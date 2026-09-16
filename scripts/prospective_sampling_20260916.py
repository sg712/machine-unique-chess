"""Freeze separate fresh-game calibration and targeted endgame samples.

A bounded August 2026 archive prefix is a convenience sampling frame, not a
representative month. Selection never reads engine evaluations or model output.
"""
from __future__ import annotations

import argparse
from collections import Counter
import codecs
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import urllib.request

import chess
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.mining_v2_sampling import canonical_fen, file_sha256, phase_of, public_exclusions
from scripts.mining_v3_sampling import game_blocks

URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2026-08.pgn.zst"
PROTOCOL = {
    "schema_version": 1, "seed": 20260916, "archive_url": URL,
    "max_compressed_bytes": 8 * 1024 * 1024, "max_complete_games": 8000,
    "ratings_both_players_inclusive": [1400, 2399], "minimum_base_seconds": 180,
    "sampling_plies_inclusive": [14, 140], "month": "2026.08",
    "calibration_target_per_role": 64,
    "endgame_target_per_side_and_rating_group": 32,
    "role_allocation": "game hash modulo 4: 0 development, 1 evaluation, 2/3 targeted",
    "calibration_state_selection": "minimum seeded hash among all eligible actual plies in one game",
    "targeted_state_selection": "hash-assigned side; minimum seeded hash among endgame plies",
    "game_selection": "minimum seeded game hash within role/target cell; one state per game",
    "endgame_definition": "total nonpawn material <=20 (N/B=3,R=5,Q=9), existing phase_of rule",
    "engine_or_model_selection": False,
    "cross_role_exposure": "every selected target absent from every other selected game's complete state history",
    "player_identity": "private unsalted SHA256 of normalized public Lichess usernames; pseudonymous, not anonymous",
    "interpretation": "bounded prefix, filtered convenience sample; not whole-month population calibration",
}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def private_path(path, root=ROOT):
    path = Path(path).resolve()
    base = (root / "data/mining_v3").resolve()
    if not path.is_relative_to(base) or not path.name.startswith("prospective-"):
        raise ValueError("output must be a new prospective-* directory under ignored data/mining_v3")
    check = subprocess.run(["git", "check-ignore", "-q", str(path / "probe.json")], cwd=root)
    if check.returncode:
        raise ValueError("private output is not Git-ignored")
    return path


def prior_exclusions(root=ROOT):
    """Read canonical identities for exclusion only; never inspect held-out outcomes."""
    path = root / "data/mining_v3/positions.audit.sqlite"
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        fens = {row[0] for row in db.execute("SELECT DISTINCT fen FROM rows")}
        games = {row[0] for row in db.execute("SELECT id FROM games")}
    public_fens, public_games, meta = public_exclusions(root)
    fens.update(public_fens)
    games.update(public_games)
    return fens, games, {"prior_state_index_sha256": file_sha256(path),
                         "excluded_states": len(fens), "excluded_game_ids": len(games),
                         "public_exclusion_inputs": meta["input_sha256"]}


def header_eligibility(headers):
    if headers.get("Variant", "Standard") not in ("Standard", "Chess"):
        return "nonstandard"
    if any(headers.get(side + "Title") == "BOT" for side in ("White", "Black")):
        return "bot"
    if (headers.get("Termination") == "Abandoned" or not headers.get("Event", "").startswith("Rated ")
            or headers.get("Result") not in ("1-0", "0-1", "1/2-1/2")):
        return "not_completed_rated_game"
    if not headers.get("UTCDate", headers.get("Date", "")).startswith(PROTOCOL["month"] + "."):
        return "wrong_month"
    try:
        elos = [int(headers[side + "Elo"]) for side in ("White", "Black")]
        if any(not 1400 <= elo <= 2399 for elo in elos):
            return "rating_outside_target"
        base, increment = map(int, headers["TimeControl"].split("+"))
        if base < 180 or increment < 0:
            return "time_control_outside_target"
    except (ValueError, KeyError):
        return "missing_rating_or_time_control"
    if not re.fullmatch(r"https://lichess\.org/[A-Za-z0-9]{8}", headers.get("Site", "")):
        return "unresolved_game_id"
    return None


def candidate_from_game(game, *, excluded_fens=(), excluded_games=()):
    problem = header_eligibility(game.headers)
    if problem:
        return None, problem
    if game.errors:
        return None, "parse_error"
    gid = game.headers["Site"].rsplit("/", 1)[-1]
    if gid in excluded_games:
        return None, "previous_game"
    bucket = int(digest(f"20260916:role:{gid}")[:16], 16) % 4
    role = ("calibration_development", "calibration_evaluation", "targeted_endgame", "targeted_endgame")[bucket]
    desired_side = int(digest(f"20260916:side:{gid}")[:16], 16) % 2 == 0
    board = game.board()
    if type(board) is not chess.Board or not board.is_valid():
        return None, "invalid_board"
    history, states, clocks = [], [board.fen()], {True: None, False: None}
    initial = board.fen()
    best = None
    all_moves, all_state_hashes = [], set()
    for ply, node in enumerate(game.mainline(), 1):
        fen = board.fen()
        canonical = canonical_fen(fen)
        all_state_hashes.add(digest(canonical))
        if canonical in excluded_fens:
            return None, "previous_state_anywhere_in_game"
        if node.move not in board.legal_moves:
            return None, "illegal_move"
        phase = phase_of(board, ply)
        eligible = 14 <= ply <= 140 and not board.is_game_over()
        if role == "targeted_endgame":
            eligible = eligible and phase == "endgame" and board.turn == desired_side
        rank = digest(f"20260916:state:{gid}:{ply}")
        if eligible and (best is None or rank < best[0]):
            mover_elo = int(game.headers["WhiteElo" if board.turn else "BlackElo"])
            best = (rank, {
                "id": f"prospective-{gid}-{ply}", "game_id": gid, "analysis_role": role,
                "fen": fen, "initial_fen": initial, "history_uci": list(history),
                "history_fens": list(states[-8:]), "history_available": True,
                "played_move": node.move.uci(), "side_to_move": "white" if board.turn else "black",
                "white_elo": int(game.headers["WhiteElo"]), "black_elo": int(game.headers["BlackElo"]),
                "mover_elo": mover_elo, "rating_group": "1400_1799" if mover_elo < 1800 else "1800_2399",
                "phase": phase, "ply": ply, "time_control": game.headers["TimeControl"],
                "clock_seconds_before": clocks[board.turn], "opponent_clock_seconds": clocks[not board.turn],
                "contains_bot": False, "known_project_public_exposure": False,
                "external_puzzle_exposure": "not_audited",
                "source": {"archive": URL, "game_url": game.headers["Site"],
                           "date": game.headers.get("UTCDate", game.headers.get("Date")),
                           "event": game.headers["Event"], "white_title": game.headers.get("WhiteTitle"),
                           "black_title": game.headers.get("BlackTitle")},
                "player_hashes": {side.lower(): digest("lichess-player:" + game.headers[side].strip().casefold())
                                  if game.headers.get(side, "?") != "?" else None for side in ("White", "Black")},
            })
        clocks[board.turn] = node.clock()
        history.append(node.move.uci())
        all_moves.append(node.move.uci())
        board.push(node.move)
        states.append(board.fen())
    final_canonical = canonical_fen(board.fen())
    all_state_hashes.add(digest(final_canonical))
    if final_canonical in excluded_fens:
        return None, "previous_state_anywhere_in_game"
    if best is None:
        return None, "no_eligible_position_for_assigned_role"
    row = best[1]
    row["source_move_sequence_sha256"] = digest(initial + " " + " ".join(all_moves))
    row["source_canonical_state_hashes"] = sorted(all_state_hashes)
    return row, None


def select(rows, calibration_n=64, targeted_cell_n=32):
    pools = {}
    for row in rows:
        cell = row["analysis_role"]
        if cell == "targeted_endgame":
            cell += "/" + row["side_to_move"] + "/" + row["rating_group"]
        pools.setdefault(cell, []).append(row)
    chosen, used_games, used_states, used_sequences, counts, rejected = [], set(), set(), set(), Counter(), Counter()
    used_source_states, used_target_hashes = set(), set()
    expected = ["calibration_development", "calibration_evaluation"] + [
        f"targeted_endgame/{side}/{rating}" for side in ("white", "black") for rating in ("1400_1799", "1800_2399")]
    deficits = {}
    for cell in expected:
        target = targeted_cell_n if cell.startswith("targeted") else calibration_n
        for row in sorted(pools.get(cell, []), key=lambda r: digest("20260916:game-rank:" + r["game_id"])):
            if counts[cell] == target:
                break
            state = canonical_fen(row["fen"])
            target_hash = digest(state)
            source_states = set(row["source_canonical_state_hashes"])
            if target_hash not in source_states:
                raise ValueError("target missing from complete source-state identity set")
            if row["game_id"] in used_games or state in used_states or row["source_move_sequence_sha256"] in used_sequences:
                rejected["duplicate_game_state_or_sequence"] += 1
                continue
            if target_hash in used_source_states or not source_states.isdisjoint(used_target_hashes):
                rejected["target_exposed_elsewhere_in_selected_source_game"] += 1
                continue
            chosen.append(row)
            used_games.add(row["game_id"]); used_states.add(state); used_sequences.add(row["source_move_sequence_sha256"])
            used_source_states.update(source_states); used_target_hashes.add(target_hash)
            counts[cell] += 1
        deficits[cell] = target - counts[cell]
    return chosen, {"selected_cells": dict(counts), "shortfall_cells": deficits,
                    "selection_rejections": dict(rejected), "available_cells": {k: len(v) for k, v in sorted(pools.items())}}


def download_prefix(path):
    import certifi
    limit = PROTOCOL["max_compressed_bytes"]
    req = urllib.request.Request(URL, headers={"Range": f"bytes=0-{limit - 1}", "User-Agent": "machine-unique-chess-research/4"})
    with urllib.request.urlopen(req, context=ssl.create_default_context(cafile=certifi.where()), timeout=45) as response:
        if response.status not in (200, 206):
            raise ValueError("unexpected archive response")
        if response.status == 206 and not response.headers.get("Content-Range", "").startswith("bytes 0-"):
            raise ValueError("archive range did not start at byte zero")
        meta = {"status": response.status, "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"), "content_range": response.headers.get("Content-Range")}
        with path.open("xb") as out:
            remaining = limit
            while remaining:
                chunk = response.read(min(1 << 20, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
    return {**meta, "compressed_prefix_bytes": path.stat().st_size,
            "compressed_prefix_sha256": file_sha256(path), "complete_month_downloaded": False}


def read_blocks(path):
    import pyzstd
    def chunks():
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        dctx = pyzstd.EndlessZstdDecompressor()
        with path.open("rb") as stream:
            while raw := stream.read(1 << 18):
                yield decoder.decode(dctx.decompress(raw))
    # game_blocks intentionally drops a possibly incomplete final game.
    yield from game_blocks(chunks())


def run(output, cached_source=None):
    output = private_path(output)
    if output.exists():
        raise ValueError("refusing to overwrite an existing prospective cohort")
    fens, games, exclusions = prior_exclusions()
    output.mkdir(parents=True)
    protocol = {**PROTOCOL, "builder_sha256": file_sha256(Path(__file__)), "exclusions": exclusions}
    # The protocol is written before acquiring or examining the fresh archive.
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    archive = output / "august_prefix.pgn.zst"
    if cached_source is None:
        source = download_prefix(archive)
    else:
        cached_source = private_path(cached_source)
        source = json.loads((cached_source / "source.json").read_text())
        old_protocol = json.loads((cached_source / "protocol.json").read_text())
        old_archive = cached_source / "august_prefix.pgn.zst"
        if (old_protocol["archive_url"] != URL
                or old_archive.stat().st_size != PROTOCOL["max_compressed_bytes"]
                or source["compressed_prefix_bytes"] != old_archive.stat().st_size
                or source["compressed_prefix_sha256"] != file_sha256(old_archive)):
            raise ValueError("cached prefix does not match its declared source")
        shutil.copyfile(old_archive, archive)
    (output / "source.json").write_text(json.dumps(source, indent=2) + "\n")
    counts, rows = Counter(), []
    for index, block in enumerate(read_blocks(archive)):
        if index >= PROTOCOL["max_complete_games"]:
            break
        counts["complete_games_scanned"] += 1
        if counts["complete_games_scanned"] % 1000 == 0:
            print(json.dumps({"scanned": counts["complete_games_scanned"], "eligible": len(rows)}), flush=True)
        headers = chess.pgn.read_headers(io.StringIO(block))
        problem = header_eligibility(headers or {})
        if problem:
            counts[problem] += 1
            continue
        game = chess.pgn.read_game(io.StringIO(block))
        row, problem = candidate_from_game(game, excluded_fens=fens, excluded_games=games)
        counts[problem or "eligible_games"] += 1
        if row:
            row["source"]["pgn_block_sha256"] = digest(block)
            rows.append(row)
    selected, selection = select(rows)
    files = {}
    for role in ("calibration_development", "calibration_evaluation", "targeted_endgame"):
        path = output / (role + ".jsonl")
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in selected if row["analysis_role"] == role))
        files[role] = {"sha256": file_sha256(path), "count": sum(r["analysis_role"] == role for r in selected)}
    report = {"schema_version": 1, "status": "source_selection_complete_not_engine_verified_or_calibrated",
              "protocol_sha256": file_sha256(output / "protocol.json"), "protocol": protocol,
              "source": source, "scan_counts": dict(counts), **selection, "outputs": files,
              "selected_sides": dict(Counter(r["side_to_move"] for r in selected)),
              "selected_phases": dict(Counter(r["phase"] for r in selected)),
              "selected_rating_groups": dict(Counter(r["rating_group"] for r in selected)),
              "selected_dates": dict(Counter(r["source"]["date"] for r in selected)),
              "missing_mover_clocks": sum(r["clock_seconds_before"] is None for r in selected),
              "unique_known_players": len({p for r in selected for p in r["player_hashes"].values() if p}),
              "missing_player_identity_fields": sum(p is None for r in selected for p in r["player_hashes"].values()),
              "inference_run": False, "engine_searches_run": 0, "trainer_ready": False,
              "limitations": ["bounded chronological prefix, not a random month",
                              "external puzzle/public exposure not fully audited",
                              "no player or near-duplicate separation claimed",
                              "source choices differ from explicit puzzle solving",
                              "model training-overlap audit still required before inference"]}
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cached-source", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.cached_source), indent=2))
