"""Freeze a rating-stratified historical audit with nearest matched controls.

Historical values select the sample; fresh engine/model checks must be reported
separately. These records have a FEN, not recovered game history or clocks.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import sys

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.mining_v2_sampling import (SEED, canonical_fen, digest, file_sha256,
                                       phase_of, public_exclusions)

STRATA = ("at_most_2000", "2000_to_2200", "2200_to_2400", "above_2400")


def stratum(elo: float) -> str:
    return STRATA[0 if elo <= 2000 else 1 if elo <= 2200 else 2 if elo <= 2400 else 3]


def eligible(row: dict) -> bool:
    try:
        values = [float(row[k]) for k in ("best_cp", "engine_margin", "mover_elo", "ply")]
        return (all(math.isfinite(v) for v in values) and abs(values[0]) <= 200
                and values[1] >= 70 and values[2] > 0
                and bool(row.get("game_id")) and row["game_id"].lower() != "nan")
    except (ValueError, TypeError, KeyError):
        return False


def selected(row: dict) -> bool:
    return str(row.get("machine_unique", "")).lower() in ("true", "1")


def distance(a: dict, b: dict) -> float:
    return math.sqrt(sum(((float(a[k]) - float(b[k])) / scale) ** 2
                         for k, scale in (("best_cp", 100), ("engine_margin", 100),
                                          ("mover_elo", 200), ("ply", 12))))


def sample_matched(rows: list[dict], per_stratum: int = 16, seed: int = SEED):
    """Choose seeded cases first; match without replacement inside rating strata."""
    pool = [r for r in rows if eligible(r)]
    cases, used_games, used_fens = [], set(), set()
    candidate_counts = {}
    for band in STRATA:
        choices = [r for r in pool if selected(r) and stratum(float(r["mover_elo"])) == band]
        candidate_counts[band] = {"positions": len(choices),
                                  "recorded_games": len({r["game_id"] for r in choices})}
        choices.sort(key=lambda r: digest(f"{seed}:historical-case:{canonical_fen(r['fen'])}:{r['game_id']}"))
        chosen = 0
        for row in choices:
            canon = canonical_fen(row["fen"])
            if row["game_id"] in used_games or canon in used_fens:
                continue
            cases.append(row)
            used_games.add(row["game_id"])
            used_fens.add(canon)
            chosen += 1
            if chosen == per_stratum:
                break
        if chosen < per_stratum:
            raise ValueError(f"Only {chosen}/{per_stratum} distinct-game candidates in {band}")
    controls = [r for r in pool if not selected(r)]
    pairs = []
    for case in cases:
        band = stratum(float(case["mover_elo"]))
        available = [r for r in controls if stratum(float(r["mover_elo"])) == band
                     and r["game_id"] not in used_games and canonical_fen(r["fen"]) not in used_fens]
        exact = [r for r in available if r.get("batch") == case.get("batch")]
        choices = exact or available
        if not choices:
            raise ValueError(f"No unused control in rating stratum {band}")
        control = min(choices, key=lambda r: (distance(case, r),
                                             digest(f"{seed}:control:{r['fen']}:{r['game_id']}")))
        used_games.add(control["game_id"])
        used_fens.add(canonical_fen(control["fen"]))
        pairs.append({"case": case, "control": control, "distance": distance(case, control),
                      "same_batch": bool(exact), "stratum": band})
    return pairs, {"candidate_pool_by_stratum": candidate_counts,
                   "control_pool_positions": len(controls),
                   "same_batch_pairs": sum(p["same_batch"] for p in pairs),
                   "batch_fallback_pairs": sum(not p["same_batch"] for p in pairs)}


def output_record(row: dict, role: str, master_hash: str) -> dict:
    fen, gid = row["fen"], row["game_id"]
    board = chess.Board(fen)
    def number(key):
        try:
            value = float(row[key])
            return value if math.isfinite(value) else None
        except (KeyError, TypeError, ValueError):
            return None
    return {"id": f"historical_stratified_{role}-{digest(canonical_fen(fen))[:16]}",
            "fen": fen, "game_id": gid, "split": "historical_audit", "cohort": f"historical_{role}",
            "side_to_move": "white" if board.turn else "black",
            # Empty UCI history means no context is supplied to the model. The
            # initial_fen is the supplied analysis start, not the game's start.
            "initial_fen": fen, "history_uci": [], "history_fens": [fen],
            "history_available": False, "initial_fen_is_game_start": False,
            "played_move": row["played_move"], "white_elo": number("white_elo"),
            "black_elo": number("black_elo"), "mover_elo": number("mover_elo"),
            "time_control": None, "clock_seconds_before": None, "opponent_clock_seconds": None,
            "phase": phase_of(board, int(float(row["ply"]))), "ply": int(float(row["ply"])),
            "rating_stratum": stratum(float(row["mover_elo"])),
            "source": {"cohort": f"historical_{role}", "batch": row.get("batch"),
                       "history_available": False, "master_sha256": master_hash},
            "historical": {"best": row["engine_best"], "best_cp": number("best_cp"),
                           "margin_cp": number("engine_margin"), "p_max": number("p_max"),
                           "maia_favourite": row.get("human_top_2000"),
                           "cost_cp": number("human_cost_cp"), "machine_unique": selected(row)}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--master", type=Path, default=ROOT / "results/master_all.csv")
    ap.add_argument("--output", type=Path, default=ROOT / "data/mining_v2/historical_stratified.jsonl")
    ap.add_argument("--new-positions", type=Path, default=ROOT / "data/mining_v2/positions.jsonl")
    ap.add_argument("--per-stratum", type=int, default=16)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.output.exists() and not args.force:
        raise SystemExit("Output already exists; use another path or --force explicitly")
    excluded_fens, excluded_games, exclusions = public_exclusions()
    if args.new_positions.exists():
        new_rows = [json.loads(line) for line in args.new_positions.read_text().splitlines()]
        excluded_fens.update(canonical_fen(r["fen"]) for r in new_rows)
        excluded_games.update(r["game_id"] for r in new_rows)
        exclusions["new_positions_sha256"] = file_sha256(args.new_positions)
    with args.master.open(newline="") as f:
        all_rows = list(csv.DictReader(f))
    # Recover historical batch-local IDs where a matching excluded canonical
    # state links them to public material or the new pilot corpus.
    recovered_ids = {r["game_id"] for r in all_rows if r.get("game_id")
                     and canonical_fen(r["fen"]) in excluded_fens}
    exclusions["additional_recorded_game_ids_recovered"] = len(recovered_ids - excluded_games)
    excluded_games.update(recovered_ids)
    filtered, counts = [], Counter()
    for row in all_rows:
        if not eligible(row):
            counts["fails_cp_margin_or_metadata_screen"] += 1
        elif row["game_id"] in excluded_games:
            counts["excluded_recorded_game"] += 1
        elif canonical_fen(row["fen"]) in excluded_fens:
            counts["excluded_canonical_position"] += 1
        else:
            filtered.append(row)
    pairs, matching = sample_matched(filtered, args.per_stratum, args.seed)
    master_hash = file_sha256(args.master)
    out = []
    for pair in pairs:
        case = output_record(pair["case"], "candidate", master_hash)
        control = output_record(pair["control"], "control", master_hash)
        control["matched_to"] = case["id"]
        case["matched_control"] = control["id"]
        for record in (case, control):
            record["historical"]["matched_distance"] = pair["distance"]
            record["historical"]["matched_same_batch"] = pair["same_batch"]
        out.extend((case, control))
    assert len({r["game_id"] for r in out}) == len(out)
    assert len({canonical_fen(r["fen"]) for r in out}) == len(out)
    for row in out:
        board = chess.Board(row["fen"])
        assert chess.Move.from_uci(row["played_move"]) in board.legal_moves
        assert chess.Move.from_uci(row["historical"]["best"]) in board.legal_moves
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in out))
    distances = sorted(p["distance"] for p in pairs)
    manifest = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "seed": args.seed, "master_sha256": master_hash,
                "script_sha256": file_sha256(Path(__file__)), "output_sha256": file_sha256(args.output),
                "cases": len(pairs), "controls": len(pairs), "recorded_games": len(out),
                "candidate_pool_positions": sum(selected(r) for r in filtered),
                "candidate_pool_recorded_games": len({r["game_id"] for r in filtered if selected(r)}),
                "exclusions": exclusions, "excluded_rows": dict(counts), "matching": matching,
                "counts_by_role_stratum": dict(Counter(f"{r['cohort']}/{r['rating_stratum']}" for r in out)),
                "matching_distance": {"min": min(distances), "median": statistics.median(distances),
                                      "max": max(distances)},
                "screen": "Saved abs(best_cp)<=200 and engine_margin>=70; candidates machine_unique=true, controls machine_unique=false; no new engine evidence implied by this screen.",
                "selection": "Seeded SHA-256 rank; equal candidate count in <=2000, (2000,2200], (2200,2400], >2400; no replacement by recorded game or canonical position.",
                "control_matching": "Greedy nearest Euclidean distance of best_cp/100, engine_margin/100, mover_elo/200, ply/12, within the candidate rating stratum; same batch preferred before fallback. Candidate selection order is fixed by stratum then hash.",
                "limitations": ["All historical source positions are Black to move; this audit does not repair the historical sampling bias.",
                                "No real move histories, clocks or time controls are supplied for these FEN-only records.",
                                "Recorded source-game IDs are distinct; unresolved historical IDs and player/opening dependence remain limitations.",
                                "Matching uses saved finite-search evaluations and selected covariates, not random assignment or full confounder control.",
                                "Public material and the new pilot are excluded by canonical position and recorded/recoverable source-game IDs; unresolved provenance prevents an absolute actual-game separation guarantee."]}
    manifest_path = args.output.with_name(args.output.stem + "_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "cases": len(pairs), "controls": len(pairs),
                      "candidate_pool": manifest["candidate_pool_positions"], "matching": matching,
                      "distance": manifest["matching_distance"]}, indent=2))


if __name__ == "__main__":
    main()
