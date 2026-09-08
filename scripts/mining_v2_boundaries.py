"""Retrieve natural rook/knight capture contrasts from the historical corpus.

Default: scan only, with no engine work. Optional --screen compares up to three
specified/ranked positions at depth 16, with a two-second cap per search. This
retrieval does not establish a teaching family or modify an active study bank.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import chess
import chess.engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.mining_v2_sampling import canonical_fen, file_sha256, public_exclusions

PROTECTED = ROOT / "data/mining_v2/private_boundary_candidates.json"
ANCHOR_GAME = "b68nh58o"


def capture_geometry(board: chess.Board, target: int = chess.C3,
                     entry: int = chess.D6) -> list[dict]:
    """Describe legal same-target rook/knight captures and the ensuing entry."""
    victim = board.piece_at(target)
    mover = board.turn
    if victim is None or victim.color == mover:
        return []
    moves = [move for move in board.legal_moves if move.to_square == target]
    rooks = [move for move in moves if board.piece_type_at(move.from_square) == chess.ROOK]
    knights = [move for move in moves if board.piece_type_at(move.from_square) == chess.KNIGHT]
    if not rooks or not knights:
        return []
    out = []
    for knight in knights:
        after = board.copy()
        after.push(knight)
        entries = [move for move in after.legal_moves
                   if move.to_square == entry and after.piece_type_at(move.from_square) == chess.KNIGHT]
        out.append({"rook_moves": [move.uci() for move in rooks],
                    "knight_move": knight.uci(), "knight_from": chess.square_name(knight.from_square),
                    "mover": "white" if mover else "black", "target_piece": victim.symbol(),
                    "entry_square": chess.square_name(entry),
                    "opponent_knight_entries": [{"uci": move.uci(), "san": after.san(move),
                                                 "is_check": after.gives_check(move)} for move in entries],
                    "remaining_opponent_knights": [chess.square_name(s) for s in after.pieces(chess.KNIGHT, not mover)],
                    "entry_defenders_after_knight_capture": [
                        {"square": chess.square_name(s), "piece": after.piece_at(s).symbol()}
                        for s in after.attackers(mover, entry)],
                    "mover_king": chess.square_name(after.king(mover)),
                    "knight_was_entry_defender": knight.from_square in board.attackers(mover, entry)})
    return out


def exclusion_sets(master_rows, public_fens=(), public_games=(), pilot_rows=(),
                   additional_games=(ANCHOR_GAME,)):
    fens = {canonical_fen(fen) for fen in public_fens}
    games = {str(game) for game in public_games} | set(additional_games)
    heldout = [row for row in pilot_rows if row["split"] in ("validation", "test")]
    fens.update(canonical_fen(row["fen"]) for row in heldout)
    games.update(row["game_id"] for row in heldout)
    recovered = {row["game_id"] for row in master_rows
                 if row.get("game_id") and canonical_fen(row["fen"]) in fens}
    extra = recovered - games
    games.update(recovered)
    return fens, games, {"excluded_canonical_states": len(fens), "excluded_recorded_games": len(games),
                        "heldout_pilot_positions": len(heldout),
                        "additional_recorded_game_ids_recovered": len(extra)}


def scan_rows(master_rows, excluded_fens, excluded_games, *, target=chess.C3,
              entry=chess.D6, preferred_knight=chess.E4):
    records, counts = [], Counter()
    for row in master_rows:
        counts["master_rows_scanned"] += 1
        if row["game_id"] in excluded_games:
            counts["excluded_recorded_game_rows"] += 1
            continue
        if canonical_fen(row["fen"]) in excluded_fens:
            counts["excluded_canonical_rows"] += 1
            continue
        found = capture_geometry(chess.Board(row["fen"]), target, entry)
        if found:
            counts["both_captures_rows"] += 1
        for geometry in found:
            records.append({"row": row, **geometry,
                            "saved_best_is_knight_capture": row.get("engine_best") == geometry["knight_move"]})
    preferred = chess.square_name(preferred_knight)
    records.sort(key=lambda x: (not x["saved_best_is_knight_capture"], x["knight_from"] != preferred,
                                bool(x["opponent_knight_entries"]), abs(float(x["row"]["best_cp"])),
                                x["row"]["game_id"], x["row"]["fen"]))
    counts["candidate_capture_choices"] = len(records)
    counts["unique_canonical_hits"] = len({canonical_fen(r["row"]["fen"]) for r in records})
    return records, dict(counts)


def bounded_search(engine, board, root=None, *, depth=16, seconds=2):
    engine.configure({"Clear Hash": None})
    merged, start = {}, time.monotonic()
    roots = [chess.Move.from_uci(root)] if root else None
    with engine.analysis(board, chess.engine.Limit(depth=depth, time=seconds), root_moves=roots) as analysis:
        for update in analysis:
            # A later exact score must clear an earlier aspiration-window bound.
            if "score" in update:
                merged.pop("lowerbound", None)
                merged.pop("upperbound", None)
            merged.update(update)
        analysis.wait()
    if "score" not in merged:
        raise ValueError("The engine supplied no score within the screening budget")
    score = merged["score"].pov(board.turn)
    replay, pv = board.copy(), []
    for move in merged.get("pv", [])[:18]:
        if move not in replay.legal_moves:
            raise ValueError("The engine supplied an illegal principal variation")
        pv.append({"uci": move.uci(), "san": replay.san(move)})
        replay.push(move)
    return {"root": root, "cp": score.score(), "mate": score.mate(),
            "depth": merged.get("depth"), "nodes": merged.get("nodes"),
            "exact_uci_score": not merged.get("lowerbound", False) and not merged.get("upperbound", False),
            "pv": pv, "seconds": time.monotonic() - start,
            "score_perspective": "side to move in this search's starting board"}


def screen_records(records, engine_path, *, limit=3, depth=16, seconds=2):
    checked, games, fens = [], set(), set()
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        engine.configure({"Threads": 1, "Hash": 64})
        for record in records:
            row = record["row"]
            canon = canonical_fen(row["fen"])
            if row["game_id"] in games or canon in fens:
                continue
            board = chess.Board(row["fen"])
            comparisons = {"knight_capture": bounded_search(engine, board, record["knight_move"], depth=depth, seconds=seconds),
                           "rook_capture": bounded_search(engine, board, record["rook_moves"][0], depth=depth, seconds=seconds),
                           "unrestricted": bounded_search(engine, board, depth=depth, seconds=seconds)}
            # The first legal knight entry is a branch probe, not an assertion
            # that an opponent would choose it or that it is their best reply.
            if record["opponent_knight_entries"]:
                branch = board.copy()
                branch.push_uci(record["knight_move"])
                entry = record["opponent_knight_entries"][0]["uci"]
                branch.push_uci(entry)
                comparisons["reply_to_entry"] = {"branch_uci": [record["knight_move"], entry],
                                                  **bounded_search(engine, branch, depth=depth, seconds=seconds)}
            checked.append({**record, "comparison": comparisons,
                            "status": "screen evidence only; chess mechanism and exhaustive acceptance still need review"})
            games.add(row["game_id"])
            fens.add(canon)
            if len(checked) >= limit:
                break
    return checked


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--master", type=Path, default=ROOT / "results/master_all.csv")
    ap.add_argument("--pilot", type=Path, default=ROOT / "data/mining_v2/positions.jsonl")
    ap.add_argument("--output", type=Path, default=ROOT / "data/mining_v2/boundary_retrieval.json")
    ap.add_argument("--target", default="c3")
    ap.add_argument("--entry", default="d6")
    ap.add_argument("--preferred-knight", default="e4")
    ap.add_argument("--exclude-game", action="append", default=[ANCHOR_GAME])
    ap.add_argument("--game-id", action="append", help="Screen only hits in these recorded games; scanning remains complete")
    ap.add_argument("--screen", action="store_true", help="Opt into bounded engine comparisons")
    ap.add_argument("--max-screen", type=int, choices=(1, 2, 3), default=3)
    ap.add_argument("--engine", type=Path, default=ROOT / "models/stockfish18/stockfish/stockfish-macos-m1-apple-silicon")
    ap.add_argument("--seconds", type=float, default=2)
    ap.add_argument("--depth", type=int, default=16)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.output.resolve() == PROTECTED.resolve():
        ap.error("The active private_boundary_candidates.json cannot be overwritten by this retrieval tool")
    if args.output.exists() and not args.force:
        ap.error("Output exists; choose another path or explicitly use --force")
    if not 0 < args.seconds <= 10 or not 1 <= args.depth <= 20:
        ap.error("Retrieval screening is bounded to 0–10 seconds and depth 1–20")
    try:
        target, entry, preferred = map(chess.parse_square, (args.target, args.entry, args.preferred_knight))
    except ValueError as error:
        ap.error(str(error))
    with args.master.open(newline="") as f:
        master = list(csv.DictReader(f))
    public_fens, public_games, public_info = public_exclusions()
    pilot = [json.loads(line) for line in args.pilot.read_text().splitlines()] if args.pilot.exists() else []
    fens, games, exclusions = exclusion_sets(master, public_fens, public_games, pilot, args.exclude_game)
    records, counts = scan_rows(master, fens, games, target=target, entry=entry, preferred_knight=preferred)
    output = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "natural-position retrieval, not approved teaching boundaries",
              "family_link": "keep-key-square-covered", "positive_anchor_game": ANCHOR_GAME,
              "query": {"target_square": args.target, "knight_entry_square": args.entry,
                        "preferred_knight_origin": args.preferred_knight,
                        "required": "Legal rook and knight captures of the same opponent piece; geometry checked after the knight capture"},
              "source_sha256": {str(args.master): file_sha256(args.master),
                                **({str(args.pilot): file_sha256(args.pilot)} if args.pilot.exists() else {})},
              "script_sha256": file_sha256(Path(__file__)), "public_exclusions": public_info,
              "exclusion_counts": exclusions, "counts": counts, "records": records,
              "limitations": ["Historical recorded IDs may not resolve every actual source game.",
                              "No held-out pilot positions inform this retrieval; recoverable source-game overlaps are excluded.",
                              "Missing, covered or nonchecking knight entry is a geometry fact, not proof that the knight capture is sound.",
                              "Default mode performs no new engine analysis. Historical best moves are screening clues, not verified answers."]}
    if args.screen:
        pool = [r for r in records if not args.game_id or r["row"]["game_id"] in args.game_id]
        output["screen"] = screen_records(pool, args.engine, limit=args.max_screen, depth=args.depth, seconds=args.seconds)
        output["engine"] = {"binary_sha256": file_sha256(args.engine), "threads": 1, "hash_mb": 64,
                            "clear_hash_each_search": True, "depth_target": args.depth,
                            "time_cap_per_search_seconds": args.seconds,
                            "note": "Separate restricted comparisons are finite-search evidence, not exhaustive move-set verification"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "counts": counts,
                      "new_engine_checks": len(output.get("screen", []))}, indent=2))


if __name__ == "__main__":
    main()
