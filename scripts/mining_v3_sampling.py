"""Acquire real White-to-move observations matching the historical Black profile.

Append-only selection resumes by replaying cached archive prefixes. The selection
uses chess metadata only; no engine result or human-model score affects inclusion.
"""
from __future__ import annotations

import argparse
from collections import Counter
import codecs
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import ssl
import sys
import urllib.request
import zipfile

import chess
import chess.pgn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.mining_v2_sampling import (ROOT, SEED, canonical_fen, digest,
    file_sha256, game_identity, phase_of, public_exclusions, split_for_game)

RATING_BINS = ("1800_1999", "2000_2199", "2200_2399", "2400_2599",
               "2600_2799", "2800_plus")


def rating_band(elo):
    return RATING_BINS[min(5, max(0, (elo - 1800) // 200))]


def cell(row):
    return row["cohort"], row["rating_bin"], row["phase"]


def game_blocks(chunks):
    buffer = ""
    for chunk in chunks:
        buffer += chunk
        start = 0
        while True:
            boundary = buffer.find("\n\n[Event ", start + 1)
            if boundary < 0:
                break
            yield buffer[start:boundary]
            start = boundary + 2
        # Slice the large decompression buffer once per chunk, not per game.
        buffer = buffer[start:]
    # A bounded compressed prefix can end inside a game: never parse its tail.


def cached_zstd_chunks(url, cache, limit_mb, stats):
    """Replay a complete cached prefix and append a validated HTTP byte range."""
    import certifi
    import pyzstd
    cache.parent.mkdir(parents=True, exist_ok=True)
    size = cache.stat().st_size if cache.exists() else 0
    limit = limit_mb << 20
    if size > limit:
        raise ValueError("cached prefix exceeds requested byte limit")
    dctx = pyzstd.EndlessZstdDecompressor()
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    sha = hashlib.sha256()
    if size:
        with cache.open("rb") as f:
            while raw := f.read(1 << 20):
                sha.update(raw)
                stats["compressed_bytes_read"] = f.tell()
                yield decoder.decode(dctx.decompress(raw))
    if size == limit:
        stats["stop_reason"] = "compressed_byte_limit"
        return
    metadata = cache.with_suffix(cache.suffix + ".http.json")
    context = ssl.create_default_context(cafile=certifi.where())
    failures = 0
    with cache.open("ab") as out:
        while size < limit:
            headers = {"User-Agent": "machine-unique-chess-research/3"}
            if size:
                headers["Range"] = f"bytes={size}-"
                if metadata.exists():
                    prior = json.loads(metadata.read_text())
                    if prior.get("url") != url:
                        raise ValueError("cached prefix belongs to another URL")
                    if prior.get("etag"):
                        headers["If-Range"] = prior["etag"]
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=45, context=context) as response:
                    if size and (response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {size}-")):
                        raise RuntimeError("server did not honor resume byte range; cached prefix was not changed")
                    stats.update(http_etag=response.headers.get("ETag"),
                                 http_last_modified=response.headers.get("Last-Modified"))
                    metadata.write_text(json.dumps({"url": url, "etag": response.headers.get("ETag"),
                                                    "last_modified": response.headers.get("Last-Modified")}) + "\n")
                    while size < limit:
                        raw = response.read(min(1 << 20, limit - size))
                        if not raw:
                            stats["stop_reason"] = "end_of_stream"
                            return
                        out.write(raw)
                        out.flush()
                        sha.update(raw)
                        size += len(raw)
                        stats["compressed_bytes_read"] = size
                        stats["compressed_prefix_sha256"] = sha.hexdigest()
                        yield decoder.decode(dctx.decompress(raw))
            except OSError as exc:
                failures += 1
                stats.setdefault("network_retries", []).append({"byte_offset": size,
                    "error_type": type(exc).__name__, "message": str(exc)})
                if failures >= 5:
                    raise
    stats.setdefault("stop_reason", "compressed_byte_limit")


def white_candidates(game, source, *, excluded_fens=(), excluded_games=(), sampled_plies=None):
    if game is None:
        return [], "empty_game"
    if game.errors:
        return [], "parse_error"
    if game.headers.get("Variant", "Standard") not in ("Standard", "Chess"):
        return [], "nonstandard"
    if any(game.headers.get(f"{s}Title") == "BOT" for s in ("White", "Black")):
        return [], "bot"
    if game.headers.get("Termination") == "Abandoned":
        return [], "abandoned"
    try:
        we, be = int(game.headers["WhiteElo"]), int(game.headers["BlackElo"])
        if min(we, be) <= 0:
            raise ValueError
    except (KeyError, ValueError):
        return [], "missing_rating"
    gid = game_identity(game, source["archive"], source["member"], source["game_index"])
    if gid in excluded_games:
        return [], "public_game_id"
    board = game.board()
    if type(board) is not chess.Board or not board.is_valid():
        return [], "invalid_board"
    initial = board.fen()
    history, states, rows = [], [initial], []
    clocks = {chess.WHITE: None, chess.BLACK: None}
    allowed_plies = set(sampled_plies) if sampled_plies is not None else set(range(15, 72, 4))
    src = {**source, "date": game.headers.get("UTCDate", game.headers.get("Date")),
           "utc_time": game.headers.get("UTCTime"),
           "game_url": game.headers.get("LichessURL", game.headers.get("Site")),
           "event": game.headers.get("Event"), "result": game.headers.get("Result"),
           "termination": game.headers.get("Termination"),
           "white_title": game.headers.get("WhiteTitle"),
           "black_title": game.headers.get("BlackTitle")}
    for ply, node in enumerate(game.mainline(), 1):
        fen = board.fen()
        # board.fen() already uses legal en-passant and canonical castling rights.
        if " ".join(fen.split()[:4]) in excluded_fens:
            return [], "public_position_in_game"
        if node.move not in board.legal_moves:
            return [], "illegal_move"
        # Next genuine White turn after each historical Black sampling slot.
        if ply in allowed_plies and board.turn == chess.WHITE and not board.is_game_over():
            rows.append({"id": f"v3-white-{gid}-{ply}", "fen": fen,
                         "game_id": gid, "split": split_for_game(gid),
                         "game_hash_split": split_for_game(gid), "source": src,
                         "cohort": source["cohort"], "initial_fen": initial,
                         "history_uci": history.copy(), "history_fens": states[-8:],
                         "history_available": True, "played_move": node.move.uci(),
                         "white_elo": we, "black_elo": be, "mover_elo": we,
                         "rating_bin": rating_band(we), "side_to_move": "white",
                         "time_control": game.headers.get("TimeControl"),
                         "clock_seconds_before": clocks[chess.WHITE],
                         "opponent_clock_seconds": clocks[chess.BLACK],
                         "clock_seconds_after_played_move": node.clock(),
                         "clock_source": "pgn_clk_annotation_or_null",
                         "phase": phase_of(board, ply), "ply": ply,
                         "sampling_method": "next_white_turn_after_legacy_4_ply_slot" if sampled_plies is None else "additional_actual_white_plies_13_through_99",
                         "bot_game": False, "contains_bot": False})
        mover = board.turn
        clocks[mover] = node.clock()
        history.append(node.move.uci())
        board.push(node.move)
        states.append(board.fen())
    if " ".join(board.fen().split()[:4]) in excluded_fens:
        return [], "public_position_in_game"
    return rows, None


class Selector:
    def __init__(self, targets, output, pilot):
        self.targets = targets
        self.output = output
        self.counts, self.games, self.skips = Counter(), Counter(), Counter()
        self.ids, self.fens, self.pilot_games = set(), set(), set()
        with pilot.open() as f:
            for line in f:
                row = json.loads(line)
                self.pilot_games.add(row["game_id"])
                if row["side_to_move"] == "white":
                    self.fens.add(canonical_fen(row["fen"]))
        if output.exists():
            with output.open() as f:
                for line in f:
                    row = json.loads(line)
                    canon = canonical_fen(row["fen"])
                    if row["id"] in self.ids or canon in self.fens:
                        raise ValueError("duplicate in resumed White sample")
                    self.ids.add(row["id"])
                    self.fens.add(canon)
                    self.games[row["game_id"]] += 1
                    self.counts[cell(row)] += 1
            if any(self.counts[k] > n for k, n in targets.items()):
                raise ValueError("resume file exceeds target profile")

    def needed(self, cohort, band=None):
        return sum(n - self.counts[k] for k, n in self.targets.items()
                   if k[0] == cohort and (band is None or k[1] == band))

    def add(self, rows, fh):
        added = 0
        for row in sorted(rows, key=lambda r: digest(f"{SEED}:v3-selection:{r['id']}")):
            key = cell(row)
            if self.counts[key] >= self.targets.get(key, 0):
                continue
            canon = canonical_fen(row["fen"])
            if row["id"] in self.ids or canon in self.fens:
                self.skips["duplicate_canonical_or_id"] += 1
                continue
            if self.games[row["game_id"]] >= 15:
                self.skips["game_cap"] += 1
                continue
            row["shares_game_with_pilot"] = row["game_id"] in self.pilot_games
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
            self.ids.add(row["id"])
            self.fens.add(canon)
            self.games[row["game_id"]] += 1
            self.counts[key] += 1
            added += 1
        if added:
            fh.flush()
        return added


def reconcile_profile(output, targets):
    """Retain observed rows up to corrected cell quotas, preserving old output."""
    if not output.exists():
        return {"removed": 0, "retained": 0}
    sha = file_sha256(output)
    archive = output.parent / "sampling_archive" / f"white-{sha[:16]}.jsonl"
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        shutil.copyfile(output, archive)
    counts, removed = Counter(), 0
    temp = output.with_suffix(".reconciled.tmp")
    with output.open() as f, temp.open("w") as out:
        for line in f:
            row = json.loads(line)
            key = cell(row)
            if counts[key] >= targets.get(key, 0):
                removed += 1
                continue
            if row.get("bot_game") is not False:
                raise ValueError("White expansion contains an unverified bot status")
            row["contains_bot"] = False
            out.write(json.dumps(row, separators=(",", ":")) + "\n")
            counts[key] += 1
    temp.replace(output)
    return {"removed": removed, "retained": sum(counts.values()),
            "previous_positions_sha256": sha, "previous_positions_archive": str(archive.relative_to(output.parent))}


def validate_selection(path, targets, pilot):
    """Stream full history replay and validate global uniqueness and quotas."""
    from scripts.mining_v2_sampling import validate_rows
    counts, game_counts = Counter(), Counter()
    fens, ids, game_splits = set(), set(), {}
    with pilot.open() as f:
        for line in f:
            row = json.loads(line)
            if row["side_to_move"] == "white":
                fens.add(canonical_fen(row["fen"]))
            game_splits[row["game_id"]] = row["split"]
    batch, initial_fens, clocks = [], len(fens), 0
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            canon = canonical_fen(row["fen"])
            if row["side_to_move"] != "white" or row.get("contains_bot") is not False:
                raise ValueError("side or bot status invalid")
            if canon in fens or row["id"] in ids:
                raise ValueError("duplicate canonical White observation")
            if game_splits.get(row["game_id"], row["split"]) != row["split"]:
                raise ValueError("game split leaks against prior observations")
            game_splits[row["game_id"]] = row["split"]
            fens.add(canon)
            ids.add(row["id"])
            counts[cell(row)] += 1
            game_counts[row["game_id"]] += 1
            clocks += row["clock_seconds_before"] is not None
            batch.append(row)
            if len(batch) == 500:
                validate_rows(batch)
                batch = []
    if batch:
        validate_rows(batch)
    if counts != Counter(targets) or max(game_counts.values(), default=0) > 15:
        raise ValueError("target quotas or game cap failed")
    return {"positions": len(ids), "unique_canonical_positions": len(fens) - initial_fens,
            "games": len(game_counts), "max_positions_per_game": max(game_counts.values(), default=0),
            "clock_before_available": clocks, "history_replay_valid": True,
            "exact_target_cells": True, "pilot_white_overlap": 0,
            "game_hash_split_consistent_with_pilot": True, "known_bot_games": 0}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", type=Path, default=ROOT / "data/mining_v3/target_profile_corrected.json")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "data/mining_v3")
    ap.add_argument("--club-months", nargs="+", default=["2026-06", "2026-07"])
    ap.add_argument("--club-limit-mb", type=int, default=512)
    ap.add_argument("--cohort", choices=("all", "elite", "club", "supplement", "local"), default="all")
    ap.add_argument("--reconcile-profile", action="store_true", help="Preserve prior output and trim rows exceeding corrected metadata quotas")
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    profile = json.loads(args.profile.read_text())
    targets = {(x["cohort"], x["rating_bin"], x["phase"]): x["count"] for x in profile["cells"]}
    old_progress = args.output_dir / "white_sampling_progress.json"
    prior = json.loads(old_progress.read_text()) if old_progress.exists() else None
    reconciliation = reconcile_profile(args.output_dir / "white_new.jsonl", targets) if args.reconcile_profile else None
    selector = Selector(targets, args.output_dir / "white_new.jsonl", ROOT / "data/mining_v2/positions.jsonl")
    excluded_fens, excluded_games, public = public_exclusions()
    stats_path = args.output_dir / "white_sampling_progress.json"
    sources, skips = [], Counter()

    def report():
        report = {"created_at": datetime.now(timezone.utc).isoformat(),
                  "target": sum(targets.values()), "selected": sum(selector.counts.values()),
                  "remaining": {c: selector.needed(c) for c in ("elite", "club")},
                  "cells": [{"cohort": k[0], "rating_bin": k[1], "phase": k[2],
                             "target": n, "selected": selector.counts[k]} for k, n in sorted(targets.items())],
                  "games": len(selector.games), "sources": sources,
                  "excluded_games_by_reason": dict(skips),
                  "selection_skips": dict(selector.skips), "public_exclusions": public,
                  "profile_sha256": file_sha256(args.profile),
                  "reconciliation": reconciliation,
                  "prior_run": prior,
                  "script_sha256": file_sha256(Path(__file__)),
                  "method": "Exact corrected historical cohort × mover 200-Elo band × phase quotas. The primary sample uses actual White turns at plies 15,19,...,71. Explicitly tagged supplements can use additional actual White plies 13–99 from preserved games or eligible slow games from elite archives. At most 15 new positions per game; game hash determines split, public games excluded; canonical deduplication against all new White and the existing White pilot.",
                  "limitations": ["Bounded chronological archive prefixes, not a population-random sample.",
                                  "White positions share games and may be adjacent to historical Black observations; they are not independent samples.",
                                  "Time controls are retained but not exactly matched because much historical metadata was originally missing; club eligibility requires both Elo >=1800 and base time >=600 seconds.",
                                  "New White excludes explicit BOT titles; historical Black BOT contamination is retained and must be reported and excluded from human-only analyses.",
                                  "Game hash split alone does not establish an unexposed test set; downstream exposure reconciliation is required."]}
        temp = stats_path.with_suffix(".tmp")
        temp.write_text(json.dumps(report, indent=2) + "\n")
        temp.replace(stats_path)
        print(json.dumps({"selected": report["selected"], "remaining": report["remaining"],
                          "source": sources[-1] if sources else None}), flush=True)

    with selector.output.open("a") as selected:
        if args.cohort == "local":
            for preserved in sorted(args.output_dir.glob("club_*_eligible_games.pgn")):
                if not selector.needed("club"):
                    break
                month = re.search(r"20\d\d-\d\d", preserved.name).group(0)
                info = {"archive": f"lichess_db_standard_rated_{month}.pgn.zst",
                        "preserved_pgn_file": preserved.name, "sha256": file_sha256(preserved),
                        "sha256_scope": "preserved_eligible_game_pgns", "source_month": month,
                        "cohort": "club", "selection_supplement": "cached_game_additional_white_plies",
                        "games_scanned": 0, "selected": 0}
                sources.append(info)
                with preserved.open() as stream:
                    for text in game_blocks(iter(lambda: stream.read(1 << 20), "")):
                        info["games_scanned"] += 1
                        headers = dict(re.findall(r'^\[(\w+) "([^"\n]*)"\]', text, re.M))
                        try:
                            we, be = int(headers["WhiteElo"]), int(headers["BlackElo"])
                            qualifies = min(we, be) >= 1800 and int(headers.get("TimeControl", "0+0").split("+")[0]) >= 600
                        except (ValueError, KeyError):
                            qualifies = False
                        gid = headers.get("Site", "").rsplit("/", 1)[-1]
                        if not qualifies or not selector.needed("club", rating_band(we)) or selector.games[gid] >= 15:
                            continue
                        game = chess.pgn.read_game(io.StringIO(text))
                        src = {k: v for k, v in info.items() if k not in ("games_scanned", "selected")}
                        src.update(member="preserved-eligible-PGN", game_index=info["games_scanned"], pgn_sha256=digest(text))
                        rows, reason = white_candidates(game, src, excluded_fens=excluded_fens,
                            excluded_games=excluded_games, sampled_plies=range(13, 101, 2))
                        if reason:
                            skips[reason] += 1
                        else:
                            for row in rows:
                                row["source_month"] = month
                                row["selection_supplement"] = "cached_game_additional_white_plies"
                            info["selected"] += selector.add(rows, selected)
                        if not selector.needed("club"):
                            break
                report()
        if args.cohort in ("supplement", "local"):
            remaining = {k: n - selector.counts[k] for k, n in targets.items() if n > selector.counts[k]}
            if sum(remaining.values()) > 5000 or any(k[0] != "club" for k in remaining):
                raise SystemExit("Supplement is restricted to a residual <=5000-position slower-game tail; continue ordinary acquisition first.")
            for month in ("2025-09", "2025-10", "2025-11"):
                if not selector.needed("club"):
                    break
                archive = ROOT / f"data/elite_{month}.zip"
                info = {"archive": archive.name, "sha256": file_sha256(archive),
                        "source_month": month, "archive_cohort": "elite",
                        "cohort": "club", "selection_supplement": "elite_archive_slow_game",
                        "games_scanned": 0, "selected": 0,
                        "eligibility": "Both Elo >=1800, base time >=600 seconds; no explicit BOT title."}
                sources.append(info)
                with zipfile.ZipFile(archive) as zf:
                    for member in sorted(n for n in zf.namelist() if n.endswith(".pgn")):
                        with zf.open(member) as raw:
                            stream = io.TextIOWrapper(raw, encoding="utf-8", errors="strict")
                            for text in game_blocks(iter(lambda: stream.read(1 << 20), "")):
                                info["games_scanned"] += 1
                                headers = dict(re.findall(r'^\[(\w+) "([^"\n]*)"\]', text, re.M))
                                try:
                                    we, be = int(headers["WhiteElo"]), int(headers["BlackElo"])
                                    qualifies = min(we, be) >= 1800 and int(headers.get("TimeControl", "0+0").split("+")[0]) >= 600
                                except (ValueError, KeyError):
                                    qualifies = False
                                if not qualifies or not selector.needed("club", rating_band(we)):
                                    continue
                                game = chess.pgn.read_game(io.StringIO(text))
                                src = {"archive": archive.name, "sha256": info["sha256"],
                                       "source_month": month, "archive_cohort": "elite",
                                       "cohort": "club", "member": member,
                                       "game_index": info["games_scanned"], "pgn_sha256": digest(text),
                                       "selection_supplement": "elite_archive_slow_game"}
                                rows, reason = white_candidates(game, src, excluded_fens=excluded_fens, excluded_games=excluded_games)
                                if reason:
                                    skips[reason] += 1
                                else:
                                    for row in rows:
                                        row["source_month"] = month
                                        row["selection_supplement"] = "elite_archive_slow_game"
                                    info["selected"] += selector.add(rows, selected)
                                if not selector.needed("club"):
                                    break
                        if not selector.needed("club"):
                            break
                report()
        if args.cohort in ("all", "elite"):
            for month in ("2025-09", "2025-10", "2025-11"):
                if not selector.needed("elite"):
                    break
                archive = ROOT / f"data/elite_{month}.zip"
                info = {"archive": archive.name, "sha256": file_sha256(archive),
                        "cohort": "elite", "games_scanned": 0, "selected": 0}
                sources.append(info)
                with zipfile.ZipFile(archive) as zf:
                    for member in sorted(n for n in zf.namelist() if n.endswith(".pgn")):
                        with zf.open(member) as raw:
                            stream = io.TextIOWrapper(raw, encoding="utf-8", errors="strict")
                            for text in game_blocks(iter(lambda: stream.read(1 << 20), "")):
                                info["games_scanned"] += 1
                                headers = dict(re.findall(r'^\[(\w+) "([^"\n]*)"\]', text, re.M))
                                try:
                                    elo = int(headers["WhiteElo"])
                                except (ValueError, KeyError):
                                    continue
                                if elo < 1800 or not selector.needed("elite", rating_band(elo)):
                                    continue
                                game = chess.pgn.read_game(io.StringIO(text))
                                src = {"archive": archive.name, "sha256": info["sha256"],
                                       "cohort": "elite", "member": member,
                                       "game_index": info["games_scanned"], "pgn_sha256": digest(text)}
                                rows, reason = white_candidates(game, src, excluded_fens=excluded_fens, excluded_games=excluded_games)
                                if reason:
                                    skips[reason] += 1
                                else:
                                    info["selected"] += selector.add(rows, selected)
                                if info["games_scanned"] % 1000 == 0:
                                    report()
                                if not selector.needed("elite"):
                                    break
                        if not selector.needed("elite"):
                            break
                report()
        if args.cohort in ("all", "club"):
            for month in args.club_months:
                if not selector.needed("club"):
                    break
                url = f"https://database.lichess.org/standard/lichess_db_standard_rated_{month}.pgn.zst"
                cache = args.output_dir / f"club_{month}_prefix.pgn.zst"
                saved_path = args.output_dir / f"club_{month}_eligible_games.pgn"
                saved_ids = set()
                if saved_path.exists():
                    with saved_path.open() as f:
                        for line in f:
                            if line.startswith('[Site "'):
                                saved_ids.add(line.split('"')[1].rsplit('/', 1)[-1])
                info = {"archive": url.rsplit("/", 1)[-1], "url": url,
                        "cohort": "club", "games_scanned": 0, "eligible_games": 0,
                        "selected": 0, "compressed_byte_limit": args.club_limit_mb << 20}
                sources.append(info)
                with saved_path.open("a") as saved:
                    for text in game_blocks(cached_zstd_chunks(url, cache, args.club_limit_mb, info)):
                        info["games_scanned"] += 1
                        headers = dict(re.findall(r'^\[(\w+) "([^"\n]*)"\]', text, re.M))
                        try:
                            we, be = int(headers["WhiteElo"]), int(headers["BlackElo"])
                            qualifies = min(we, be) >= 1800 and int(headers.get("TimeControl", "0+0").split("+")[0]) >= 600
                        except (ValueError, KeyError):
                            qualifies = False
                        if qualifies:
                            gid = headers.get("Site", "").rsplit("/", 1)[-1]
                            if gid not in saved_ids:
                                saved.write(text + "\n\n")
                                saved.flush()
                                saved_ids.add(gid)
                            info["eligible_games"] += 1
                            if selector.needed("club", rating_band(we)):
                                game = chess.pgn.read_game(io.StringIO(text))
                                src = {"archive": info["archive"], "url": url,
                                       "cohort": "club", "member": "compressed-prefix",
                                       "game_index": info["games_scanned"], "pgn_sha256": digest(text),
                                       "preserved_pgn_file": saved_path.name}
                                rows, reason = white_candidates(game, src, excluded_fens=excluded_fens, excluded_games=excluded_games)
                                if reason:
                                    skips[reason] += 1
                                else:
                                    info["selected"] += selector.add(rows, selected)
                                    if rows:
                                        info.setdefault("first_eligible_date", rows[0]["source"]["date"])
                                        info["last_eligible_date"] = rows[0]["source"]["date"]
                        if info["games_scanned"] % 10000 == 0:
                            report()
                        if not selector.needed("club"):
                            info["stop_reason"] = "all_cohort_quotas_met"
                            break
                if cache.exists():
                    info["compressed_prefix_sha256"] = file_sha256(cache)
                    info["compressed_bytes_read"] = cache.stat().st_size
                info["eligible_pgn_sha256"] = file_sha256(saved_path)
                report()
    report()
    if sum(selector.counts.values()) != sum(targets.values()):
        raise SystemExit("Sample remains incomplete; resume with a larger prefix limit or another month.")
    progress = json.loads(stats_path.read_text())
    progress["positions_sha256"] = file_sha256(selector.output)
    progress["validation"] = validate_selection(selector.output, targets, ROOT / "data/mining_v2/positions.jsonl")
    frozen_profile = args.output_dir / "white_target_profile.json"
    frozen_profile.write_bytes(args.profile.read_bytes())
    progress["profile_file"] = frozen_profile.name
    progress["profile_sha256"] = file_sha256(frozen_profile)
    progress["retained_source_files"] = {}
    for pattern in ("club_*_prefix.pgn.zst", "club_*_eligible_games.pgn"):
        for retained in sorted(args.output_dir.glob(pattern)):
            progress["retained_source_files"][retained.name] = {
                "bytes": retained.stat().st_size, "sha256": file_sha256(retained)}
    supplements = Counter()
    with selector.output.open() as f:
        for line in f:
            row = json.loads(line)
            if row.get("selection_supplement"):
                supplements[f"{row['selection_supplement']}/{row['source_month']}"] += 1
    progress["selection_supplements"] = dict(supplements)
    if supplements:
        progress["limitations"].append("Labelled supplements include additional real White plies from cached games and slow games from 2025 elite archives. The latter are outside the 2026 standard-archive sampling frame and have no recorded move clocks. Exact monthly or individual time-control matching is not claimed; the 15-position per-game cap and canonical deduplication still apply.")
        progress["cohort_interpretation"] = {"elite": "Elite archive sample", "club": "Slower-game cohort: both Elo >=1800 and base >=600 seconds; 2026 standard archives plus explicitly labelled 2025 elite-archive slow-game supplement."}
    progress["complete"] = True
    (args.output_dir / "white_sampling_manifest.json").write_text(json.dumps(progress, indent=2) + "\n")


if __name__ == "__main__":
    main()
