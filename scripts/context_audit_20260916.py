"""Freeze and run a small paired Maia3 history audit; never change frozen census files.

Prepare and report run without model inference. Run uses the local pinned 5M model,
2 CPU threads, and stops before the next batch when AC power is unavailable.
Private outputs are immutable inputs plus resumable, atomic paired batches.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import candidate_review as review
from editorial_diagnostics import root_scores_for, summary
from mining_v2_engine import probability_summary

SEED = "context-audit-20260916-v1"
RATINGS = (1700, 2000)
DEPTHS = ("20", "24")
CONDITIONS = ("fen_only", "history")
MAX_COUNT = 96
CHUNK = 8
MODEL = {"model": "Maia3-5M", "source_commit": "1e13597c42d4858b7cfd7cfdae01e297263364b2",
         "weights_revision": "b6559de2398d7140b985f28fd2c19fb5e47ddabe",
         "weights_sha256": "ba14208b2992d85502f5fb501934abf6aaaeb355e9f3fdf90e326911f562524f"}
SCOPE = ("Exploratory paired sensitivity within previously selected, editorial-eligible development states. "
         "Not a population estimate, human calibration, independent validation or trainer approval. "
         "All saved engine scores remain FEN-conditioned at depths 20 and 24.")


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def fingerprint(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(encoded(value))
        handle.flush()
        import os
        os.fsync(handle.fileno())
    temporary.replace(path)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def history_check(record, origins):
    """Require one unambiguous observation and a fully replayable true source history."""
    if len(origins) != 1:
        raise ValueError("multiple_origin_observations_excluded")
    if record.get("source_match_count", 1) != 1:
        raise ValueError("ambiguous_source_match")
    if record.get("history_available") is not True or not record.get("history_uci"):
        raise ValueError("missing_actual_history")
    if record.get("initial_fen") != chess.STARTING_FEN:
        raise ValueError("nonstandard_or_unverified_game_start")
    if not (record.get("source", {}).get("game_moves_sha256") or record.get("source", {}).get("pgn_sha256")):
        raise ValueError("missing_source_game_fingerprint")
    if record.get("ply") != len(record["history_uci"]) + 1:
        raise ValueError("history_ply_mismatch")
    board = chess.Board(record["initial_fen"])
    states = [board.fen()]
    for uci in record["history_uci"]:
        try:
            move = chess.Move.from_uci(uci)
        except (ValueError, TypeError) as error:
            raise ValueError("invalid_history_uci") from error
        if move not in board.legal_moves:
            raise ValueError("illegal_history_move")
        board.push(move)
        states.append(board.fen())
    if not board.is_valid() or not any(board.legal_moves):
        raise ValueError("invalid_target")
    if board.fen() != record["fen"] or states[-8:] != record.get("history_fens"):
        raise ValueError("history_target_or_cache_mismatch")
    repeated = board.is_repetition(2)
    claim = board.can_claim_threefold_repetition()
    return {"history_plies": len(record["history_uci"]), "history_tokens_including_current": min(8, len(states)),
            "target_previously_seen": repeated, "threefold_claim_available": claim,
            "fivefold_repetition": board.is_fivefold_repetition(),
            "near_fifty_move_boundary": board.halfmove_clock >= 90,
            "repetition_sensitive": repeated or claim}


def selection_bucket(record, outcome):
    values = [outcome["metrics"][d][f"maia3/fen_only/{r}"]["20"] for d in DEPTHS for r in RATINGS]
    near = max(v["p_good_upper"] for v in values) >= .075 or min(v["capped_regret_lower_cp"] for v in values) <= 75
    return (record["phase"], record["side_to_move"],
            "multiple" if len(outcome["accepted"]["24"]) > 1 else "single", "near_gate" if near else "interior")


def choose(records, outcomes, origins, count=MAX_COUNT):
    """Equal phase/side quotas, round-robin multiplicity/margin, no shared source aliases."""
    if type(count) is not int or count < 6 or count > MAX_COUNT or count % 6:
        raise ValueError("count must be a multiple of six from 6 through 96")
    buckets = defaultdict(list)
    checks, excluded = {}, {}
    for key in sorted(records):
        try:
            checks[key] = history_check(records[key], origins[key])
        except ValueError as error:
            excluded[key] = str(error)
            continue
        bucket = selection_bucket(records[key], outcomes[key])
        if bucket[0] not in ("opening", "middlegame", "endgame") or bucket[1] not in ("white", "black"):
            excluded[key] = "unknown_phase_or_side"
            del checks[key]
            continue
        buckets[bucket].append(key)
    for values in buckets.values():
        values.sort(key=lambda key: hashlib.sha256((SEED + "|" + key).encode()).hexdigest())
    queues = {key: deque(value) for key, value in buckets.items()}
    # Scarce endgames go first so a middlegame cannot consume their only source game.
    primary = [(phase, side) for phase in ("endgame", "opening", "middlegame") for side in ("white", "black")]
    order = {cell: deque((cell + (multi, margin)) for multi in ("single", "multiple")
                         for margin in ("near_gate", "interior")) for cell in primary}
    quota = count // 6
    selected, used, collisions = [], set(), set()
    deficits = {}
    for cell in primary:
        picked = 0
        for _ in range(quota):
            found = None
            for _ in range(4):
                bucket = order[cell][0]
                order[cell].rotate(-1)
                queue = queues.get(bucket, deque())
                while queue:
                    key = queue.popleft()
                    games = review.source_games(origins[key])
                    if not games or not games.isdisjoint(used):
                        collisions.add(key)
                        continue
                    found = key
                    used.update(games)
                    break
                if found is not None:
                    break
            if found is None:
                break
            selected.append(found)
            picked += 1
        deficits["/".join(cell)] = quota - picked
    if not selected:
        raise ValueError("No unambiguous game-distinct sample is available")
    return selected, checks, excluded, {"phase_side_requested_each": quota, "phase_side_deficits": deficits,
        "history_eligible_n": len(checks), "history_excluded_by_reason": dict(Counter(excluded.values())),
        "source_collision_skipped_n": len(collisions),
        "selected_by_phase_side_multiplicity_margin": dict(sorted(Counter("/".join(selection_bucket(records[k], outcomes[k])) for k in selected).items()))}


def evidence_metrics(record, outcome, scores, probabilities):
    legal = {move.uci() for move in chess.Board(record["fen"]).legal_moves}
    if set(probabilities) != legal or any(isinstance(p, bool) or not isinstance(p, (int, float)) or
            not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values()) or abs(math.fsum(probabilities.values()) - 1) > 2e-6:
        raise ValueError("Policy must be a finite, complete legal distribution")
    result = {}
    for depth in DEPTHS:
        if set(scores[depth]) != legal:
            raise ValueError("Incomplete saved root scores")
        if any(isinstance(cp, bool) or not isinstance(cp, (int, float)) or not math.isfinite(cp)
               for cp in scores[depth].values()):
            raise ValueError("Saved roots must have finite numeric scores")
        best = max(scores[depth].values())
        accepted = sorted(move for move, cp in scores[depth].items() if best - cp <= 20)
        if best != outcome["best_cp"][depth] or accepted != outcome["accepted"][depth]:
            raise ValueError("Root evidence differs from the frozen outcome")
        metrics = probability_summary({move: {"cp": cp, "mate": None} for move, cp in scores[depth].items()}, probabilities, 20, 300)
        result[depth] = {"p_acceptable": metrics["p_good_lower"], "p_acceptable_upper": metrics["p_good_upper"],
                         "capped_regret_cp": metrics["capped_regret_lower_cp"],
                         "probability_gate": metrics["p_good_upper"] <= .10,
                         "regret_gate": metrics["capped_regret_lower_cp"] >= 50,
                         "candidate_gate": -200 <= best <= 200 and metrics["p_good_upper"] <= .10 and metrics["capped_regret_lower_cp"] >= 50}
    return result


def paired_metrics(item, prediction):
    record, outcome, scores = item["record"], item["outcome"], item["scores"]
    if prediction.get("id") != record["id"] or prediction.get("fen") != record["fen"] or prediction.get("history_available") is not True:
        raise ValueError("Paired policy identity or context differs")
    maps = prediction.get("maia3", {})
    if set(maps) != set(CONDITIONS) or any(set(maps[c]) != {str(r) for r in RATINGS} for c in CONDITIONS):
        raise ValueError("Require both conditions at both fixed ratings")
    result = {"id": record["id"], "metrics": {}, "changes": {}, "condition_pass": {}}
    for condition in CONDITIONS:
        result["metrics"][condition] = {str(r): evidence_metrics(record, outcome, scores, maps[condition][str(r)]) for r in RATINGS}
        result["condition_pass"][condition] = outcome["engine_verified"] is True and all(
            result["metrics"][condition][str(r)][d]["candidate_gate"] for r in RATINGS for d in DEPTHS)
    for rating in map(str, RATINGS):
        f, h = (maps[c][rating] for c in CONDITIONS)
        top = lambda p: sorted(move for move in p if p[move] == max(p.values()))
        result["changes"][rating] = {"top_choice_changed": top(f) != top(h),
            "total_variation": .5 * math.fsum(abs(f[m] - h[m]) for m in f),
            "by_depth": {d: {"delta_p_acceptable": result["metrics"]["history"][rating][d]["p_acceptable"] - result["metrics"]["fen_only"][rating][d]["p_acceptable"],
                "delta_capped_regret_cp": result["metrics"]["history"][rating][d]["capped_regret_cp"] - result["metrics"]["fen_only"][rating][d]["capped_regret_cp"]} for d in DEPTHS}}
    return result


def prepare(output, count=MAX_COUNT):
    output = review.require_private_output(output)
    records, outcomes, census, paths, fingerprints, _ = review.verify_bundle()
    eligible, pool_counts = review.editorial_pool(records, outcomes, census)
    subset = {key: records[key] for key in eligible}
    chosen, histories, excluded, quota = choose(subset, outcomes, census["canonical_origins_by_id"], count)
    scores = root_scores_for(chosen, records, paths)
    rows = []
    for key in chosen:
        # Reconcile all complete numeric roots before any new policy can be inspected.
        for depth in DEPTHS:
            if len(scores[key][depth]) != outcomes[key]["legal_count"]:
                raise ValueError("Incomplete chosen root evidence")
        rows.append({"record": records[key], "outcome": outcomes[key], "scores": scores[key],
                     "origins": census["canonical_origins_by_id"][key], "history_flags": histories[key],
                     "sampling_bucket": list(selection_bucket(records[key], outcomes[key]))})
    files = {"inputs.json": {"items": rows}, "history_exclusions.json": excluded}
    manifest = {"schema_version": 1, "created_utc": utc_now(), "scope": SCOPE, "seed": SEED,
        "selection_frozen_before_inference": True, "requested_n": count, "selected_n": len(chosen),
        "pool_counts": pool_counts, "quota": quota, "model_pin": MODEL,
        "files_sha256": {name: fingerprint(value) for name, value in files.items()},
        "fingerprints": fingerprints, "adapter_sha256": digest(ROOT / "scripts/mining_v2_policy.py"),
        "audit_script_sha256": digest(__file__), "selected_ids_sha256": fingerprint(chosen),
        "dependency_sha256": {name: digest(ROOT / "scripts" / name) for name in ("mining_v2_engine.py", "editorial_diagnostics.py", "candidate_review.py")},
        "python_chess_version": chess.__version__,
        "settings": {"device": "cpu", "threads": 2, "batch_size": 32, "position_chunk_size": CHUNK,
                     "ratings_self_and_opponent": list(RATINGS), "conditions": list(CONDITIONS),
                     "temperature": 1, "normalization": "raw logits softmax over every legal move; no post-hoc renormalization",
                     "history": "last eight true chronological source states including current; left-pad earliest if shorter",
                     "fen_only": "current state repeated eight times", "clocks": "disabled/zero in both conditions",
                     "engine_context": "saved FEN-only roots at depth20 and depth24; unchanged", "precision": "float32; no AMP",
                     "battery_policy": "pause before loading model and before each chunk unless AC power is confirmed"},
        "selection_method": "16 per phase/side at n=96, scarce endgame cells first; round-robin single/multiple acceptable moves and old probability>=.075 or old regret<=75 versus interior. SHA256 seeded ranks; every-origin source game/alias disjoint. Empty subcells redistribute within primary cell; primary deficits stay explicit, no post-inference replacement.",
        "readiness": {"human_reviewed": False, "human_calibrated": False, "trainer_ready": False}}
    output.mkdir(parents=True, exist_ok=False)
    for name, value in {**files, "selection_manifest.json": manifest}.items():
        (output / name).write_bytes(encoded(value))
    return manifest


def read_inputs(output):
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / "data/mining_v3").resolve()):
        raise ValueError("Audit directory must be private")
    manifest = json.loads((output / "selection_manifest.json").read_text())
    if manifest["audit_script_sha256"] != digest(__file__) or manifest["adapter_sha256"] != digest(ROOT / "scripts/mining_v2_policy.py"):
        raise ValueError("Audit or adapter changed after selection; preserve this run and freeze a new directory")
    if manifest["python_chess_version"] != chess.__version__:
        raise ValueError("Python-chess changed after selection")
    for name, expected in manifest["dependency_sha256"].items():
        if digest(ROOT / "scripts" / name) != expected:
            raise ValueError("Audit dependency changed after selection")
    for name, expected in manifest["files_sha256"].items():
        if digest(output / name) != expected:
            raise ValueError("Frozen audit input changed")
    items = json.loads((output / "inputs.json").read_text())["items"]
    if len(items) != manifest["selected_n"] or fingerprint([i["record"]["id"] for i in items]) != manifest["selected_ids_sha256"]:
        raise ValueError("Frozen selected identities differ")
    for item in items:
        if history_check(item["record"], item["origins"]) != item["history_flags"]:
            raise ValueError("Frozen source history verification differs")
    return manifest, items


def power_state():
    try:
        value = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if "Now drawing from 'AC Power'" in value:
        return "ac"
    if "Now drawing from 'Battery Power'" in value:
        return "battery"
    return "unknown"


def runtime_fingerprint(adapter):
    return {"python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
            "packages": {name: importlib.metadata.version(name) for name in ("torch", "numpy", "python-chess", "huggingface-hub")},
            "model": adapter.manifest, "adapter_sha256": digest(ROOT / "scripts/mining_v2_policy.py"),
            "audit_script_sha256": digest(__file__)}


def control_inputs(items):
    controls = []
    for item in items[:4]:
        fen = item["record"]["fen"]
        controls.append({"id": "control/" + item["record"]["id"], "fen": fen, "initial_fen": fen,
                         "history_uci": [], "history_fens": [fen], "history_available": True})
    return controls


def check_controls(rows, expected):
    if not expected or len(rows) != len(expected) or len({r["id"] for r in rows}) != len(expected):
        raise ValueError("Controls must contain every selected control exactly once")
    differences = []
    for row, record in zip(rows, expected, strict=True):
        if (row.get("id") != record["id"] or row.get("fen") != record["fen"] or
                row.get("history_available") is not True or set(row.get("maia3", {})) != set(CONDITIONS)):
            raise ValueError("Control identity or paired context differs")
        legal = {m.uci() for m in chess.Board(record["fen"]).legal_moves}
        for condition in CONDITIONS:
            if set(row["maia3"][condition]) != {str(r) for r in RATINGS}:
                raise ValueError("Control ratings differ")
            for probs in row["maia3"][condition].values():
                if (set(probs) != legal or any(isinstance(p, bool) or not isinstance(p, (int, float)) or
                        not math.isfinite(p) or not 0 <= p <= 1 for p in probs.values()) or
                        abs(math.fsum(probs.values()) - 1) > 2e-6):
                    raise ValueError("Control is not a full legal normalized probability distribution")
        for rating in map(str, RATINGS):
            f, h = (row["maia3"][c][rating] for c in CONDITIONS)
            differences.append(max(abs(f[m] - h[m]) for m in f))
    maximum = max(differences)
    if not math.isfinite(maximum) or maximum > 1e-6:
        raise ValueError("Identical-input paired control failed")
    return {"positions_n": len(rows), "rating_pairs_n": len(differences), "max_abs_probability_difference": maximum,
            "passed": True, "meaning": "Both code paths receive identical current-position tokens; this is not a real-history comparison."}


def verified_controls(output, items):
    path = output / "controls.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    expected = control_inputs(items)
    if (not (output / "runtime.json").exists() or value["runtime_sha256"] != digest(output / "runtime.json") or
            value.get("control_inputs_sha256") != fingerprint(expected) or
            check_controls(value["predictions"], expected) != value["summary"]):
        raise ValueError("Controls differ from frozen targets, verified runtime or predictions")
    return value


def read_batches(output, manifest, items):
    found, runtime_hashes = {}, set()
    for path in sorted((output / "batches").glob("*.json")):
        batch = json.loads(path.read_text())
        if batch["selection_manifest_sha256"] != digest(output / "selection_manifest.json"):
            raise ValueError("Batch belongs to different selection")
        runtime_hashes.add(batch["runtime_sha256"])
        for row in batch["predictions"]:
            if row["id"] in found:
                raise ValueError("Duplicate paired prediction")
            found[row["id"]] = row
    wanted = {i["record"]["id"] for i in items}
    if not set(found) <= wanted or len(runtime_hashes) > 1:
        raise ValueError("Extra prediction or mixed inference runtimes")
    if runtime_hashes and (not (output / "runtime.json").exists() or runtime_hashes != {digest(output / "runtime.json")}):
        raise ValueError("Runtime provenance differs")
    controls = verified_controls(output, items)
    if found and controls is None:
        raise ValueError("Paired results require successful frozen-input controls before numeric reporting")
    for item in items:
        key = item["record"]["id"]
        if key in found:
            paired_metrics(item, found[key])
    return found


def run(output):
    """Serialize resumes so paired batches cannot race or overwrite one another."""
    import fcntl
    output = Path(output)
    if not output.is_dir():
        raise ValueError("Prepare the immutable private audit first")
    with (output / ".run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another process is already running this audit") from error
        return run_locked(output)


def run_locked(output):
    output = Path(output)
    manifest, items = read_inputs(output)
    existing = read_batches(output, manifest, items)
    if len(existing) == len(items) and (output / "controls.json").exists():
        return report(output)
    if power_state() != "ac":
        atomic_json(output / "status.json", {"status": "paused_power", "updated_utc": utc_now(), "completed_n": len(existing), "selected_n": len(items), "power": power_state()})
        return report(output)
    from mining_v2_policy import Maia3Policy
    import torch
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    adapter = Maia3Policy(device="cpu", threads=2, batch_size=32, local_files_only=True, model_size="5m")
    runtime = runtime_fingerprint(adapter)
    if (output / "runtime.json").exists():
        if json.loads((output / "runtime.json").read_text()) != runtime:
            raise ValueError("Runtime changed; do not mix paired results across runs")
    else:
        atomic_json(output / "runtime.json", runtime)
    if not (output / "controls.json").exists():
        if power_state() != "ac":
            return report(output)
        controls = control_inputs(items)
        values = adapter.predict(controls, history_ratings=RATINGS, fen_ratings=RATINGS)
        atomic_json(output / "controls.json", {"runtime_sha256": digest(output / "runtime.json"),
            "control_inputs_sha256": fingerprint(controls), "summary": check_controls(values, controls), "predictions": values})
    (output / "batches").mkdir(exist_ok=True)
    pending = [i for i in items if i["record"]["id"] not in existing]
    started = time.monotonic()
    for offset in range(0, len(pending), CHUNK):
        if power_state() != "ac":
            atomic_json(output / "status.json", {"status": "paused_power", "updated_utc": utc_now(), "completed_n": len(existing), "selected_n": len(items), "power": power_state()})
            return report(output)
        batch_items = pending[offset:offset + CHUNK]
        tick = time.monotonic()
        predictions = adapter.predict([i["record"] for i in batch_items], history_ratings=RATINGS, fen_ratings=RATINGS)
        if len(predictions) != len(batch_items):
            raise ValueError("Inference omitted a selected position")
        for item, prediction in zip(batch_items, predictions):
            paired_metrics(item, prediction)
        path = output / "batches" / f"batch-{len(existing):03d}.json"
        if path.exists():
            raise FileExistsError("Refuse overwrite of paired inference batch")
        atomic_json(path, {"selection_manifest_sha256": digest(output / "selection_manifest.json"),
            "runtime_sha256": digest(output / "runtime.json"), "created_utc": utc_now(),
            "seconds": time.monotonic() - tick, "predictions": predictions})
        existing.update({row["id"]: row for row in predictions})
        print(json.dumps({"paired_positions": len(existing), "selected": len(items), "inference_seconds_this_resume": round(time.monotonic() - started, 2)}), flush=True)
    atomic_json(output / "status.json", {"status": "complete", "updated_utc": utc_now(), "completed_n": len(existing), "selected_n": len(items)})
    return report(output)


def group_report(items, predictions):
    paired = [paired_metrics(item, predictions[item["record"]["id"]]) for item in items if item["record"]["id"] in predictions]
    result = {"n": len(paired), "candidate_transitions": dict(Counter(
        f"{'pass' if row['condition_pass']['fen_only'] else 'fail'}_to_{'pass' if row['condition_pass']['history'] else 'fail'}" for row in paired)), "by_rating": {}}
    for rating in map(str, RATINGS):
        result["by_rating"][rating] = {"top_choice_changed_n": sum(row["changes"][rating]["top_choice_changed"] for row in paired),
            "total_variation": summary([row["changes"][rating]["total_variation"] for row in paired]) if paired else None,
            "by_depth": {}}
        for depth in DEPTHS:
            current = {key: summary([row["changes"][rating]["by_depth"][depth][key] for row in paired]) if paired else None
                       for key in ("delta_p_acceptable", "delta_capped_regret_cp")}
            for gate in ("probability_gate", "regret_gate", "candidate_gate"):
                current[gate + "_transitions"] = dict(Counter(
                    f"{'pass' if row['metrics']['fen_only'][rating][depth][gate] else 'fail'}_to_{'pass' if row['metrics']['history'][rating][depth][gate] else 'fail'}" for row in paired))
            result["by_rating"][rating]["by_depth"][depth] = current
    return result


def report(output):
    output = Path(output)
    manifest, items = read_inputs(output)
    predictions = read_batches(output, manifest, items)
    controls = verified_controls(output, items)
    result = {"schema_version": 1, "scope": SCOPE, "selection_frozen_before_inference": True,
        "status": "complete" if len(predictions) == len(items) and controls else "prepared_or_paused",
        "counts": {"editorial_pool_n": manifest["pool_counts"]["editorial_eligible"], "selected_n": len(items),
                   "paired_completed_n": len(predictions), "pending_n": len(items) - len(predictions), "failed_n": 0,
                   "history_excluded_n": sum(manifest["quota"]["history_excluded_by_reason"].values()), "trainer_ready_n": 0},
        "selection": manifest["quota"], "settings": manifest["settings"], "model_pin": MODEL,
        "fingerprints": {"selection_manifest_sha256": digest(output / "selection_manifest.json"),
            "inputs_sha256": digest(output / "inputs.json"), "census_aggregate_sha256": manifest["fingerprints"]["aggregate_sha256"],
            "audit_script_sha256": digest(__file__), "adapter_sha256": manifest["adapter_sha256"], "dependency_sha256": manifest["dependency_sha256"],
            "runtime_sha256": digest(output / "runtime.json") if (output / "runtime.json").exists() else None,
            "paired_batches": {p.name: digest(p) for p in sorted((output / "batches").glob("*.json"))}},
        "controls": controls["summary"] if controls else None,
        "all_selected": group_report(items, predictions),
        "by_phase": {phase: group_report([i for i in items if i["record"]["phase"] == phase], predictions) for phase in ("opening", "middlegame", "endgame")},
        "by_side": {side: group_report([i for i in items if i["record"]["side_to_move"] == side], predictions) for side in ("white", "black")},
        "repetition_sensitive_selected_n": sum(i["history_flags"]["repetition_sensitive"] for i in items),
        "without_repetition_sensitivity": group_report([i for i in items if not i["history_flags"]["repetition_sensitive"]], predictions),
        "limitations": ["Purposive phase-balanced sample selected using old model/engine outcomes; do not treat frequencies as representative.",
            "Both new conditions share one pinned model/runtime. Old census probabilities are not the paired baseline.",
            "Real history changes model input only. Saved engine evaluations have no actual game-history stack.",
            "Ratings are hypothetical equal self/opponent settings; clocks disabled; source time-control mismatch remains.",
            "No human choices or learning outcomes measured; no assessment states used; no trainer promotion."]}
    # Public aggregate must contain no board/move/source identities, individual observations or paths.
    forbidden = {"fen", "history_uci", "history_fens", "game_id", "id", "record", "origins", "predictions", "scores", "accepted"}
    def check(value):
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise ValueError("Private fields in public report")
            for child in value.values(): check(child)
        elif isinstance(value, list):
            for child in value: check(child)
    check(result)
    atomic_json(ROOT / "results/context_audit_20260916.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "report"))
    parser.add_argument("--directory", type=Path, default=ROOT / "data/mining_v3/context-audit-20260916-final")
    parser.add_argument("--count", type=int, default=MAX_COUNT)
    args = parser.parse_args()
    result = prepare(args.directory, args.count) if args.action == "prepare" else run(args.directory) if args.action == "run" else report(args.directory)
    if args.action == "prepare":
        result = report(args.directory)
    print(json.dumps({"status": result["status"], "counts": result["counts"], "selection": result["selection"]}, indent=2))


if __name__ == "__main__":
    main()
