"""Publish checked progress or final aggregates for the complete candidate census.

Progress never classifies unfinished positions or reports new outcome totals.
Final reporting recomputes every outcome from exact exhaustive legal-root
evidence. Public output contains no positions, moves, identifiers or paths.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import mining_v3_deep as old_runner
import mining_v3_full_deep as runner
import mining_v3_full_deep_selection as selector
from mining_v3_deep_summary import checked_hash, distribution, finite_number, selection_timing
from mining_v2_sampling import canonical_fen
from mining_v3_io import digest, rows, write_manifest

TOTAL_N = 4345
IMPORTED_N = 200
OBSERVATIONS_N = 4353
STRATA = {
    "bot_status": {"no_bot", "bot_tagged", "unknown"},
    "history_status": {"recovered", "unavailable", "unknown"},
    "public_exposure": {"known_public", "not_known_public", "unknown"},
    "analysis_role": {"prior_development", "pilot_train", "pilot_validation", "pilot_test",
                      "new_train", "new_validation", "new_test", "public_exposed", "unknown"},
}
PROVENANCE_FLAGS = ("any_bot_tagged", "any_unknown_bot_status", "any_known_public",
                    "any_unknown_public_exposure", "any_unavailable_history", "any_unknown_history",
                    "all_origins_recovered_no_bot_not_known_public")


def read_prefix(path, byte_count, expected_hash):
    """Read only a durable checkpoint, ignoring a concurrently appended tail."""
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
        raise ValueError("Invalid root checkpoint byte count")
    with Path(path).open("rb") as source:
        payload = source.read(byte_count)
    if len(payload) != byte_count or hashlib.sha256(payload).hexdigest() != expected_hash:
        raise ValueError("Durable root checkpoint prefix hash changed")
    if payload and not payload.endswith(b"\n"):
        raise ValueError("Root checkpoint ends inside a record")
    values = []
    for line in payload.splitlines():
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid root checkpoint JSON") from exc
        if not isinstance(value, dict) or not isinstance(value.get("id"), str):
            raise ValueError("Invalid root checkpoint identity")
        values.append(value)
    return values


def check_root_fields(root, record, legal):
    """Cheap progress validation; full PV replay is reserved for final results."""
    depth, move = root.get("target_depth"), root.get("uci")
    if (depth not in (20, 24) or isinstance(depth, bool) or not isinstance(depth, int) or
            move not in legal or root.get("record_id") != record["id"] or
            root.get("id") != old_runner.task_id(record["id"], depth, move) or
            root.get("fen") != record["fen"] or root.get("board_context") != "fen_only"):
        raise ValueError("Root is outside the exact frozen legal-root plan")
    achieved = root.get("depth")
    if (not isinstance(achieved, int) or isinstance(achieved, bool) or achieved < depth or
            root.get("reached_target") is not True or root.get("score_is_exact") is not True or
            root.get("lowerbound") or root.get("upperbound")):
        raise ValueError("Root lacks an exact target-depth score")
    cp, mate = root.get("cp"), root.get("mate")
    if not ((finite_number(cp) and mate is None) or
            (cp is None and isinstance(mate, int) and not isinstance(mate, bool))):
        raise ValueError("Root score must be numeric or typed mate")
    if (not finite_number(root.get("wall_seconds")) or root["wall_seconds"] < 0 or
            not isinstance(root.get("nodes"), int) or isinstance(root["nodes"], bool) or root["nodes"] <= 0):
        raise ValueError("Root lacks valid timing or node evidence")


def attempt_timing(run, snapshot_at, complete):
    """Attempt clocks include host sleep; they never estimate CPU time."""
    attempts = run.get("attempts")
    start = run.get("started_at")
    if not finite_number(start) or not finite_number(snapshot_at) or snapshot_at < start:
        raise ValueError("Invalid run timing bounds")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("Run has no attempt timing records")
    closed, monotonic, open_elapsed, missing_prior, missing_monotonic = [], [], None, 0, 0
    previous_start, previous_end = None, None
    for index, attempt in enumerate(attempts):
        begin, end = attempt.get("started_at"), attempt.get("finished_at")
        if not finite_number(begin) or begin < start or begin > snapshot_at:
            raise ValueError("Attempt start is outside the snapshot interval")
        if ((previous_start is not None and begin < previous_start) or
                (previous_end is not None and begin < previous_end)):
            raise ValueError("Attempt intervals are not chronological")
        if end is None:
            if index == len(attempts) - 1:
                if complete:
                    raise ValueError("Completed run has an open final attempt")
                open_elapsed = snapshot_at - begin
            else:
                missing_prior += 1
            previous_end = None
        else:
            if not finite_number(end) or end < begin or end > snapshot_at:
                raise ValueError("Attempt finish is outside the snapshot interval")
            closed.append(end - begin)
            elapsed = attempt.get("monotonic_elapsed_seconds")
            if elapsed is None:
                missing_monotonic += 1
            elif not finite_number(elapsed) or elapsed < 0:
                raise ValueError("Invalid recorded attempt monotonic duration")
            else:
                monotonic.append(elapsed)
            previous_end = end
        previous_start = begin
    if complete and attempts[-1].get("complete") is not True:
        raise ValueError("Final attempt was not completed")
    measured = sum(closed) + (open_elapsed or 0.)
    return {"attempts_n": len(attempts), "closed_attempts_n": len(closed),
            "unfinished_prior_attempts_n": missing_prior,
            "closed_attempt_elapsed_wall_seconds": sum(closed),
            "closed_attempt_recorded_monotonic_seconds": sum(monotonic) if missing_monotonic == 0 else None,
            "closed_attempts_missing_monotonic_timing_n": missing_monotonic,
            "open_attempt_elapsed_wall_seconds_to_checkpoint": open_elapsed,
            "attempt_elapsed_wall_seconds_to_checkpoint": measured if missing_prior == 0 else None,
            "run_elapsed_wall_seconds_to_checkpoint": snapshot_at - start,
            "active_compute_seconds": None, "host_suspension_measured": False,
            "host_suspension_seconds": None,
            "interpretation": "These attempt wall-clock intervals concern only this new run, including any host suspension within attempts and excluding gaps between attempts. Recorded closed-attempt monotonic durations are separate elapsed-clock measurements, not CPU time; their difference from wall time is not used to infer sleep. Imported searches were performed earlier. Active compute and host suspension were not measured; missing prior finish times are not imputed."}


def outcome_counts(values):
    """Only call with fully recomputed position results."""
    values = list(values)
    return {"checked_n": len(values),
            "engine_verified_n": sum(row["engine_verified"] for row in values),
            "survives_candidate_criterion_n": sum(row["survives"] for row in values),
            "trainer_ready_n": 0,
            "failure_reasons_overlapping": dict(Counter(reason for row in values for reason in row["reasons"]))}


def group_counts(identifiers, completed, imported, recomputed=None):
    identifiers = set(identifiers)
    done = identifiers & completed
    return {"planned_n": len(identifiers), "completed_n": len(done),
            "pending_n": len(identifiers - completed),
            "imported_completed_n": len(done & imported),
            "new_completed_n": len(done - imported),
            "outcomes": outcome_counts(recomputed[key] for key in identifiers) if recomputed is not None else None}


def anchored_rows(path, byte_count, expected_hash):
    """Stream a checked prefix with offsets, without holding all PVs in memory."""
    if type(byte_count) is not int or byte_count < 0:
        raise ValueError("Invalid checkpoint byte count")
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        remaining = byte_count
        while remaining:
            block = stream.read(min(1024 * 1024, remaining))
            if not block:
                raise ValueError("Truncated root checkpoint")
            hasher.update(block)
            remaining -= len(block)
        if hasher.hexdigest() != expected_hash:
            raise ValueError("Root checkpoint prefix hash changed")
        stream.seek(0)
        while stream.tell() < byte_count:
            offset = stream.tell()
            line = stream.readline(byte_count - offset)
            if not line.endswith(b"\n"):
                raise ValueError("Checkpoint ends inside a root record")
            try:
                value = json.loads(line)
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError("Invalid root checkpoint JSON") from exc
            if not isinstance(value, dict) or not isinstance(value.get("id"), str):
                raise ValueError("Invalid root identity")
            yield value, offset, len(line)


def validate_census(args, run):
    records, policies, census, legal, strata, line_hashes = runner.load_census(args)
    ids = {row["id"] for row in records}
    imported = census.get("already_deep200_ids", [])
    if (len(records) != TOTAL_N or len(imported) != IMPORTED_N or len(set(imported)) != IMPORTED_N or
            not set(imported) <= ids or census.get("already_deep200_n") != IMPORTED_N or
            census.get("new_n") != TOTAL_N - IMPORTED_N):
        raise ValueError("Census must contain the exact full and imported position counts")
    checked_hash(selector.__file__, census.get("selection_script_sha256"), "Census selection implementation")
    protocol_path = Path(args.selection_manifest).parent / "selection_protocol.json"
    checked_hash(protocol_path, census.get("selection_protocol_sha256"), "Census selection protocol")
    protocol = json.loads(protocol_path.read_text())
    if (protocol.get("expected_n") != TOTAL_N or protocol.get("initial_n") != IMPORTED_N or
            protocol.get("seed") != census.get("seed") or
            protocol.get("input_hashes") != census.get("input_hashes") or
            protocol.get("initial_selection_hashes") != census.get("initial_selection_hashes") or
            protocol.get("selection_script_sha256") != census.get("selection_script_sha256") or
            protocol.get("selection_function_sha256") != hashlib.sha256(inspect.getsource(selector.choose_census).encode()).hexdigest() or
            protocol.get("screen_gate_function_sha256") != hashlib.sha256(inspect.getsource(selector.is_screen_candidate).encode()).hexdigest()):
        raise ValueError("Census protocol and frozen selection disagree")
    freeze = selection_timing(census, protocol, run.get("started_at"))
    for key, expected in (("sources", census.get("original_position_line_sha256")),
                          ("policies", census.get("original_policy_line_sha256"))):
        if line_hashes[key] != expected:
            raise ValueError("Census export differs from original source or policy bytes")
    origins, provenance = census.get("canonical_origins_by_id", {}), census.get("state_provenance_by_id", {})
    if set(origins) != ids or set(provenance) != ids:
        raise ValueError("Census does not cover every canonical state's origins")
    origin_ids = set()
    for record in records:
        identifier = record["id"]
        group = origins[identifier]
        if not isinstance(group, list) or not group or identifier not in {item.get("id") for item in group}:
            raise ValueError("Canonical origins omit their representative")
        for origin in group:
            if (not isinstance(origin.get("id"), str) or origin["id"] in origin_ids or
                    not isinstance(origin.get("game_id"), str) or not origin["game_id"] or
                    origin.get("side_to_move") != record["side_to_move"] or
                    type(origin.get("public_game_detected")) is not bool or
                    set(origin.get("strata", {})) != set(STRATA) or
                    any(origin["strata"][key] not in allowed for key, allowed in STRATA.items())):
                raise ValueError("Invalid or repeated canonical source origin")
            origin_ids.add(origin["id"])
            if origin["id"] == identifier and (origin["game_id"] != record["game_id"] or origin["strata"] != strata[identifier]):
                raise ValueError("Representative origin differs from its input metadata")
        if provenance[identifier] != selector.state_provenance(group):
            raise ValueError("Any-origin exposure differs from its recorded source observations")
    if len(origin_ids) != OBSERVATIONS_N or census.get("counts", {}).get("screen_candidates_n") != OBSERVATIONS_N:
        raise ValueError("Canonical origins do not cover all candidate observations")
    return records, policies, census, legal, strata, set(imported), freeze


def prior_completed_counts(path, reuse, imported_n, imported_roots_n):
    checked_hash(path, reuse.get("prior_public_summary_sha256"), "Prior public summary")
    previous = json.loads(Path(path).read_text())
    if previous.get("complete") is not True:
        raise ValueError("Prior public report is incomplete")
    for key in ("input_sha256", "policy_sha256", "selection_manifest_sha256", "roots_sha256",
                "positions_sha256", "run_manifest_sha256"):
        if previous.get("fingerprints", {}).get(key) != reuse.get(key):
            raise ValueError("Prior public report does not refer to the imported evidence")
    raw = previous.get("counts", {})
    if raw.get("checked_n") != imported_n or raw.get("root_searches_n") != imported_roots_n:
        raise ValueError("Prior public report has different sample or root counts")
    def clean(value, n):
        engine, survives = value.get("engine_verified_n"), value.get("survives_candidate_criterion_n")
        if (type(engine) is not int or type(survives) is not int or
                not 0 <= survives <= engine <= n or value.get("trainer_ready_n") != 0):
            raise ValueError("Prior public report has invalid outcome counts")
        return {"checked_n": n, "engine_verified_n": engine,
                "survives_candidate_criterion_n": survives, "trainer_ready_n": 0}
    result = clean(raw, imported_n)
    result["root_searches_n"] = imported_roots_n
    result["by_side"] = {}
    for side in ("white", "black"):
        group = raw.get("by_side", {}).get(side, {})
        if group.get("n") != imported_n // 2:
            raise ValueError("Prior public report has different colour counts")
        result["by_side"][side] = clean(group, group["n"])
    result["interpretation"] = "Previously completed and published initial batch; imported evidence is not new computation. Its outcomes are not a prediction for the remaining census."
    return result


def build_summary(input_path, policy_path, selection_path, run_dir,
                  engine_path=old_runner.base.DEFAULT_ENGINE, require_complete=False,
                  prior_summary_path=ROOT / "results/mining_v3_deep200.json"):
    args = SimpleNamespace(input=Path(input_path), policies=Path(policy_path), selection_manifest=Path(selection_path))
    run_dir, engine_path = Path(run_dir), Path(engine_path)
    run_path, checkpoint_path = run_dir / "run.json", run_dir / "checkpoint.json"
    run_bytes, checkpoint_bytes = run_path.read_bytes(), checkpoint_path.read_bytes()
    run, checkpoint = json.loads(run_bytes), json.loads(checkpoint_bytes)
    complete = run.get("complete") is True
    if require_complete and not complete:
        raise ValueError("The full census must finish before final outcome reporting")
    records, policies, census, legal, strata, imported, freeze = validate_census(args, run)
    index = {row["id"]: row for row in records}
    settings = run.get("settings", {})
    expected = {**runner.SCORE_SETTINGS, "python_chess_version": chess.__version__}
    if any(key not in settings or settings[key] != value for key, value in expected.items()):
        raise ValueError("Full census used a different scoring contract")
    if type(settings.get("workers")) is not int or settings["workers"] <= 0:
        raise ValueError("Invalid worker count")
    fingerprints = runner.scoring_fingerprints(engine_path)
    if any(settings.get(key) != value for key, value in fingerprints.items()):
        raise ValueError("Frozen engine or scoring implementation hash changed")
    if fingerprints["original_runner_sha256"] != runner.FROZEN_DEEP200_SHA256:
        raise ValueError("The original scoring contract changed")
    for key, path in (("input_sha256", args.input), ("policy_sha256", args.policies),
                      ("selection_manifest_sha256", args.selection_manifest)):
        fingerprints[key] = checked_hash(path, settings.get(key), key)
    settings_hash = hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if run.get("settings_sha256") != settings_hash or checkpoint.get("settings_sha256") != settings_hash:
        raise ValueError("Run or checkpoint settings hash changed")
    reuse = settings.get("reuse", {})
    if run.get("reuse", {}).get("fingerprints") != reuse:
        raise ValueError("Run import provenance differs from frozen settings")
    if (census.get("old200_selection_manifest_sha256") != reuse.get("selection_manifest_sha256") or
            census.get("initial_selection_hashes", {}).get("positions.jsonl") != reuse.get("input_sha256") or
            census.get("initial_selection_hashes", {}).get("policies.jsonl") != reuse.get("policy_sha256")):
        raise ValueError("Census original selection hashes do not identify the imported batch")
    imported_roots_n = 2 * sum(len(legal[key]) for key in imported)
    total_roots_n = 2 * sum(map(len, legal.values()))
    plan = {"input_n": TOTAL_N, "root_searches_n": total_roots_n,
            "imported_positions_n": IMPORTED_N, "imported_root_searches_n": imported_roots_n,
            "planned_new_positions_n": TOTAL_N - IMPORTED_N,
            "planned_new_root_searches_n": total_roots_n - imported_roots_n}
    if any(run.get(key) != value for key, value in plan.items()):
        raise ValueError("Run plan differs from exact census coverage")
    previous = prior_completed_counts(prior_summary_path, reuse, IMPORTED_N, imported_roots_n)
    imported_path, new_path = run_dir / "imported_roots.jsonl", run_dir / "roots.jsonl"
    imported_hash = checked_hash(imported_path, reuse.get("roots_sha256"), "Imported roots")
    if run.get("imported_roots_sha256") != imported_hash:
        raise ValueError("Imported root hash differs from the run manifest")
    locations, seen, root_times, root_nodes = defaultdict(list), set(), defaultdict(list), Counter()
    for origin, path, size, fingerprint in (("imported", imported_path, imported_path.stat().st_size, imported_hash),
                                           ("new", new_path, checkpoint.get("bytes"), checkpoint.get("sha256"))):
        for root, offset, length in anchored_rows(path, size, fingerprint):
            identifier = root.get("record_id")
            if identifier not in index or root["id"] in seen or (identifier in imported) != (origin == "imported"):
                raise ValueError("Duplicate, unexpected, or misattributed root evidence")
            if origin == "new" and (root.get("evidence_origin") != "new_full_census" or
                    type(root.get("attempt_index")) is not int or
                    not 1 <= root["attempt_index"] <= len(run.get("attempts", []))):
                raise ValueError("New root has invalid attempt provenance")
            check_root_fields(root, index[identifier], legal[identifier])
            seen.add(root["id"])
            locations[identifier].append((path, offset, length))
            root_times[origin].append(root["wall_seconds"])
            root_times[f"{origin}_{root['target_depth']}"].append(root["wall_seconds"])
            root_nodes[origin] += root["nodes"]
    if len(root_times["imported"]) != imported_roots_n or len(root_times["new"]) != checkpoint.get("root_searches_n"):
        raise ValueError("Anchored root counts differ from imported or new checkpoint counts")
    completed = {key for key in index if len(locations[key]) == 2 * len(legal[key])}
    if not imported <= completed:
        raise ValueError("Imported positions lack full root coverage")
    new_completed = completed - imported
    if complete and (len(completed) != TOTAL_N or len(seen) != total_roots_n):
        raise ValueError("Completed census has incomplete legal-root coverage")
    recomputed = None
    if complete:
        if new_path.stat().st_size != checkpoint["bytes"]:
            raise ValueError("Completed new roots contain unanchored bytes")
        checked_hash(new_path, run.get("roots_sha256"), "Final new roots")
        if checkpoint["sha256"] != run["roots_sha256"]:
            raise ValueError("Final root and checkpoint hashes disagree")
        position_path = run_dir / "positions.jsonl"
        checked_hash(position_path, run.get("positions_sha256"), "Final positions")
        final_counts = {"completed_positions_n": TOTAL_N, "completed_new_positions_n": TOTAL_N - IMPORTED_N,
                        "completed_root_searches_n": total_roots_n,
                        "completed_new_root_searches_n": total_roots_n - imported_roots_n}
        if any(run.get(key) != value for key, value in final_counts.items()):
            raise ValueError("Final manifest counts disagree with exhaustive coverage")
        saved = iter(runner.strict_rows(position_path))
        recomputed = {}
        with imported_path.open("rb") as imported_stream, new_path.open("rb") as new_stream:
            handles = {imported_path: imported_stream, new_path: new_stream}
            for record, policy in zip(records, policies):
                evidence = []
                for path, offset, length in locations[record["id"]]:
                    stream = handles[path]
                    stream.seek(offset)
                    evidence.append(json.loads(stream.read(length)))
                result = runner.summarize_record(record, policy, evidence, strata[record["id"]], record["id"] in imported)
                stored = next(saved, (None, None, None))[0]
                if result != stored:
                    raise ValueError("Saved final outcome differs from exhaustive recomputation")
                recomputed[record["id"]] = {key: result[key] for key in ("engine_verified", "survives", "reasons", "has_mate",
                    "best_cp", "best_moves", "accepted", "candidate_criterion_by_depth", "root_search_seconds_sum", "nodes")}
        if next(saved, None) is not None:
            raise ValueError("Final position output contains extra records")
        old_counts = outcome_counts(recomputed[key] for key in imported)
        if any(old_counts[key] != previous[key] for key in ("checked_n", "engine_verified_n", "survives_candidate_criterion_n", "trainer_ready_n")):
            raise ValueError("Imported outcomes differ from the previously published batch")
    snapshot_at = run.get("finished_at") if complete else max(run.get("updated_at", run["started_at"]), checkpoint["updated_at"])
    timing = attempt_timing(run, snapshot_at, complete)
    groups = {"by_side": {side: group_counts([row["id"] for row in records if row["side_to_move"] == side], completed, imported, recomputed)
                           for side in ("white", "black")},
              "by_evidence_origin": {"imported_deep200": group_counts(imported, completed, imported, recomputed),
                                     "new_full_census": group_counts(set(index) - imported, completed, imported, recomputed)},
              "representative_strata": {key: {value: group_counts([identifier for identifier in index if strata[identifier][key] == value], completed, imported, recomputed)
                                               for value in sorted(allowed)} for key, allowed in STRATA.items()},
              "any_origin_provenance": {flag: group_counts([identifier for identifier in index if census["state_provenance_by_id"][identifier][flag]], completed, imported, recomputed)
                                         for flag in PROVENANCE_FLAGS}}
    all_origins = [origin for group in census["canonical_origins_by_id"].values() for origin in group]
    games = Counter(row["game_id"] for row in records)
    counts = {"planned_n": TOTAL_N, "completed_positions_n": len(completed), "pending_positions_n": TOTAL_N - len(completed),
              "imported_completed_positions_n": IMPORTED_N, "new_completed_positions_n": len(new_completed),
              "new_pending_positions_n": TOTAL_N - IMPORTED_N - len(new_completed),
              "partially_searched_positions_n": sum(0 < len(locations[key]) < 2 * len(legal[key]) for key in index),
              "planned_root_searches_n": total_roots_n, "completed_root_searches_n": len(seen),
              "imported_root_searches_n": imported_roots_n, "new_completed_root_searches_n": len(root_times["new"]),
              "new_pending_root_searches_n": total_roots_n - len(seen),
              **(outcome_counts(recomputed.values()) if complete else {"checked_n": None, "engine_verified_n": None,
                  "survives_candidate_criterion_n": None, "trainer_ready_n": 0, "failure_reasons_overlapping": None})}
    depth_changes = None
    if complete:
        numeric = [row for row in recomputed.values() if not row["has_mate"]]
        depth_changes = {"numeric_positions_n": len(numeric),
                         "best_score_change_cp": distribution([row["best_cp"]["24"] - row["best_cp"]["20"] for row in numeric]),
                         "absolute_best_score_change_cp": distribution([abs(row["best_cp"]["24"] - row["best_cp"]["20"]) for row in numeric]),
                         "best_move_set_changed_n": sum(row["best_moves"]["24"] != row["best_moves"]["20"] for row in numeric),
                         "acceptable_move_set_changed_n": sum(row["accepted"]["24"] != row["accepted"]["20"] for row in numeric),
                         "interpretation": "Depth 20 versus 24. Numeric score and move-set comparisons exclude positions with any mate-valued root."}
    fingerprints.update(settings_sha256=settings_hash, imported_roots_sha256=imported_hash,
                        new_roots_checkpoint_sha256=checkpoint["sha256"],
                        run_manifest_snapshot_sha256=hashlib.sha256(run_bytes).hexdigest(),
                        checkpoint_manifest_snapshot_sha256=hashlib.sha256(checkpoint_bytes).hexdigest(),
                        prior_public_summary_sha256=reuse["prior_public_summary_sha256"],
                        summary_builder_sha256=digest(__file__))
    if complete:
        fingerprints.update(positions_sha256=run["positions_sha256"], new_roots_sha256=run["roots_sha256"])
    return {"schema_version": 1, "complete": complete,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "checkpoint_at": datetime.fromtimestamp(checkpoint["updated_at"], timezone.utc).isoformat(),
            "scope": "Census of all distinct first-pass candidate states, retaining the initial 200 checks and computing the remainder under the same depth-20/24 contract.",
            "selection": {**freeze, "candidate_observations_n": OBSERVATIONS_N, "distinct_candidate_states_n": TOTAL_N,
                          "canonical_repeat_observations_n": OBSERVATIONS_N - TOTAL_N,
                          "unique_representative_source_games_n": len(games),
                          "unique_origin_source_games_n": len({origin["game_id"] for origin in all_origins}),
                          "maximum_selected_positions_per_source_game": max(games.values()),
                          "source_stratum_exclusions_n": 0},
            "engine": {**runner.SCORE_SETTINGS, "workers": settings["workers"], "python_chess_version": chess.__version__},
            "counts": counts, "previously_completed_initial_batch": previous, "groups": groups,
            "depth_changes": depth_changes,
            "runtime": {"new_run_attempts": timing,
                        "imported_root_search_seconds": distribution(root_times["imported"]),
                        "new_root_search_seconds": distribution(root_times["new"]),
                        "root_search_seconds_by_origin_and_depth": {key: distribution(root_times[key]) for key in ("imported_20", "imported_24", "new_20", "new_24")},
                        "imported_nodes": root_nodes["imported"], "new_nodes": root_nodes["new"],
                        "completed_position_root_search_seconds": {origin: distribution([row["root_search_seconds_sum"] for key, row in recomputed.items() if (key in imported) == (origin == "imported")]) for origin in ("imported", "new")} if complete else None,
                        "interpretation": "Imported root durations and nodes are historical work, not new computation. Recorded root monotonic-clock durations overlap across workers and are neither CPU time nor total job elapsed time. No host-suspension duration is inferred or subtracted; no continuous-compute completion forecast is made.",
                        "quantile_method": "Linear interpolation at p*(n-1)."},
            "validation": {"frozen_hashes_checked": True, "durable_new_root_prefix_checked": True,
                           "root_identities_exact_scores_and_depths_checked": True,
                           "all_legal_roots_covered": complete, "all_root_pvs_replayed": complete,
                           "all_outcomes_recomputed": complete, "saved_outcomes_match_recomputation": complete,
                           "any_origin_exposure_recomputed": True},
            "fingerprints": fingerprints,
            "limitations": ["Completed progress counts describe root coverage, not success or failure; new outcome totals are withheld until final recomputation.",
                            "The census covers first-pass candidates, not all chess positions; no human solving or learning effect is estimated.",
                            "Several states can come from the same game. Removing the earlier one-game cap does not make source observations independent.",
                            "BOT tags, missing histories, unknown sources and public exposure are reported separately. Any-origin flags overlap and must not be added as mutually exclusive groups.",
                            "Recovered origins without BOT tags or known public exposure are an archive stratum, not proof of unassisted human play or fresh held-out data.",
                            "Engine stability, retained candidate criteria and trainer readiness are separate; every trainer-ready count remains zero.",
                            "Private positions, moves, game identities, histories and filesystem paths are excluded from this aggregate."]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=ROOT / "data/mining_v3/deep_all/positions.jsonl")
    ap.add_argument("--policies", type=Path, default=ROOT / "data/mining_v3/deep_all/policies.jsonl")
    ap.add_argument("--selection-manifest", type=Path, default=ROOT / "data/mining_v3/deep_all/selection_manifest.json")
    ap.add_argument("--run-dir", type=Path, default=ROOT / "results/mining_v3/deep_all")
    ap.add_argument("--engine", type=Path, default=old_runner.base.DEFAULT_ENGINE)
    ap.add_argument("--prior-summary", type=Path, default=ROOT / "results/mining_v3_deep200.json")
    ap.add_argument("--output", type=Path, default=ROOT / "results/mining_v3_full_deep.json")
    ap.add_argument("--require-complete", action="store_true")
    args = ap.parse_args()
    protected = {args.input.resolve(), args.policies.resolve(), args.selection_manifest.resolve(),
                 args.engine.resolve(), args.prior_summary.resolve(),
                 (args.selection_manifest.parent / "selection_protocol.json").resolve(),
                 *(args.run_dir.joinpath(name).resolve() for name in ("run.json", "checkpoint.json", "roots.jsonl", "imported_roots.jsonl", "positions.jsonl"))}
    if args.output.resolve() in protected:
        ap.error("Public reporting must not overwrite frozen evidence")
    result = build_summary(args.input, args.policies, args.selection_manifest, args.run_dir,
                           args.engine, args.require_complete, args.prior_summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(args.output, result)
    print(json.dumps({"complete": result["complete"], "counts": result["counts"]}, indent=2))


if __name__ == "__main__":
    main()
