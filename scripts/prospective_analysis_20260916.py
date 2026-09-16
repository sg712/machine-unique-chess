"""Bounded, AC-only analysis of separately frozen prospective chess queues.

Calibration: actual player-rating pairs, paired real-history/FEN Maia3 policies,
complete numeric depth20/24 engine roots, stable 20cp acceptable sets. Targeted:
additional fixed1700/2000 policies and explicitly approximate depth14 screening.
All source rows stay in coverage denominators; no transform fitting or promotion.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

import chess
import chess.engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from mining_v2_sampling import canonical_fen
from mining_v2_engine import probability_summary, DEFAULT_ENGINE
from context_audit_20260916 import atomic_json, digest, encoded, fingerprint, power_state, MODEL

ROLES = ("calibration_development", "calibration_evaluation", "targeted_endgame")
SEED = "prospective-analysis-20260916-v1"
PROVENANCE = ROOT / "results/prospective_model_provenance_20260916.json"
ENGINE_SHA256 = "bc0cac905ecdf2147fe22055c733bcd999b1e3f7c399fbaf7fb9055786563590"
PLAN = {"schema_version": 1, "seed": SEED, "role_counts_requested": dict(zip(ROLES, (16, 16, 32))),
    "targeted_per_side_and_rating_group": 8,
    "tranche_selection": "seeded SHA256 rank within calibration role, and targeted side/rating cells; frozen before outcomes",
    "calibration_depths": [20, 24], "targeted_depths": [14], "tolerance_cp": 20,
    "regret_cap_cp": 300, "engine_board_context": "FEN-only for both model conditions",
    "engine_threads": 1, "engine_hash_mb": 64, "clear_hash_each_search": True,
    "task_scheduling": "fewest prior attempts first; all never-attempted roots precede retries; seeded tranche role-interleaving breaks ties",
    "per_root_seconds": 30, "per_invocation_wall_seconds": 600,
    "power_policy": "confirmed AC only; check before model batches and during each engine search",
    "engine_stop_grace_seconds": 2, "model_threads": 2, "model_batch_size": 24,
    "model_position_chunk": 4, "model_pin": MODEL,
    "ratings": "calibration: actual mover and actual opponent; targeted: actual plus equal1700 and equal2000",
    "probability": "temperature1 softmax on complete legal support; float32; no AMP; no posthoc transform",
    "clock_inputs": "disabled/zero identically in both history conditions",
    "controls": "same-FEN paired inputs for actual and fixed ratings; equal1700 separate-rating adapter matches pinned original adapter to1e-6",
    "history": "last8actual states including current; earliest-left padding; FEN condition repeats target",
    "calibration_event": "recorded source move is in complete stable20cp acceptable set",
    "calibration_gate": "both depths reached, exact, all legal roots, numeric/no mates, same nonempty20cp set; no surprise or evaluation-window gate",
    "reliability_bin_edges": [0, .05, .10, .25, .50, .75, .90, 1.0],
    "log_loss_probability_clip": 1e-12,
    "targeted_interpretation": "depth14 approximation only; not depth-stable candidates or teaching approvals",
    "calibration_transform_fitting": False,
    "unit": "one selected actual source-game move; not a human puzzle response"}


def now():
    return datetime.now(timezone.utc).isoformat()


def string_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def validate_row(row):
    if row.get("analysis_role") not in ROLES or row.get("history_available") is not True:
        raise ValueError("Unknown role or missing genuine history")
    board = chess.Board(row["initial_fen"])
    states = [board.fen()]
    if not board.is_valid():
        raise ValueError("Invalid source initial position")
    for uci in row["history_uci"]:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError("Illegal source history")
        board.push(move)
        states.append(board.fen())
    if (board.fen() != row["fen"] or states[-8:] != row["history_fens"] or
        row["ply"] != len(row["history_uci"]) + 1 or not board.is_valid() or board.is_game_over() or
        chess.Move.from_uci(row["played_move"]) not in board.legal_moves or
        row["side_to_move"] != ("white" if board.turn else "black")):
        raise ValueError("Source target/history/played-move identity differs")
    for key in ("white_elo", "black_elo"):
        if type(row[key]) is not int or not 1400 <= row[key] <= 2399:
            raise ValueError("Actual rating is outside frozen cohort support")
    if row["mover_elo"] != row["white_elo" if board.turn else "black_elo"]:
        raise ValueError("Actual mover rating differs from side-to-move")
    if row.get("contains_bot") is not False or row.get("known_project_public_exposure") is not False:
        raise ValueError("Unexpected bot or known project exposure")
    target = string_hash(canonical_fen(row["fen"]))
    source_states = row.get("source_canonical_state_hashes")
    if (not isinstance(source_states, list) or target not in source_states or
            any(not isinstance(v, str) or len(v) != 64 for v in source_states)):
        raise ValueError("Missing full-source-state identity audit")
    return {"target_previously_seen": board.is_repetition(2),
            "threefold_claim_available": board.can_claim_threefold_repetition(),
            "near_fifty_move_boundary": board.halfmove_clock >= 90}


def validate_cohort_rows(rows):
    games, sequences, targets, all_states, ids = set(), set(), set(), set(), set()
    for row in rows:
        validate_row(row)
        target = string_hash(canonical_fen(row["fen"]))
        states = set(row["source_canonical_state_hashes"])
        if (row["id"] in ids or row["game_id"] in games or row["source_move_sequence_sha256"] in sequences
                or target in all_states or not states.isdisjoint(targets)):
            raise ValueError("Cohort repeats a game, sequence, or target anywhere in another source game")
        ids.add(row["id"]); games.add(row["game_id"]); sequences.add(row["source_move_sequence_sha256"])
        targets.add(target); all_states.update(states)


def load_cohort(directory):
    directory = Path(directory).resolve()
    if not directory.is_relative_to(ROOT / "data/mining_v3"):
        raise ValueError("Cohort must be private")
    summary = json.loads((directory / "summary.json").read_text())
    protocol = json.loads((directory / "protocol.json").read_text())
    if summary["protocol_sha256"] != digest(directory / "protocol.json") or summary["protocol"] != protocol:
        raise ValueError("Cohort protocol hash differs")
    if protocol.get("engine_or_model_selection") is not False or summary.get("inference_run") is not False:
        raise ValueError("Cohort was not frozen independently of model outcomes")
    source = json.loads((directory / "source.json").read_text())
    if summary["source"] != source or source["compressed_prefix_sha256"] != digest(directory / "august_prefix.pgn.zst"):
        raise ValueError("Saved source prefix differs")
    rows = []
    hashes = {"summary_sha256": digest(directory / "summary.json"), "protocol_sha256": digest(directory / "protocol.json"),
              "source_sha256": digest(directory / "source.json"), "compressed_prefix_sha256": source["compressed_prefix_sha256"]}
    for role in ROLES:
        path = directory / (role + ".jsonl")
        if digest(path) != summary["outputs"][role]["sha256"]:
            raise ValueError("Cohort queue hash differs")
        values = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if len(values) != summary["outputs"][role]["count"] or any(r["analysis_role"] != role for r in values):
            raise ValueError("Cohort queue role/count differs")
        rows.extend(values)
        hashes[role + "_sha256"] = digest(path)
    validate_cohort_rows(rows)
    return rows, hashes


def tranche(rows):
    selected, deficits = [], {}
    for role in ROLES:
        cells = [(None, None)] if role != "targeted_endgame" else [(s, r) for s in ("white", "black") for r in ("1400_1799", "1800_2399")]
        for side, rating in cells:
            candidates = [r for r in rows if r["analysis_role"] == role and
                          (side is None or (r["side_to_move"], r["rating_group"]) == (side, rating))]
            candidates.sort(key=lambda r: string_hash(SEED + ":" + r["id"]))
            n = 16 if side is None else 8
            selected.extend(candidates[:n])
            deficits[role if side is None else f"{role}/{side}/{rating}"] = max(0, n - len(candidates))
    return selected, deficits


def safe_output(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT / "data/mining_v3") or not path.name.startswith("prospective-analysis-"):
        raise ValueError("Analysis output must be a new ignored prospective-analysis-* directory")
    if subprocess.run(["git", "check-ignore", "-q", str(path / "plan.json")], cwd=ROOT).returncode:
        raise ValueError("Analysis outputs must be ignored")
    if subprocess.check_output(["git", "ls-files", "--", str(path)], cwd=ROOT, text=True).strip():
        raise ValueError("Analysis directory contains tracked files")
    return path


def prepare(cohort, output):
    output = safe_output(output)
    if output.exists():
        raise FileExistsError("Preserve previous analysis; choose a new output directory")
    rows, hashes = load_cohort(cohort)
    selected, deficits = tranche(rows)
    if not selected:
        raise ValueError("No source rows available")
    if digest(DEFAULT_ENGINE) != ENGINE_SHA256:
        raise ValueError("Local engine differs from pinned Stockfish18 binary")
    provenance = json.loads(PROVENANCE.read_text())
    if (provenance.get("weights_sha256") != MODEL["weights_sha256"] or provenance.get("revision") != MODEL["weights_revision"]
            or provenance.get("documentary_temporal_separation_supported") is not True):
        raise ValueError("Pinned model publication/source-date provenance is not verified")
    data = {"rows": selected, "history_flags_by_id": {r["id"]: validate_row(r) for r in selected}}
    plan = {"plan": PLAN, "created_utc": now(), "cohort_directory_name": Path(cohort).name,
            "cohort_fingerprints": hashes, "cohort_n": len(rows), "selected_n": len(selected),
            "selected_by_role": dict(Counter(r["analysis_role"] for r in selected)), "quota_deficits": deficits,
            "inputs_sha256": fingerprint(data), "engine_sha256": ENGINE_SHA256,
            "script_sha256": digest(__file__), "policy_adapter_sha256": digest(ROOT / "scripts/mining_v2_policy.py"),
            "metrics_sha256": digest(ROOT / "scripts/mining_v2_engine.py"),
            "context_helpers_sha256": digest(ROOT / "scripts/context_audit_20260916.py"),
            "selection_frozen_before_inference": True, "model_provenance_sha256": digest(PROVENANCE),
            "training_overlap_audit": "source games postdate published pinned weights; no exhaustive training corpus or pattern/player independence claim"}
    output.mkdir(parents=True)
    (output / "inputs.json").write_bytes(encoded(data))
    (output / "plan.json").write_bytes(encoded(plan))
    atomic_json(output / "status.json", {"status": "prepared", "updated_utc": now()})
    return report(output)


def load_plan(output):
    output = safe_output(output)
    plan = json.loads((output / "plan.json").read_text())
    if plan["plan"] != PLAN or plan["script_sha256"] != digest(__file__):
        raise ValueError("Frozen analysis settings or script changed")
    for key, path in (("policy_adapter_sha256", ROOT / "scripts/mining_v2_policy.py"),
                      ("metrics_sha256", ROOT / "scripts/mining_v2_engine.py"),
                      ("context_helpers_sha256", ROOT / "scripts/context_audit_20260916.py")):
        if plan[key] != digest(path):
            raise ValueError("Pinned analysis dependency changed")
    if plan["model_provenance_sha256"] != digest(PROVENANCE):
        raise ValueError("Model documentary provenance changed")
    if plan["inputs_sha256"] != digest(output / "inputs.json") or digest(DEFAULT_ENGINE) != plan["engine_sha256"]:
        raise ValueError("Frozen input or engine changed")
    rows = json.loads((output / "inputs.json").read_text())["rows"]
    validate_cohort_rows(rows)
    return plan, rows


def rating_pairs(row):
    mover = row["white_elo"] if row["side_to_move"] == "white" else row["black_elo"]
    opponent = row["black_elo"] if row["side_to_move"] == "white" else row["white_elo"]
    pairs = {"actual": (mover, opponent)}
    if row["analysis_role"] == "targeted_endgame":
        pairs.update(fixed1700=(1700, 1700), fixed2000=(2000, 2000))
    return pairs


def predict_actual(adapter, rows):
    """Pinned Maia3 forward pass with separate self/opponent rating tensors."""
    import torch
    from mining_v2_policy import history_boards, validate_policy
    output, tasks = [], []
    for row in rows:
        boards = history_boards(row)
        board = boards[-1]
        mask = adapter.get_legal_moves_mask(board, adapter.move_index)
        result = {"id": row["id"], "fen": row["fen"], "rating_pairs": {k: list(v) for k, v in rating_pairs(row).items()}, "policies": {}}
        output.append(result)
        for condition, context in (("history", boards), ("fen_only", [board])):
            result["policies"][condition] = {}
            tokens = adapter.tokens(context)
            for label, (mover, opponent) in rating_pairs(row).items():
                tasks.append((result, condition, label, mover, opponent, tokens, mask, board))
    with torch.inference_mode():
        for start in range(0, len(tasks), PLAN["model_batch_size"]):
            batch = tasks[start:start + PLAN["model_batch_size"]]
            tokens = torch.stack([t[5] for t in batch]).to(adapter.device)
            movers = torch.tensor([t[3] for t in batch], dtype=torch.long, device=adapter.device)
            opponents = torch.tensor([t[4] for t in batch], dtype=torch.long, device=adapter.device)
            masks = torch.stack([t[6] for t in batch]).to(adapter.device)
            logits, _, _ = adapter.model(tokens, movers, opponents)
            probs = logits.float().masked_fill(~masks, float("-inf")).softmax(-1).cpu()
            for task, values in zip(batch, probs):
                result, condition, label, _, _, _, mask, board = task
                mapping = {adapter.mirror_move(adapter.all_moves[i]) if board.turn == chess.BLACK else adapter.all_moves[i]: float(values[i])
                           for i in mask.nonzero().flatten().tolist()}
                validate_policy(board, mapping)
                result["policies"][condition][label] = mapping
    return output


def validate_policy_result(row, value):
    if value.get("id") != row["id"] or value.get("fen") != row["fen"] or value.get("rating_pairs") != {k: list(v) for k, v in rating_pairs(row).items()}:
        raise ValueError("Policy identity or actual rating pairing differs")
    legal = {move.uci() for move in chess.Board(row["fen"]).legal_moves}
    if set(value["policies"]) != {"history", "fen_only"}:
        raise ValueError("Missing paired model condition")
    for maps in value["policies"].values():
        if set(maps) != set(rating_pairs(row)):
            raise ValueError("Missing requested rating condition")
        for probs in maps.values():
            if (set(probs) != legal or any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1 for p in probs.values())
                    or abs(math.fsum(probs.values()) - 1) > 2e-6):
                raise ValueError("Policy is not complete finite legal probability distribution")


def model_control_rows(rows):
    selected = [r for r in rows if r["analysis_role"] != "targeted_endgame"][:2] + [r for r in rows if r["analysis_role"] == "targeted_endgame"][:2]
    controls = []
    for row in selected:
        controls.append({**row, "id": "control/" + row["id"], "initial_fen": row["fen"],
                         "history_uci": [], "history_fens": [row["fen"]], "history_available": True})
    return controls


def verify_control_predictions(expected, values):
    if not expected or len(expected) != len(values):
        raise ValueError("Missing model controls")
    differences = []
    for row, value in zip(expected, values, strict=True):
        validate_policy_result(row, value)
        for label in rating_pairs(row):
            f, h = (value["policies"][c][label] for c in ("fen_only", "history"))
            differences.append(max(abs(f[m] - h[m]) for m in f))
    maximum = max(differences)
    if maximum > 1e-6:
        raise ValueError("Same-input paired model control differs")
    return maximum


def equal_control_row(rows):
    source = model_control_rows(rows)[0]
    return {**source, "id": "equal-rating-control", "analysis_role": "calibration_development",
            "white_elo": 1700, "black_elo": 1700, "mover_elo": 1700}


def verified_model_controls(output, rows):
    path = output / "model_controls.json"
    if not path.exists():
        return None
    controls = json.loads(path.read_text())
    expected, equal = model_control_rows(rows), equal_control_row(rows)
    if (controls["runtime_sha256"] != digest(output / "model_runtime.json") or
            controls["expected_controls_sha256"] != fingerprint(expected) or
            controls["equal_control_sha256"] != fingerprint(equal)):
        raise ValueError("Model controls have different frozen inputs or runtime")
    maximum = verify_control_predictions(expected, controls["predictions"])
    actual, reference = controls["equal_rating_actual"], controls["equal_rating_reference"]
    validate_policy_result(equal, actual)
    validate_policy_result(equal, reference)
    diff = max(abs(actual["policies"][c]["actual"][m] - reference["policies"][c]["actual"][m])
               for c in ("history", "fen_only") for m in actual["policies"][c]["actual"])
    if diff > 1e-6:
        raise ValueError("Separate-rating adapter does not match original at equal ratings")
    return {"same_input_controls_n": len(expected), "max_paired_probability_difference": maximum,
            "max_equal_rating_adapter_difference": diff, "passed": True}


def task_key(row, depth, move):
    return string_hash(f"{row['id']}|{depth}|{move}")


def depths_for(row):
    return PLAN["targeted_depths"] if row["analysis_role"] == "targeted_endgame" else PLAN["calibration_depths"]


def evidence_status(row, result, depth, move):
    if (result.get("record_id") != row["id"] or result.get("fen") != row["fen"] or
            result.get("target_depth") != depth or result.get("requested_root") != move or result.get("board_context") != "fen_only"):
        raise ValueError("Saved engine result has different identity or root request")
    if result.get("error"):
        return "engine_error"
    if result.get("depth", 0) < depth or result.get("reached_target") is not True:
        return "capped_or_interrupted"
    if result.get("lowerbound") or result.get("upperbound") or result.get("score_is_exact") is not True:
        return "bound_score"
    cp, mate = result.get("cp"), result.get("mate")
    if not ((isinstance(cp, (int, float)) and not isinstance(cp, bool) and math.isfinite(cp) and mate is None)
            or (type(mate) is int and cp is None)):
        raise ValueError("Exact search must have one finite numeric or typed mate score")
    board = chess.Board(row["fen"])
    pv = result.get("pv", [])
    if not pv or pv[0]["uci"] != move:
        raise ValueError("Root evidence lacks its requested legal continuation")
    for step in pv:
        action = chess.Move.from_uci(step["uci"])
        if action not in board.legal_moves or board.san(action) != step["san"]:
            raise ValueError("Root evidence contains an illegal or mislabelled line")
        board.push(action)
    return "mate_score" if mate is not None else "complete_numeric"


def bounded_search(engine, row, depth, move, deadline):
    """Hard stop watchdog complements UCI limits and polls power during each search."""
    board = chess.Board(row["fen"])
    started = time.monotonic()
    seconds = max(.01, min(PLAN["per_root_seconds"], deadline - started))
    result = {"record_id": row["id"], "fen": row["fen"], "target_depth": depth,
              "requested_root": move, "board_context": "fen_only", "per_root_cap_seconds": seconds}
    done, stop_reason = threading.Event(), []
    analysis, latest = None, {}
    try:
        engine.configure({"Clear Hash": None})
        analysis = engine.analysis(board, chess.engine.Limit(depth=depth, time=seconds), root_moves=[chess.Move.from_uci(move)])
        def watch():
            stopped = None
            while not done.wait(.5):
                if stopped is None:
                    reason = "power_pause" if power_state() != "ac" else "wall_or_root_cap" if time.monotonic() >= started + seconds else None
                    if reason:
                        stop_reason.append(reason)
                        analysis.stop()
                        stopped = time.monotonic()
                elif time.monotonic() - stopped >= PLAN["engine_stop_grace_seconds"]:
                    engine.close()
                    break
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        for update in analysis:
            # A deeper currmove/info line cannot promote an older scored PV.
            if "score" in update:
                latest = {"score": update["score"], "depth": update.get("depth", 0),
                          "pv": update.get("pv", []), "nodes": update.get("nodes"),
                          "lowerbound": bool(update.get("lowerbound")), "upperbound": bool(update.get("upperbound"))}
        if "score" not in latest:
            raise ValueError("No scored continuation before interruption")
        score = latest["score"].pov(board.turn)
        replay, pv = board.copy(), []
        for action in latest.get("pv", [])[:20]:
            if action not in replay.legal_moves:
                raise ValueError("Illegal engine continuation")
            pv.append({"uci": action.uci(), "san": replay.san(action)})
            replay.push(action)
        result.update(cp=score.score(), mate=score.mate(), depth=latest.get("depth", 0),
            reached_target=latest.get("depth", 0) >= depth,
            lowerbound=bool(latest.get("lowerbound")), upperbound=bool(latest.get("upperbound")),
            score_is_exact=not latest.get("lowerbound") and not latest.get("upperbound"),
            nodes=latest.get("nodes"), pv=pv)
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)[:300]
    finally:
        done.set()
        if analysis is not None:
            try: analysis.stop()
            except (RuntimeError, chess.engine.EngineError): pass
        result["stop_reason"] = stop_reason[0] if stop_reason else None
        result["wall_seconds"] = time.monotonic() - started
    result["status"] = evidence_status(row, result, depth, move)
    return result


def load_saved(output, plan, rows):
    wanted = {row["id"]: row for row in rows}
    policies, roots = {}, {key: {} for key in wanted}
    plan_hash = digest(output / "plan.json")
    inventory = {}
    for path in sorted((output / "policies").glob("*.json")):
        payload = path.read_bytes()
        value = json.loads(payload)
        inventory[str(path.relative_to(output))] = hashlib.sha256(payload).hexdigest()
        if value["plan_sha256"] != plan_hash or value["runtime_sha256"] != digest(output / "model_runtime.json"):
            raise ValueError("Policy plan/runtime fingerprint differs")
        row = value["prediction"]
        if row["id"] not in wanted or row["id"] in policies:
            raise ValueError("Unknown or duplicate policy")
        validate_policy_result(wanted[row["id"]], row)
        policies[row["id"]] = row
    controls = verified_model_controls(output, rows)
    if policies and controls is None:
        raise ValueError("Predictions cannot be reported without verified model controls")
    for path in sorted((output / "roots").glob("*.json")):
        payload = path.read_bytes()
        value = json.loads(payload)
        inventory[str(path.relative_to(output))] = hashlib.sha256(payload).hexdigest()
        if value["plan_sha256"] != plan_hash or value["runtime_sha256"] != digest(output / "engine_runtime.json"):
            raise ValueError("Root plan/runtime fingerprint differs")
        result = value["result"]
        row = wanted.get(result["record_id"])
        if row is None or result["target_depth"] not in depths_for(row):
            raise ValueError("Unknown root position or depth")
        depth, move = result["target_depth"], result["requested_root"]
        if chess.Move.from_uci(move) not in chess.Board(row["fen"]).legal_moves:
            raise ValueError("Saved root request is illegal")
        if evidence_status(row, result, depth, move) != result["status"]:
            raise ValueError("Saved root status differs")
        roots[row["id"]].setdefault(str(depth), {})[move] = result
    if controls is not None:
        inventory["model_controls.json"] = digest(output / "model_controls.json")
    return policies, roots, inventory


def scheduled_tasks(rows, roots):
    role_rows = {role: [r for r in rows if r["analysis_role"] == role] for role in ROLES}
    ordered, tasks = [], []
    for index in range(16):
        for role, pos in (("targeted_endgame", 2 * index), ("calibration_development", index),
                          ("targeted_endgame", 2 * index + 1), ("calibration_evaluation", index)):
            if pos < len(role_rows[role]): ordered.append(role_rows[role][pos])
    for row in ordered:
        for depth in depths_for(row):
            for move in sorted(m.uci() for m in chess.Board(row["fen"]).legal_moves):
                prior = roots[row["id"]].get(str(depth), {}).get(move)
                if prior and evidence_status(row, prior, depth, move) in ("complete_numeric", "mate_score"):
                    continue
                tasks.append((prior.get("attempt_number", 1) if prior else 0, len(tasks), row, depth, move))
    return [(row, depth, move, attempts) for attempts, _, row, depth, move in sorted(tasks, key=lambda t: (t[0], t[1]))]


def lock_is_held(output):
    with (output / ".run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def position_result(row, roots, policy):
    legal = {m.uci() for m in chess.Board(row["fen"]).legal_moves}
    statuses, scores = [], {}
    for depth in depths_for(row):
        bucket = roots.get(str(depth), {})
        scores[str(depth)] = {}
        for move in sorted(legal):
            result = bucket.get(move)
            status = "pending" if result is None else evidence_status(row, result, depth, move)
            statuses.append(status)
            if status in ("complete_numeric", "mate_score"):
                scores[str(depth)][move] = result
    counts = dict(Counter(statuses))
    result = {"id": row["id"], "role": row["analysis_role"], "root_status_counts": counts,
              "model_policy_available": policy is not None, "verified_for_calibration": False,
              "state": "incomplete_roots", "metrics": {}}
    if len(statuses) != counts.get("complete_numeric", 0) + counts.get("mate_score", 0):
        return result
    if counts.get("mate_score", 0):
        result["state"] = "mate_in_legal_root"
        return result
    accepted = {d: sorted(m for m, v in bucket.items() if max(r["cp"] for r in bucket.values()) - v["cp"] <= PLAN["tolerance_cp"]) for d, bucket in scores.items()}
    if row["analysis_role"] != "targeted_endgame" and accepted["20"] != accepted["24"]:
        result["state"] = "unstable_acceptable_set"
        return result
    result["state"] = "approximate_targeted_screen" if row["analysis_role"] == "targeted_endgame" else "complete_stable_numeric"
    if policy is None:
        return result
    validate_policy_result(row, policy)
    depth = "14" if row["analysis_role"] == "targeted_endgame" else "24"
    result["acceptable_n"] = len(accepted[depth])
    result["observed_move_acceptable"] = row["played_move"] in accepted[depth]
    for condition, maps in policy["policies"].items():
        result["metrics"][condition] = {}
        for label, probs in maps.items():
            metrics = probability_summary(scores[depth], probs, PLAN["tolerance_cp"], PLAN["regret_cap_cp"])
            result["metrics"][condition][label] = {"p_acceptable": metrics["p_good_lower"], "capped_regret_cp": metrics["capped_regret_lower_cp"]}
    result["verified_for_calibration"] = row["analysis_role"] != "targeted_endgame"
    return result


def calibration_metrics(values):
    if not values:
        return {"n": 0, "brier": None, "log_loss": None, "bins": []}
    epsilon = PLAN["log_loss_probability_clip"]
    for p, y in values:
        if not math.isfinite(p) or not -2e-6 <= p <= 1 + 2e-6 or type(y) is not bool:
            raise ValueError("Invalid calibration event/probability")
    # Clip only float rounding to the probability domain; log loss uses its declared epsilon.
    points = [(min(1., max(0., p)), y) for p, y in values]
    brier = math.fsum((p - y) ** 2 for p, y in points) / len(points)
    loss = -math.fsum(math.log(max(epsilon, min(1 - epsilon, p if y else 1 - p))) for p, y in points) / len(points)
    edges, bins = PLAN["reliability_bin_edges"], []
    for i, (low, high) in enumerate(zip(edges, edges[1:])):
        entries = [(p, y) for p, y in points if low <= p < high or (i == len(edges) - 2 and p == high)]
        bins.append({"lower_inclusive": low, "upper": high, "last_upper_inclusive": i == len(edges) - 2,
                     "n": len(entries), "mean_predicted": math.fsum(p for p, _ in entries) / len(entries) if entries else None,
                     "observed_fraction": sum(y for _, y in entries) / len(entries) if entries else None,
                     "sparse": len(entries) < 30})
    return {"n": len(points), "brier": brier, "log_loss": loss, "bins": bins}


def report(output):
    output = safe_output(output)
    plan, rows = load_plan(output)
    policies, roots, inventory = load_saved(output, plan, rows)
    values = [position_result(row, roots[row["id"]], policies.get(row["id"])) for row in rows]
    by_role = {}
    for role in ROLES:
        group = [v for v in values if v["role"] == role]
        verified = [v for v in group if v["verified_for_calibration"]]
        role_rows = [r for r in rows if r["analysis_role"] == role]
        players = Counter(p for r in role_rows for p in r.get("player_hashes", {}).values() if p)
        by_role[role] = {"selected_n": len(group), "policy_completed_n": sum(v["model_policy_available"] for v in group),
            "state_counts": dict(Counter(v["state"] for v in group)), "verified_calibration_n": len(verified),
            "root_status_counts": dict(sum((Counter(v["root_status_counts"]) for v in group), Counter())),
            "known_players_n": len(players), "players_repeated_across_games_n": sum(n > 1 for n in players.values())}
        if role != "targeted_endgame":
            by_role[role]["calibration"] = {c: calibration_metrics([(v["metrics"][c]["actual"]["p_acceptable"], v["observed_move_acceptable"]) for v in verified]) for c in ("history", "fen_only")}
        else:
            approximate = [v for v in group if v["state"] == "approximate_targeted_screen" and v["model_policy_available"]]
            by_role[role]["approximate_screen_with_policy_n"] = len(approximate)
            by_role[role]["history_fixed1700_to2000_probability_increases_n"] = sum(v["metrics"]["history"]["fixed2000"]["p_acceptable"] > v["metrics"]["history"]["fixed1700"]["p_acceptable"] for v in approximate)
    status = json.loads((output / "status.json").read_text()) if (output / "status.json").exists() else {"status": "prepared"}
    displayed_status = status["status"]
    if displayed_status.startswith("running_") and not lock_is_held(output):
        displayed_status = "interrupted_without_final_checkpoint"
    atomic_json(output / "evidence_inventory.json", inventory)
    aggregate = {"schema_version": 1, "status": displayed_status, "plan": PLAN,
        "selected_n": len(rows), "cohort_n": plan["cohort_n"], "quota_deficits": plan["quota_deficits"], "by_role": by_role,
        "fingerprints": {"plan_sha256": digest(output / "plan.json"), "inputs_sha256": digest(output / "inputs.json"),
            "cohort": plan["cohort_fingerprints"], "script_sha256": digest(__file__),
            "model_runtime_sha256": digest(output / "model_runtime.json") if (output / "model_runtime.json").exists() else None,
            "engine_runtime_sha256": digest(output / "engine_runtime.json") if (output / "engine_runtime.json").exists() else None,
            "evidence_inventory_sha256": fingerprint(inventory), "evidence_files_n": len(inventory),
            "model_controls_sha256": inventory.get("model_controls.json")},
        "controls": verified_model_controls(output, rows),
        "documentary_model_provenance_sha256": plan["model_provenance_sha256"],
        "calibration_transform_fitted": False, "trainer_ready_n": 0,
        "limitations": ["Fresh bounded chronological convenience prefix; not a random whole-month sample.",
            "Calibration metrics, if present, concern recorded online-game moves on the complete stable numeric subset; full selected coverage remains shown.",
            "Incomplete, capped, bound, mate-valued and unstable items are not relabelled as complete; they remain in denominators.",
            "August2026 games postdate published pinned May2026 weights and declared Jan2023–July2025 training; this does not establish new players, novel patterns or exhaustive training-corpus exclusion.",
            "Actual rating pairs are preserved; clocks disabled and source time-control/model mismatch remains.",
            "Repeated-player and near-duplicate dependence limits uncertainty; small-bin frequencies are descriptive.",
            "Targeted depth14 screening is approximate and cannot establish the frozen20/24 candidate criterion or a teaching family.",
            "No human puzzle calibration, learning result, probability transform or trainer release."]}
    atomic_json(output / "analysis_rows.json", {"items": values})
    atomic_json(output / "aggregate.json", aggregate)
    atomic_json(ROOT / "results/prospective_analysis_20260916.json", aggregate)
    return aggregate


def run(output):
    output = safe_output(output)
    with (output / ".run.lock").open("a+") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise RuntimeError("Analysis already running") from error
        try:
            return run_locked(output)
        except BaseException as error:
            atomic_json(output / "status.json", {"status": "interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                        "updated_utc": now(), "error_type": type(error).__name__})
            try: report(output)
            except Exception: pass
            raise


def run_locked(output):
    plan, rows = load_plan(output)
    policies, roots, inventory = load_saved(output, plan, rows)
    started = time.monotonic()
    deadline = started + PLAN["per_invocation_wall_seconds"]
    def checkpoint(status):
        atomic_json(output / "status.json", {"status": status, "updated_utc": now(), "wall_seconds_this_invocation": time.monotonic() - started})
        return report(output)
    if power_state() != "ac":
        return checkpoint("paused_power")
    from mining_v2_policy import Maia3Policy
    import torch
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    pending = [r for r in rows if r["id"] not in policies]
    if pending:
        checkpoint("running_model")
        adapter = Maia3Policy(device="cpu", threads=2, batch_size=PLAN["model_batch_size"], local_files_only=True, model_size="5m")
        runtime = {"model": {**adapter.manifest, "rating_conditioning": "separate actual mover/opponent or declared fixed equal-rating pair"}, "python": sys.version, "platform": platform.platform(),
                   "numpy": importlib.metadata.version("numpy"), "separate_self_opponent_ratings": True,
                   "script_sha256": digest(__file__)}
        runtime_file = output / "model_runtime.json"
        if runtime_file.exists() and json.loads(runtime_file.read_text()) != runtime:
            raise ValueError("Refuse mixing model runtimes")
        if not runtime_file.exists(): atomic_json(runtime_file, runtime)
        if verified_model_controls(output, rows) is None:
            if power_state() != "ac": return checkpoint("paused_power")
            controls, equal = model_control_rows(rows), equal_control_row(rows)
            values = predict_actual(adapter, controls)
            verify_control_predictions(controls, values)
            custom = predict_actual(adapter, [equal])[0]
            original = adapter.predict([equal], history_ratings=(1700,), fen_ratings=(1700,))[0]
            reference = {"id": equal["id"], "fen": equal["fen"], "rating_pairs": {"actual": [1700, 1700]},
                         "policies": {c: {"actual": original["maia3"][c]["1700"]} for c in ("history", "fen_only")}}
            atomic_json(output / "model_controls.json", {"runtime_sha256": digest(runtime_file),
                "expected_controls_sha256": fingerprint(controls), "equal_control_sha256": fingerprint(equal),
                "predictions": values, "equal_rating_actual": custom, "equal_rating_reference": reference})
            verified_model_controls(output, rows)
        (output / "policies").mkdir(exist_ok=True)
        for offset in range(0, len(pending), PLAN["model_position_chunk"]):
            if power_state() != "ac": return checkpoint("paused_power")
            if time.monotonic() >= deadline: return checkpoint("paused_wall_cap")
            batch = pending[offset:offset + PLAN["model_position_chunk"]]
            values = predict_actual(adapter, batch)
            for row, value in zip(batch, values, strict=True):
                validate_policy_result(row, value)
                path = output / "policies" / (string_hash(row["id"]) + ".json")
                if path.exists(): raise FileExistsError("Policy already exists")
                atomic_json(path, {"plan_sha256": digest(output / "plan.json"), "runtime_sha256": digest(runtime_file), "prediction": value})
                policies[row["id"]] = value
        del adapter
    if power_state() != "ac": return checkpoint("paused_power")
    checkpoint("running_engine")
    engine = chess.engine.SimpleEngine.popen_uci(str(DEFAULT_ENGINE), timeout=5)
    try:
        engine.configure({"Threads": 1, "Hash": 64})
        runtime = {"engine_id": engine.id, "binary_sha256": digest(DEFAULT_ENGINE), "python_chess": chess.__version__,
                   "threads": 1, "hash_mb": 64, "clear_hash_each_search": True, "script_sha256": digest(__file__)}
        runtime_file = output / "engine_runtime.json"
        if runtime_file.exists() and json.loads(runtime_file.read_text()) != runtime:
            raise ValueError("Refuse mixing engine runtimes")
        if not runtime_file.exists(): atomic_json(runtime_file, runtime)
        (output / "roots").mkdir(exist_ok=True)
        tasks = scheduled_tasks(rows, roots)
        for index, (row, depth, move, attempts) in enumerate(tasks):
            if power_state() != "ac": return checkpoint("paused_power")
            if time.monotonic() >= deadline - .5: return checkpoint("paused_wall_cap")
            result = bounded_search(engine, row, depth, move, deadline)
            result["attempt_number"] = attempts + 1
            key = task_key(row, depth, move)
            path = output / "roots" / f"{key}-{attempts + 1:04d}.json"
            if path.exists(): raise FileExistsError("Root attempt must not overwrite prior evidence")
            atomic_json(path, {"plan_sha256": digest(output / "plan.json"),
                "runtime_sha256": digest(runtime_file), "created_utc": now(), "result": result})
            roots[row["id"]].setdefault(str(depth), {})[move] = result
            if result.get("stop_reason") == "power_pause": return checkpoint("paused_power")
            if result["status"] == "engine_error":
                return checkpoint("paused_root_cap" if result.get("stop_reason") == "wall_or_root_cap" else "paused_engine_error")
            if (index + 1) % 20 == 0:
                checkpoint("running_engine")
                print(json.dumps({"root_tasks_this_invocation": index + 1, "seconds": round(time.monotonic() - started, 1)}), flush=True)
        all_finished = all(all(v in ("complete_numeric", "mate_score") for v in
                           [r["status"] for d in roots[row["id"]].values() for r in d.values()])
                           and sum(len(d) for d in roots[row["id"]].values()) == len(depths_for(row)) * chess.Board(row["fen"]).legal_moves.count()
                           for row in rows)
        return checkpoint("searches_complete" if all_finished else "pass_complete_with_incomplete_roots")
    finally:
        try: engine.quit()
        except (chess.engine.EngineError, TimeoutError): engine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "report"))
    parser.add_argument("--cohort", type=Path, default=ROOT / "data/mining_v3/prospective-20260916-v2")
    parser.add_argument("--directory", type=Path, default=ROOT / "data/mining_v3/prospective-analysis-20260916")
    args = parser.parse_args()
    import signal
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    value = prepare(args.cohort, args.directory) if args.action == "prepare" else run(args.directory) if args.action == "run" else report(args.directory)
    print(json.dumps({"status": value["status"], "selected_n": value["selected_n"],
                      "by_role": {role: {k: v for k, v in data.items() if k != "calibration"} for role, data in value["by_role"].items()}}, indent=2))


if __name__ == "__main__":
    main()
