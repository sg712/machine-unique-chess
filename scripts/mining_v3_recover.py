"""Recover provenance for every historical Black row without changing its identity.

The historical corpus is preserved, including repeated canonical positions and
games involving bots. Missing or ambiguous histories remain explicitly missing.
Exact FEN, ply, played move and both ratings must match a source game, except
documented November eN archive aliases or exact club URL IDs establish identity and correct a
historical FEN-only rating join. When a legacy game has several rows, every one
must agree with the same source game.
The complete supplied archives are scanned to detect ambiguous matches.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import zipfile

import chess
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.mining_v2_sampling import canonical_fen, file_sha256, game_identity, phase_of, split_for_game

HEADER_RE = re.compile(r'^\[(\w+) "(.*)"\]$', re.MULTILINE)


def atomic_json(path, value, *, pretty=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2 if pretty else None,
                                  separators=None if pretty else (",", ":")) + "\n")
    partial.replace(path)


def game_blocks(stream):
    """Yield PGN blocks while retaining boundaries across arbitrary read sizes."""
    buf = ""
    while chunk := stream.read(1 << 20):
        buf += chunk
        while True:
            cut = buf.find("\n\n[Event ", 1)
            if cut < 0:
                break
            yield buf[:cut]
            buf = buf[cut + 2:]
    if buf.strip():
        yield buf


def archive_blocks(path):
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            for member in zf.namelist():
                if member.endswith(".pgn"):
                    with io.TextIOWrapper(zf.open(member), encoding="utf-8", errors="replace") as stream:
                        for index, block in enumerate(game_blocks(stream), 1):
                            yield member, index, block
    else:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for index, block in enumerate(game_blocks(stream), 1):
                yield path.name, index, block


def rating_band(elo):
    return "under_1800" if elo < 1800 else "1800_1999" if elo < 2000 else "2000_2199" if elo < 2200 else "2200_2399" if elo < 2400 else "2400_2599" if elo < 2600 else "2600_2799" if elo < 2800 else "2800_plus"


def time_class(value):
    if value in (None, "", "-", "?"):
        return "unknown"
    try:
        base, increment = map(float, value.split("+"))
        seconds = base + 40 * increment
    except (ValueError, TypeError, AttributeError):
        return "unknown"
    if not all(math.isfinite(x) and x >= 0 for x in (base, increment)):
        return "unknown"
    return "bullet" if seconds < 180 else "blitz" if seconds < 480 else "rapid" if seconds < 1500 else "classical"


def row_key(row):
    return (row["fen"], int(row["ply"]), row["played_move"], int(float(row["white_elo"])), int(float(row["black_elo"])))


def scan_archives(rows, paths, cache_path, master_path=None):
    """Keep compact game histories and row links, never infer a missing move."""
    wanted = defaultdict(list)
    groups = defaultdict(set)
    pairs = set()
    for index, row in enumerate(rows):
        wanted[row_key(row)].append(index)
        groups[row["game_id"]].add(index)
        pairs.add((int(float(row["white_elo"])), int(float(row["black_elo"]))))
    hits = defaultdict(set)
    games = {}
    manifests = []
    for path in paths:
        initial_stat = path.stat()
        archive_hash = file_sha256(path)
        if (path.stat().st_size, path.stat().st_mtime_ns) != (initial_stat.st_size, initial_stat.st_mtime_ns):
            raise ValueError(f"Source file changed during hashing; freeze the PGN before recovery: {path}")
        valid_rating_game_index = 0
        info = {"path": str(path), "sha256": archive_hash, "bytes": path.stat().st_size,
                "games_scanned": 0, "games_parsed": 0, "matching_games": 0,
                "parse_errors": 0, "complete_supplied_file_scan": True}
        for member, index, block in archive_blocks(path):
            info["games_scanned"] += 1
            headers = dict(HEADER_RE.findall(block.split("\n\n", 1)[0]))
            try:
                pair = (int(headers["WhiteElo"]), int(headers["BlackElo"]))
            except (KeyError, ValueError):
                continue
            valid_rating_game_index += 1
            # Experiment 22 defines eN as the Nth November game with numeric
            # player ratings. Some historical ratings were attached by FEN
            # alone and belong to another game; recover these only through
            # that documented archive-order identity and the entire trajectory.
            archive_alias = f"e{valid_rating_game_index}" if path.name == "elite_2025-11.zip" and valid_rating_game_index <= 2500 else None
            alias_rows = set(groups.get(archive_alias, set()))
            direct_link = headers.get("LichessURL", headers.get("Site", ""))
            direct_match = re.search(r"lichess\.org/([A-Za-z0-9]{8})(?:/|$)", direct_link)
            if direct_match:
                direct_id = direct_match.group(1)
                direct_rows = groups.get(direct_id, set())
                if direct_rows and all(rows[i]["source"] == "club" for i in direct_rows):
                    alias_rows.update(direct_rows)
            # Real club game IDs provide a second inexpensive prefilter.
            if pair not in pairs and not alias_rows:
                continue
            game = chess.pgn.read_game(io.StringIO(block))
            info["games_parsed"] += 1
            if game is None or game.errors:
                info["parse_errors"] += 1
                continue
            if game.headers.get("Variant", "Standard") not in ("Chess", "Standard"):
                continue
            board = game.board()
            if type(board) is not chess.Board or not board.is_valid():
                continue
            initial = board.fen()
            found, moves, clocks = set(), [], []
            alias_keys = {(rows[i]["fen"], int(rows[i]["ply"]), rows[i]["played_move"]): i for i in alias_rows}
            for ply, node in enumerate(game.mainline(), 1):
                if node.move not in board.legal_moves:
                    found = set()
                    break
                key = (board.fen(), ply, node.move.uci(), *pair)
                found.update(wanted.get(key, ()))
                if key[:3] in alias_keys:
                    found.add(alias_keys[key[:3]])
                moves.append(node.move.uci())
                clocks.append(node.clock())
                board.push(node.move)
            if not found:
                continue
            gid = game_identity(game, path.name, member, index)
            # A legacy game group is recovered only if its entire stored
            # trajectory matches. Club IDs must also match the source URL.
            complete = set()
            for legacy_gid in {rows[i]["game_id"] for i in found}:
                required = groups[legacy_gid]
                if not required <= found:
                    continue
                if any(rows[i]["source"] == "club" for i in required) and gid != legacy_gid:
                    continue
                complete.update(required)
            if not complete:
                continue
            signature = hashlib.sha256((initial + " " + " ".join(moves)).encode()).hexdigest()
            identity = gid + ":" + signature
            if identity not in games:
                games[identity] = {"game_id": gid, "initial_fen": initial, "moves": moves,
                                   "clocks": clocks, "headers": dict(game.headers),
                                   "source": {"archive": path.name, "sha256": archive_hash,
                                              "member": member, "game_index": index,
                                              "game_moves_sha256": signature}}
            for row_index in complete:
                hits[row_index].add(identity)
            info["matching_games"] += 1
            if info["matching_games"] % 1000 == 0:
                print(f'{path.name}: {info["games_scanned"]} scanned; {info["matching_games"]} matching games', flush=True)
        if (path.stat().st_size, path.stat().st_mtime_ns) != (initial_stat.st_size, initial_stat.st_mtime_ns):
            raise ValueError(f"Source file changed during recovery; freeze the PGN before recovery: {path}")
        manifests.append(info)
        print(json.dumps(info), flush=True)
    cache = {"schema_version": 3, "master_sha256": file_sha256(master_path or ROOT / "results/master_all.csv"),
             "archives": manifests, "games": games,
             "hits": {str(i): sorted(identities) for i, identities in hits.items()}}
    atomic_json(cache_path, cache)
    return cache


def recovered_snapshot(game, target_ply):
    board = chess.Board(game["initial_fen"])
    history, states = [], [board.fen()]
    clocks = {chess.WHITE: None, chess.BLACK: None}
    for ply, move in enumerate(game["moves"], 1):
        if ply == target_ply:
            return {"initial_fen": game["initial_fen"], "history_uci": history,
                    "history_fens": states[-8:], "history_available": True,
                    "clock_seconds_before": clocks[board.turn],
                    "opponent_clock_seconds": clocks[not board.turn],
                    "clock_seconds_after_played_move": game["clocks"][ply - 1]}
        clocks[board.turn] = game["clocks"][ply - 1]
        board.push_uci(move)
        history.append(move)
        states.append(board.fen())
    raise ValueError(f"Source game does not reach ply {target_ply}")


def extend_cache(previous, addition):
    if previous["master_sha256"] != addition["master_sha256"]:
        raise ValueError("Cannot merge recovery caches for different historical corpora")
    games = dict(previous["games"])
    for identity, game in addition["games"].items():
        old = games.get(identity)
        if old is None or sum(c is not None for c in game["clocks"]) > sum(c is not None for c in old["clocks"]):
            games[identity] = game
    hits = {key: set(values) for key, values in previous["hits"].items()}
    for key, values in addition["hits"].items():
        hits.setdefault(key, set()).update(values)
    archives = {a["sha256"]: a for a in previous["archives"] + addition["archives"]}
    return {"schema_version": 3, "master_sha256": previous["master_sha256"],
            "archives": list(archives.values()), "games": games,
            "hits": {key: sorted(values) for key, values in hits.items()}}


def make_row(row, index, cache, master_hash, snapshot=None):
    board = chess.Board(row["fen"])
    if board.turn != chess.BLACK:
        raise ValueError(f"Historical row {index} is not Black to move")
    ply = int(row["ply"])
    ids = cache.get("hits", {}).get(str(index), [])
    recovered = cache["games"][ids[0]] if len(ids) == 1 else None
    gid = recovered["game_id"] if recovered else "legacy-" + row["game_id"]
    headers = recovered["headers"] if recovered else {}
    white_elo = int(headers["WhiteElo"]) if recovered else int(float(row["white_elo"]))
    black_elo = int(headers["BlackElo"]) if recovered else int(float(row["black_elo"]))
    base = {"id": f"v3-historical-black-{index:06d}", "fen": row["fen"], "game_id": gid,
            "legacy_game_id": row["game_id"], "split": split_for_game(gid),
            "cohort": row["source"], "side_to_move": "black", "ply": ply,
            "played_move": row["played_move"], "white_elo": white_elo,
            "black_elo": black_elo, "mover_elo": black_elo,
            "rating_bin": rating_band(black_elo), "phase": phase_of(board, ply),
            "ratings_corrected_from_source": white_elo != int(float(row["white_elo"])) or black_elo != int(float(row["black_elo"])),
            "time_control": headers.get("TimeControl"),
            "time_control_class": time_class(headers.get("TimeControl")),
            "history_recovery": "exact_complete_legacy_game_match" if recovered else "ambiguous" if ids else "source_not_recovered",
            "rating_recovery": "source_pgn" if recovered else "historical_csv_unverified",
            "source_match_count": len(ids), "contains_bot": any(headers.get(s + "Title") == "BOT" for s in ("White", "Black")) if recovered else None,
            "mover_is_bot": headers.get("BlackTitle") == "BOT" if recovered else None,
            "opponent_is_bot": headers.get("WhiteTitle") == "BOT" if recovered else None,
            "source": {"master_sha256": master_hash, "master_row_index": index, "batch": row["batch"],
                       "cohort": row["source"], "legacy_game_id": row["game_id"],
                       **(recovered["source"] if recovered else {}),
                       "date": headers.get("UTCDate", headers.get("Date")),
                       "url": headers.get("LichessURL", headers.get("Site")),
                       "event": headers.get("Event"), "termination": headers.get("Termination")},
            "historical": {"engine_best": row["engine_best"], "best_cp": float(row["best_cp"]),
                           "engine_margin": float(row["engine_margin"]), "p_max": float(row["p_max"]),
                           "white_elo": int(float(row["white_elo"])), "black_elo": int(float(row["black_elo"])),
                           "machine_unique": row["machine_unique"] == "True"}}
    if recovered:
        base.update(snapshot if snapshot is not None else recovered_snapshot(recovered, ply))
        if base["history_fens"][-1] != row["fen"]:
            raise ValueError(f"Recovered history differs at row {index}")
    else:
        base.update({"initial_fen": row["fen"], "history_uci": [], "history_fens": [row["fen"]],
                     "history_available": False, "clock_seconds_before": None, "opponent_clock_seconds": None,
                     "clock_seconds_after_played_move": None})
    return base


def write_corpus(rows, pilot_rows, cache, output, manifest_path, master_path, pilot_path):
    master_hash = file_sha256(master_path)
    if cache["master_sha256"] != master_hash:
        raise ValueError("Recovery cache belongs to a different historical corpus")
    canonical_first, counts, cells = {}, Counter(), Counter()
    historical_cells, known_human_cells = Counter(), Counter()
    wanted_plies = defaultdict(set)
    for index, row in enumerate(rows):
        found = cache["hits"].get(str(index), [])
        if len(found) == 1:
            wanted_plies[found[0]].add(int(row["ply"]))
    game_ids, legacy_ids, ids = set(), set(), set()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    with partial.open("w") as dest:
        def emit(row):
            if row["id"] in ids:
                raise ValueError("Duplicate record identity")
            ids.add(row["id"])
            key = canonical_fen(row["fen"])
            first = canonical_first.setdefault(key, row["id"])
            row["canonical_duplicate_of"] = None if first == row["id"] else first
            row["canonical_position_sha256"] = hashlib.sha256(key.encode()).hexdigest()
            if chess.Board(row["fen"]).turn != chess.BLACK:
                raise ValueError("Non-Black position in Black corpus")
            row["rating_bin"] = rating_band(row["mover_elo"])
            row["time_control_class"] = time_class(row.get("time_control"))
            counts["positions"] += 1
            counts["history_available"] += bool(row["history_available"])
            counts["clock_available"] += row.get("clock_seconds_before") is not None
            counts["time_control_available"] += row.get("time_control_class") != "unknown"
            counts["known_bot_positions"] += row.get("contains_bot") is True
            counts["bot_status_unknown"] += row.get("contains_bot") is None
            counts["ratings_corrected_from_source"] += row.get("ratings_corrected_from_source") is True
            counts["known_bot_mover_positions"] += row.get("mover_is_bot") is True
            counts["known_bot_opponent_positions"] += row.get("opponent_is_bot") is True
            counts["canonical_duplicate_rows"] += row["canonical_duplicate_of"] is not None
            game_ids.add(row["game_id"])
            if row.get("legacy_game_id"):
                legacy_ids.add(row["legacy_game_id"])
            cells[(row["cohort"], row["rating_bin"], row["phase"], row["time_control_class"])] += 1
            if row.get("legacy_game_id"):
                historical_cells[(row["cohort"], row["rating_bin"], row["phase"])] += 1
            if row.get("contains_bot") is False:
                known_human_cells[(row["cohort"], row["rating_bin"], row["phase"], row["time_control_class"])] += 1
            dest.write(json.dumps(row, separators=(",", ":")) + "\n")
        last_identity, snapshots = None, {}
        for index, row in enumerate(rows):
            found = cache["hits"].get(str(index), [])
            identity = found[0] if len(found) == 1 else None
            if identity and identity != last_identity:
                game = cache["games"][identity]
                board = chess.Board(game["initial_fen"])
                history, states, clocks = [], [board.fen()], {chess.WHITE: None, chess.BLACK: None}
                snapshots = {}
                for ply, move in enumerate(game["moves"], 1):
                    if ply in wanted_plies[identity]:
                        snapshots[ply] = {"initial_fen": game["initial_fen"], "history_uci": history.copy(),
                                          "history_fens": states[-8:], "history_available": True,
                                          "clock_seconds_before": clocks[board.turn],
                                          "opponent_clock_seconds": clocks[not board.turn],
                                          "clock_seconds_after_played_move": game["clocks"][ply - 1]}
                    if ply >= max(wanted_plies[identity]):
                        break
                    clocks[board.turn] = game["clocks"][ply - 1]
                    board.push_uci(move)
                    history.append(move)
                    states.append(board.fen())
                last_identity = identity
            emit(make_row(row, index, cache, master_hash, snapshots.get(int(row["ply"])) if identity else None))
        for original in pilot_rows:
            if chess.Board(original["fen"]).turn != chess.BLACK:
                continue
            row = dict(original)
            row["id"] = "v3-pilot-" + original["id"]
            row["pilot_id"] = original["id"]
            row["history_available"] = True
            row["history_recovery"] = "preserved_v2_actual_history"
            row["contains_bot"] = False
            row["mover_is_bot"] = False
            row["opponent_is_bot"] = False
            emit(row)
    partial.replace(output)
    manifest = {"schema_version": 3, "created_at": datetime.now(timezone.utc).isoformat(),
                "historical_positions": len(rows), "pilot_black_positions": len(ids) - len(rows),
                "input_sha256": {str(master_path): master_hash, str(pilot_path): file_sha256(pilot_path)},
                "output_sha256": file_sha256(output), "output": str(output),
                "recovery_archives": cache["archives"], "counts": dict(counts),
                "distinct_canonical_positions": len(canonical_first), "source_game_ids": len(game_ids),
                "legacy_game_ids": len(legacy_ids),
                "profile": [{"cohort": c, "rating_bin": r, "phase": p, "time_control_class": t, "count": n}
                            for (c, r, p, t), n in sorted(cells.items())],
                "historical_profile": [{"cohort": c, "rating_bin": r, "phase": p, "count": n}
                                       for (c, r, p), n in sorted(historical_cells.items())],
                "known_human_profile": [{"cohort": c, "rating_bin": r, "phase": p, "time_control_class": t, "count": n}
                                        for (c, r, p, t), n in sorted(known_human_cells.items())],
                "limitations": ["Preserves historical rows; canonical duplicates are labelled, not deleted.",
                                "Matching covers the complete supplied files, not archives that were not supplied.",
                                "Missing histories, clocks, time controls and bot status remain unknown.",
                                "Historical game aliases are retained; recovered identities use source game URLs.",
                                "Source PGN ratings replace historical FEN-join mismatches, with original ratings retained per row.",
                                "Position counts are not independent sample sizes; analyses must group by game and canonical position."]}
    atomic_json(manifest_path, manifest, pretty=True)
    return manifest


def audit_legacy_claims(black_path, output, root=ROOT):
    """Reproducible aggregate contamination audit without exporting test answers."""
    concepts = json.loads((root / "webapp/concepts.json").read_text())
    study = {item["fen"] for concept in concepts for item in concept["study"]}
    drill = {item["fen"] for concept in concepts for item in concept["drill"]}
    research = set()

    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get("fen"), str):
                research.add(value["fen"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(json.loads((root / "webapp/research_examples.json").read_text()))
    counts = defaultdict(Counter)
    bot_games = defaultdict(set)
    found_rates = defaultdict(Counter)
    legacy_found_rates = defaultdict(Counter)
    source_counts = defaultdict(Counter)
    for line in black_path.open():
        row = json.loads(line)
        if not row.get("legacy_game_id"):
            continue
        status = "unknown" if row["contains_bot"] is None else "bot" if row["contains_bot"] else "human"
        source_cell = source_counts[(row["rating_bin"], status)]
        source_cell["positions"] += 1
        source_cell["rating_corrected"] += row.get("ratings_corrected_from_source") is True
        groups = ["historical"]
        if row["historical"]["machine_unique"]:
            groups.append("selected_5155")
            cell = found_rates[(row["rating_bin"], status)]
            cell["selected"] += 1
            cell["found"] += row["played_move"] == row["historical"]["engine_best"]
            elo = row["mover_elo"]
            legacy_band = "<=2000" if elo <= 2000 else "(2000,2200]" if elo <= 2200 else "(2200,2400]" if elo <= 2400 else "(2400,2600]" if elo <= 2600 else "(2600,2800]" if elo <= 2800 else ">2800"
            legacy_cell = legacy_found_rates[(legacy_band, status)]
            legacy_cell["selected"] += 1
            legacy_cell["found"] += row["played_move"] == row["historical"]["engine_best"]
        if row["fen"] in study | drill:
            groups.append("public_trainer")
        if row["fen"] in study:
            groups.append("public_study")
        if row["fen"] in drill:
            groups.append("public_drill")
        if row["fen"] in research:
            groups.append("research_examples")
        for group in groups:
            c = counts[group]
            c["rows"] += 1
            c["known_bot_game"] += row.get("contains_bot") is True
            c["known_bot_mover"] += row.get("mover_is_bot") is True
            c["known_bot_opponent"] += row.get("opponent_is_bot") is True
            c["known_human_game"] += row.get("contains_bot") is False
            c["source_unknown"] += row.get("contains_bot") is None
            c["rating_corrected"] += row.get("ratings_corrected_from_source") is True
            if row.get("contains_bot") is True:
                bot_games[group].add(row["game_id"])
    result = {group: {**dict(c), "source_games_with_bots": len(bot_games[group])} for group, c in counts.items()}
    result["selected_find_rate_by_source"] = [
        {"rating_bin": band, "source_status": status, **dict(c),
         "exact_historical_best_rate": c["found"] / c["selected"]}
        for (band, status), c in sorted(found_rates.items())]
    result["selected_find_rate_legacy_band_boundaries"] = [
        {"rating_bin": band, "source_status": status, **dict(c),
         "exact_historical_best_rate": c["found"] / c["selected"]}
        for (band, status), c in sorted(legacy_found_rates.items())]
    result["historical_source_counts_by_rating_bin"] = [
        {"rating_bin": band, "source_status": status, **dict(c)}
        for (band, status), c in sorted(source_counts.items())]
    result["input_sha256"] = {"black.jsonl": file_sha256(black_path),
                              "concepts.json": file_sha256(root / "webapp/concepts.json"),
                              "research_examples.json": file_sha256(root / "webapp/research_examples.json")}
    atomic_json(output, result, pretty=True)
    compact = {"historical": result["historical"], "selected_5155": result["selected_5155"],
               "by_v3_rating_bin": result["selected_find_rate_by_source"],
               "by_legacy_rating_bin": result["selected_find_rate_legacy_band_boundaries"],
               "historical_source_counts_by_rating_bin": result["historical_source_counts_by_rating_bin"],
               "input_sha256": result["input_sha256"],
               "limitations": ["Exact agreement with historical engine choice in a selected corpus, not move quality or population calibration.",
                               "Human means recovered PGN without either BOT title; unknown sources remain separate.",
                               "Version-3 bands include their lower bound; legacy reporting bands include their upper bound.",
                               "Source PGN ratings are used when recovered; corrected original values remain in private row metadata."]}
    atomic_json(output.parent / "legacy_found_rate_by_source.json", compact, pretty=True)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", action="append", type=Path)
    ap.add_argument("--cache", type=Path, default=ROOT / "data/mining_v3/recovery_cache.json")
    ap.add_argument("--reuse-cache", action="store_true")
    ap.add_argument("--extend-cache", action="store_true", help="Scan only --archive inputs and merge with the existing recovery cache")
    ap.add_argument("--output", type=Path, default=ROOT / "data/mining_v3/black.jsonl")
    ap.add_argument("--manifest", type=Path, default=ROOT / "data/mining_v3/black_manifest.json")
    args = ap.parse_args()
    master_path, pilot_path = ROOT / "results/master_all.csv", ROOT / "data/mining_v2/positions.jsonl"
    rows = list(csv.DictReader(master_path.open()))
    pilot = [json.loads(line) for line in pilot_path.open()]
    paths = args.archive or sorted((ROOT / "data").glob("elite_*.zip")) + [ROOT / "data/mining_v2/club_eligible_games.pgn"]
    if args.reuse_cache and args.extend_cache:
        ap.error("Use either --reuse-cache or --extend-cache")
    if args.extend_cache:
        if not args.archive:
            ap.error("--extend-cache requires at least one --archive")
        previous = json.loads(args.cache.read_text())
        addition = scan_archives(rows, paths, args.cache.with_suffix(".addition.json"))
        cache = extend_cache(previous, addition)
        atomic_json(args.cache, cache)
    else:
        cache = json.loads(args.cache.read_text()) if args.reuse_cache else scan_archives(rows, paths, args.cache)
    manifest = write_corpus(rows, pilot, cache, args.output, args.manifest, master_path, pilot_path)
    audit_legacy_claims(args.output, args.output.parent / "legacy_contamination_audit.json")
    print(json.dumps({"output": str(args.output), "counts": manifest["counts"], "sha256": manifest["output_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
