"""Publish aggregate depth-20/24 evidence only after the entire frozen batch ends.

Every legal-root checkpoint is validated and every position is recomputed from
the frozen policies. Public output deliberately excludes chess positions,
source-game identities, moves, histories and filesystem paths.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import inspect
import json
import math
from pathlib import Path
import statistics
import sys

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import mining_v3_deep as runner
import mining_v3_deep_selection as selector
from mining_v2_sampling import canonical_fen
from mining_v3_dataset import rating_band
from mining_v3_io import digest, rows, write_manifest

SAMPLE_N = 200
PER_SIDE = 100
DISTINCT_CANDIDATES = 4345
REMAINING_CANDIDATES = DISTINCT_CANDIDATES - SAMPLE_N


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "sum": 0, "mean": None, "median": None, "p90": None,
                "minimum": None, "maximum": None}
    if any(not finite_number(value) for value in values):
        raise ValueError("Aggregate contains a non-finite quantity")
    # Linear interpolation of the empirical quantile, stated in the public file.
    location = .9 * (len(values) - 1)
    lower, upper = math.floor(location), math.ceil(location)
    p90 = values[lower] + (values[upper] - values[lower]) * (location - lower)
    return {"n": len(values), "sum": sum(values), "mean": statistics.mean(values),
            "median": statistics.median(values), "p90": p90,
            "minimum": values[0], "maximum": values[-1]}


def checked_hash(path, expected, label):
    actual = digest(path)
    if not isinstance(expected, str) or actual != expected:
        raise ValueError(f"{label} hash changed")
    return actual


def selection_timing(selection, protocol, run_started_at):
    """Check available freeze timestamps without inferring missing dates."""
    if not finite_number(run_started_at):
        raise ValueError("Run start time is invalid")
    timestamps = {}
    for key, document in (("frozen_at", selection), ("protocol_declared_at", protocol)):
        value = document.get("created_at")
        if value is None:
            timestamps[key] = None
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"Selection {key} timestamp is invalid") from exc
        if parsed.utcoffset() is None:
            raise ValueError(f"Selection {key} timestamp has no timezone")
        parsed = parsed.astimezone(timezone.utc)
        if parsed.timestamp() >= run_started_at:
            raise ValueError(f"Selection {key} must precede the run start")
        timestamps[key] = parsed
    frozen, declared = timestamps["frozen_at"], timestamps["protocol_declared_at"]
    if frozen is not None and declared is not None and declared > frozen:
        raise ValueError("Selection protocol was declared after the selection freeze")
    return {**{key: value.isoformat() if value is not None else None for key, value in timestamps.items()},
            "freeze_precedes_run_checked": frozen is not None,
            "protocol_precedes_run_checked": declared is not None}


def validate_attempts(run):
    """Measure attempt clock intervals, without inferring active compute time."""
    attempts = run.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("Run has no attempt timing records")
    durations, missing = [], 0
    previous_start, previous_end = None, None
    for attempt in attempts:
        start, end = attempt.get("started_at"), attempt.get("finished_at")
        if not finite_number(start):
            raise ValueError("Attempt has an invalid start time")
        if previous_start is not None and start < previous_start:
            raise ValueError("Attempt start times are not chronological")
        if previous_end is not None and start < previous_end:
            raise ValueError("Attempt timing intervals overlap")
        if end is None:
            missing += 1
            previous_end = None
        else:
            if not finite_number(end) or end < start:
                raise ValueError("Attempt has an invalid finish time")
            durations.append(end - start)
            previous_end = end
        previous_start = start
    if attempts[-1].get("complete") is not True or attempts[-1].get("finished_at") is None:
        raise ValueError("The final attempt has not completed")
    first, last = run.get("started_at"), run.get("finished_at")
    if not finite_number(first) or not finite_number(last) or last < first:
        raise ValueError("Run timing bounds are invalid")
    if attempts[0]["started_at"] < first or attempts[-1]["finished_at"] > last:
        raise ValueError("Attempt timing is outside the run interval")
    complete = missing == 0
    return {"attempts_n": len(attempts), "closed_attempts_n": len(durations),
            "unfinished_prior_attempts_n": missing, "attempt_timing_complete": complete,
            "closed_attempt_seconds_sum": sum(durations),
            "attempt_elapsed_wall_seconds": sum(durations) if complete else None,
            "active_attempt_wall_seconds": None,
            "host_suspension_measured": False,
            "host_suspension_seconds": None,
            "elapsed_wall_seconds_including_pauses": last - first,
            "outside_attempt_seconds": max(0., last - first - sum(durations)) if complete else None,
            "interpretation": "Attempt elapsed time sums recorded wall-clock intervals and excludes gaps between explicit runner attempts. It includes host sleep or suspension within an attempt. Host suspension and active compute time were not measured; no sleep duration is inferred or subtracted. The legacy active_attempt_wall_seconds field is null. Missing prior finish times are not imputed."}


def validate_selection(input_path, policy_path, selection_path):
    selection = json.loads(selection_path.read_text())
    records, policies = list(rows(input_path)), list(rows(policy_path))
    identifiers = [record["id"] for record in records]
    if (selection.get("complete") is not True or selection.get("selected_n") != SAMPLE_N or
            len(records) != SAMPLE_N or len(set(identifiers)) != SAMPLE_N or
            identifiers != selection.get("selected_ids") or identifiers != [p["id"] for p in policies]):
        raise ValueError("The frozen selection must have exactly 200 unique, ordered input and policy identities")
    checked_hash(input_path, selection.get("positions_sha256"), "Selected inputs")
    checked_hash(policy_path, selection.get("policies_sha256"), "Selected policies")
    checked_hash(selector.__file__, selection.get("selection_script_sha256"), "Selection implementation")
    protocol_path = selection_path.parent / "selection_protocol.json"
    checked_hash(protocol_path, selection.get("selection_protocol_sha256"), "Selection protocol")
    protocol = json.loads(protocol_path.read_text())
    if (protocol.get("seed") != selection.get("seed") or
            protocol.get("per_side_target") != PER_SIDE or selection.get("per_side_target") != PER_SIDE or
            protocol.get("input_hashes") != selection.get("input_hashes") or
            protocol.get("selection_script_sha256") != selection.get("selection_script_sha256") or
            protocol.get("selection_function_sha256") != hashlib.sha256(inspect.getsource(selector.choose_candidates).encode()).hexdigest() or
            protocol.get("screen_gate_function_sha256") != hashlib.sha256(inspect.getsource(selector.is_screen_candidate).encode()).hexdigest()):
        raise ValueError("Selection declaration and frozen manifest disagree")
    if Counter(r["side_to_move"] for r in records) != Counter(white=PER_SIDE, black=PER_SIDE):
        raise ValueError("The frozen sample must contain 100 observations of each colour")
    if len({r["game_id"] for r in records}) != SAMPLE_N or len({canonical_fen(r["fen"]) for r in records}) != SAMPLE_N:
        raise ValueError("The frozen sample repeats a source game or canonical state")
    legal_counts = {}
    for record, policy in zip(records, policies):
        legal_counts[record["id"]] = selector.check_selected_policy(record, policy)
    with policy_path.open("rb") as stream:
        lines = stream.readlines()
    if len(lines) != SAMPLE_N:
        raise ValueError("Policy export does not contain exactly 200 physical lines")
    expected_lines = selection.get("original_policy_line_sha256", {})
    if set(expected_lines) != set(identifiers) or any(hashlib.sha256(line).hexdigest() != expected_lines[key] for key, line in zip(identifiers, lines)):
        raise ValueError("Selected policies differ from the frozen original policy bytes")
    return records, policies, selection, legal_counts


def safe_categories(records):
    vocabularies = {"cohort": {"club", "elite"}, "phase": {"opening", "middlegame", "endgame"},
                    "split": {"train", "validation", "test"},
                    "analysis_role": {"prior_development", "pilot_train", "pilot_validation", "pilot_test",
                                      "new_train", "new_validation", "new_test", "public_exposed"}}
    result = {key: dict(Counter(r.get(key) if r.get(key) in allowed else "unknown" for r in records))
              for key, allowed in vocabularies.items()}
    result["rating_band"] = dict(Counter(rating_band(r["mover_elo"]) for r in records))
    return result


def build_summary(input_path, policy_path, selection_path, run_dir, engine_path=runner.base.DEFAULT_ENGINE):
    input_path, policy_path, selection_path, run_dir, engine_path = map(Path, (input_path, policy_path, selection_path, run_dir, engine_path))
    run_path, root_path, position_path = run_dir / "run.json", run_dir / "roots.jsonl", run_dir / "positions.jsonl"
    run = json.loads(run_path.read_text())
    if run.get("complete") is not True:
        raise ValueError("The entire deep run must finish before publishing its summary")
    records, policies, selection, legal_counts = validate_selection(input_path, policy_path, selection_path)
    settings = run.get("settings", {})
    expected_settings = {"depths": [20, 24], "board_context": "fen_only", "engine_threads": 1,
                         "hash_mb": 64, "clear_hash_each_search": True, "time_limit": None, "node_limit": None}
    if any(key not in settings or settings[key] != value for key, value in expected_settings.items()):
        raise ValueError("The run does not use the declared exhaustive depth-20/24 settings")
    if settings.get("python_chess_version") != chess.__version__:
        raise ValueError("Recorded python-chess version differs from the validation runtime")
    if (not isinstance(settings.get("workers"), int) or isinstance(settings["workers"], bool) or settings["workers"] < 1):
        raise ValueError("Worker count is invalid")
    freeze_timing = selection_timing(selection, json.loads((selection_path.parent / "selection_protocol.json").read_text()),
                                     run.get("started_at"))
    fingerprints = {}
    for key, path in {"input_sha256": input_path, "policy_sha256": policy_path,
                      "selection_manifest_sha256": selection_path, "engine_sha256": engine_path,
                      "runner_sha256": Path(runner.__file__), "search_and_metrics_sha256": Path(runner.base.__file__),
                      "canonicalization_sha256": ROOT / "scripts/mining_v2_sampling.py",
                      "io_sha256": ROOT / "scripts/mining_v3_io.py"}.items():
        fingerprints[key] = checked_hash(path, settings.get(key), key)
    for key, path in (("roots_sha256", root_path), ("positions_sha256", position_path)):
        fingerprints[key] = checked_hash(path, run.get(key), key)
    fingerprints["run_manifest_sha256"] = digest(run_path)
    if (run.get("roots_checkpoint_bytes") != root_path.stat().st_size or
            run.get("roots_checkpoint_sha256") != fingerprints["roots_sha256"]):
        raise ValueError("The completed root checkpoint prefix does not cover the exact output")
    expected_roots = 2 * sum(legal_counts.values())
    if (run.get("input_n") != SAMPLE_N or run.get("completed_positions_n") != SAMPLE_N or
            run.get("root_searches_n") != expected_roots or run.get("completed_root_searches_n") != expected_roots):
        raise ValueError("Completed run counts disagree with the full legal-root plan")
    index = {r["id"]: r for r in records}
    by_position, root_ids = defaultdict(list), set()
    for root in rows(root_path):
        identifier = root.get("record_id")
        if identifier not in index or root["id"] in root_ids:
            raise ValueError("Root checkpoint has an unknown or duplicate identity")
        runner.validate_root(root, index[identifier])
        root_ids.add(root["id"])
        by_position[identifier].append(root)
    if len(root_ids) != expected_roots:
        raise ValueError("The root evidence does not cover the complete plan")
    recomputed = [runner.summarize_position(record, policy, by_position[record["id"]])
                  for record, policy in zip(records, policies)]
    saved = list(rows(position_path))
    if saved != recomputed:
        raise ValueError("Saved position results differ from recomputation of the legal roots and frozen policies")
    timing = validate_attempts(run)
    reason_counts = Counter(reason for item in recomputed for reason in item["reasons"])
    by_side = {}
    for side in ("white", "black"):
        values = [item for item in recomputed if item["side_to_move"] == side]
        by_side[side] = {"n": len(values), "engine_verified_n": sum(r["engine_verified"] for r in values),
                         "survives_candidate_criterion_n": sum(r["survives"] for r in values), "trainer_ready_n": 0}
    numeric = [r for r in recomputed if not r["has_mate"]]
    all_roots = [root for roots_ in by_position.values() for root in roots_]
    per_position = distribution([r["root_search_seconds_sum"] for r in recomputed])
    root_timing = distribution([r["wall_seconds"] for r in all_roots])
    root_by_depth = {str(depth): distribution([r["wall_seconds"] for r in all_roots if r["target_depth"] == depth]) for depth in runner.DEPTHS}
    attempt_clock_cost = timing["attempt_elapsed_wall_seconds"] / SAMPLE_N if timing["attempt_timing_complete"] else None
    result = {"schema_version": 1, "complete": True, "created_at": datetime.now(timezone.utc).isoformat(),
              "scope": "Completed exhaustive depth-20/24 checks of 200 constrained random screen candidates; no teaching or human-learning validation.",
              "sample": {"n": SAMPLE_N, "by_side": {"white": PER_SIDE, "black": PER_SIDE},
                         "unique_source_games_n": SAMPLE_N, "unique_canonical_states_n": SAMPLE_N,
                         "source_histories_recovered_n": SAMPLE_N, "bot_tagged_games_n": 0,
                         "known_public_exposed_games_n": 0, "categories": safe_categories(records)},
              "selection": {"seed": selection["seed"], "per_side_target": PER_SIDE, **freeze_timing,
                            "ranking": "Declared seeded hash ranking of canonical states, at most one source game globally; no shallow score or search complexity preference."},
              "engine": {"depths": [20, 24], "board_context": "fen_only", "workers": settings["workers"],
                         "python_chess_version": chess.__version__,
                         "threads_per_worker": 1, "hash_mb_per_worker": 64, "time_limit": None, "node_limit": None,
                         "clear_hash_each_search": True},
              "counts": {"checked_n": SAMPLE_N, "root_searches_n": expected_roots,
                         "engine_verified_n": sum(r["engine_verified"] for r in recomputed),
                         "survives_candidate_criterion_n": sum(r["survives"] for r in recomputed),
                         "trainer_ready_n": 0, "by_side": by_side},
              "outcome_definitions": {"engine_verified": "Every legal root has an exact achieved-depth score at both depths, no mate-valued root, and the complete within-20cp move set is stable.",
                                      "survives_candidate_criterion": "Engine verified and the original competitive-position, low acceptable-move probability and high capped-regret criterion holds at both depths.",
                                      "trainer_ready": "Zero: explanations, chess review, teaching-family fit and study readiness have not been established."},
              "failure_reasons_overlapping": dict(reason_counts),
              "depth_changes": {"comparison": "Depth 20 versus depth 24; score changes exclude positions with any mate-valued root.",
                                "numeric_positions_n": len(numeric),
                                "best_score_change_cp": distribution([r["best_cp"]["24"] - r["best_cp"]["20"] for r in numeric]),
                                "absolute_best_score_change_cp": distribution([abs(r["best_cp"]["24"] - r["best_cp"]["20"]) for r in numeric]),
                                "best_move_set_changed_n": sum(r["best_moves"]["20"] != r["best_moves"]["24"] for r in numeric),
                                "best_move_set_comparable_n": len(numeric),
                                "acceptable_move_set_changed_n": sum(r["accepted"]["20"] != r["accepted"]["24"] for r in numeric),
                                "acceptable_move_set_comparable_n": len(numeric),
                                "candidate_criterion_by_depth": {str(depth): sum(r["candidate_criterion_by_depth"][str(depth)] for r in recomputed) for depth in runner.DEPTHS}},
              "runtime": {**timing, "root_search_seconds": root_timing, "root_search_seconds_by_depth": root_by_depth,
                          "per_position_root_search_seconds": per_position,
                          "nodes_total": sum(r["nodes"] for r in recomputed),
                          "per_position_nodes": distribution([r["nodes"] for r in recomputed]),
                          "quantile_method": "Linear interpolation at p*(n-1).",
                          "root_timing_interpretation": "Root timings are recorded monotonic-clock durations, summed across searches that may overlap. They are not CPU-time measurements or total job elapsed time; host suspension is not measured or corrected."},
              "remaining_work_planning_estimate": {"distinct_screen_candidate_states": DISTINCT_CANDIDATES,
                           "sampled_distinct_states": SAMPLE_N, "remaining_distinct_states": REMAINING_CANDIDATES,
                           "serial_root_search_hours_from_sample_mean": per_position["mean"] * REMAINING_CANDIDATES / 3600,
                           "ideal_same_worker_hours_from_root_sum": per_position["mean"] * REMAINING_CANDIDATES / settings["workers"] / 3600,
                           "attempt_elapsed_hours_from_observed_throughput": attempt_clock_cost * REMAINING_CANDIDATES / 3600 if attempt_clock_cost is not None else None,
                           "active_attempt_hours_from_observed_throughput": None,
                           "interpretation": "Nonrepresentative planning estimate only: this game-capped, colour-balanced, recovered non-BOT sample excludes some remaining candidates. Attempt throughput extrapolates elapsed clock time, including any host suspension within attempts; it is not active computation or a reliable no-sleep forecast. The legacy active_attempt_hours_from_observed_throughput field is null. Root-based estimates use recorded monotonic durations, not CPU time. Heavy search tails, hardware contention, retries and pauses can change costs; ideal parallel time is not a completion forecast."},
              "validation": {"all_input_output_hashes_checked": True, "frozen_selection_checked": True,
                             "all_legal_roots_exact_and_depth_reached": True, "position_results_recomputed": True,
                             "saved_results_match_recomputation": True, "original_fen_only_policies_preserved": True},
              "fingerprints": fingerprints,
              "limitations": ["Counts concern selected archive positions and finite engine searches, not a human success rate or learning effect.",
                               "Engine verification, retained model-surprise criterion and trainer readiness are separate outcomes.",
                               "Failure reasons overlap and must not be added as mutually exclusive categories.",
                               "Selection caps games and colours without matching other covariates; old development and pilot exposure labels are retained.",
                               "Public aggregates do not disclose positions, moves, source-game identities, histories or private file locations."]}
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=ROOT / "data/mining_v3/deep200/positions.jsonl")
    ap.add_argument("--policies", type=Path, default=ROOT / "data/mining_v3/deep200/policies.jsonl")
    ap.add_argument("--selection-manifest", type=Path, default=ROOT / "data/mining_v3/deep200/selection_manifest.json")
    ap.add_argument("--run-dir", type=Path, default=ROOT / "results/mining_v3/deep200")
    ap.add_argument("--engine", type=Path, default=runner.base.DEFAULT_ENGINE)
    ap.add_argument("--output", type=Path, default=ROOT / "results/mining_v3_deep200.json")
    args = ap.parse_args()
    protected = {args.input.resolve(), args.policies.resolve(), args.selection_manifest.resolve(),
                 args.engine.resolve(), (args.selection_manifest.parent / "selection_protocol.json").resolve(),
                 *(args.run_dir.joinpath(name).resolve() for name in ("run.json", "roots.jsonl", "positions.jsonl"))}
    if args.output.resolve() in protected:
        ap.error("The public summary must not overwrite frozen evidence")
    summary = build_summary(args.input, args.policies, args.selection_manifest, args.run_dir, args.engine)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(args.output, summary)
    print(json.dumps({"counts": summary["counts"], "runtime": summary["runtime"]}, indent=2))


if __name__ == "__main__":
    main()
