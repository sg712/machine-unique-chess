"""Build a reproducible, side-balanced pilot corpus from local elite PGN zips.

This is a stratified sample of bounded archive prefixes, not a representative
sample of chess. Historical CSVs and the public trainer are never rewritten.
Run with the research Python environment; defaults produce 2,000 positions.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import ssl
import urllib.request
import zipfile

import chess
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260908
SPLITS = {"train": 0.6, "validation": 0.2, "test": 0.2}
PHASES = ("opening", "middlegame", "endgame")
RATING_BINS = ("under_2400", "2400_2599", "2600_2799", "2800_plus")
CLUB_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2026-06.pgn.zst"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_fen(fen: str) -> str:
    """Ignore move counters and non-legal en-passant targets, retain move rights."""
    return " ".join(chess.Board(fen).fen(en_passant="legal").split()[:4])


def split_for_game(game_id: str, seed: int = SEED) -> str:
    # Assign before inspecting or selecting positions. Integer boundaries avoid
    # platform-dependent floating point decisions.
    bucket = int(digest(f"{seed}:split:{game_id}")[:16], 16) % 10000
    return "train" if bucket < 6000 else "validation" if bucket < 8000 else "test"


def legacy_sampled_plies(game: chess.pgn.Game, every: int = 4,
                         min_ply: int = 14, max_ply: int = 70,
                         white_side: bool | None = None,
                         seed: int = SEED) -> set[int]:
    """Sample one move per block without the old even-ply/Black-only aliasing.

    A seeded offset selects the first side, then full blocks alternate sides.
    Side-specific sampling chooses only that side within each block. Existing
    saved CSVs are unaffected; this helper changes future legacy-script runs.
    """
    if every < 1:
        raise ValueError("every must be positive")
    moves = list(game.mainline_moves())
    key = digest(f"{seed}:{game.headers.get('LichessURL', game.headers.get('Site', ''))}:"
                 + " ".join(m.uci() for m in moves))
    first_side = int(key[:2], 16) % 2 == 0
    first_turn = game.board().turn
    selected = set()
    for block, start in enumerate(range(min_ply, min(max_ply, len(moves)) + 1, every)):
        choices = list(range(start, min(start + every, max_ply + 1, len(moves) + 1)))
        side = white_side if white_side is not None else first_side ^ bool(block % 2)
        matching = [p for p in choices if (first_turn ^ bool((p - 1) % 2)) == side]
        if not matching and white_side is not None:
            continue
        pool = matching or choices
        selected.add(pool[int(digest(f"{key}:{block}")[:8], 16) % len(pool)])
    return selected


def rating_bin(elo: int) -> str:
    return RATING_BINS[0 if elo < 2400 else 1 if elo < 2600 else 2 if elo < 2800 else 3]


def phase_of(board: chess.Board, ply: int) -> str:
    material = sum(len(board.pieces(piece, color)) * value
                   for color in chess.COLORS
                   for piece, value in ((chess.KNIGHT, 3), (chess.BISHOP, 3),
                                        (chess.ROOK, 5), (chess.QUEEN, 9)))
    return "endgame" if material <= 20 else "opening" if ply <= 20 else "middlegame"


def game_identity(game: chess.pgn.Game, archive: str, member: str, index: int) -> str:
    for field in ("LichessURL", "Site"):
        link = game.headers.get(field, "")
        m = re.search(r"lichess\.org/([A-Za-z0-9]{8})(?:/|$)", link)
        if m:
            return m.group(1)
    # A game-content identity also deduplicates a game copied between archives.
    content = json.dumps(dict(game.headers), sort_keys=True) + " " + " ".join(
        move.uci() for move in game.mainline_moves())
    return "pgn-" + digest(content)[:24]


def public_exclusions(root: Path = ROOT) -> tuple[set[str], set[str], dict]:
    fens, games = set(), set()
    inputs = {}

    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get("fen"), str):
                fens.add(canonical_fen(value["fen"]))
                if value.get("game_id"):
                    games.add(str(value["game_id"]))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for rel in ("webapp/concepts.json", "webapp/research_examples.json"):
        p = root / rel
        if p.exists():
            visit(json.loads(p.read_text()))
            inputs[rel] = file_sha256(p)
    master = root / "results/master_all.csv"
    recovered = 0
    if master.exists():
        inputs["results/master_all.csv"] = file_sha256(master)
        with master.open(newline="") as f:
            for row in csv.DictReader(f):
                if canonical_fen(row["fen"]) in fens and row.get("game_id"):
                    games.add(row["game_id"])
                    recovered += 1
    return fens, games, {"input_sha256": inputs, "canonical_positions": len(fens),
                         "game_ids": len(games), "matching_master_rows": recovered}


def game_candidates(game: chess.pgn.Game, source: dict, *, seed: int = SEED,
                    min_ply: int = 14, max_ply: int = 100,
                    excluded_fens: set[str] | None = None,
                    excluded_games: set[str] | None = None) -> tuple[list[dict], str | None]:
    """Keep one hash-reservoir candidate for each side/phase in a whole game."""
    if game.errors:
        return [], "parse_error"
    if game.headers.get("Variant", "Standard") not in ("Standard", "Chess"):
        return [], "nonstandard"
    if any(game.headers.get(f"{side}Title") == "BOT" for side in ("White", "Black")):
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
    if gid in (excluded_games or set()):
        return [], "public_game_id"
    board = game.board()
    if not board.is_valid() or type(board) is not chess.Board:
        return [], "invalid_board"
    initial_fen = board.fen()
    history, states = [], [initial_fen]
    clocks = {chess.WHITE: None, chess.BLACK: None}
    candidates = {}
    common_source = {**source, "date": game.headers.get("UTCDate", game.headers.get("Date")),
                     "utc_time": game.headers.get("UTCTime"),
                     "url": game.headers.get("LichessURL", game.headers.get("Site")),
                     "event": game.headers.get("Event"), "result": game.headers.get("Result"),
                     "termination": game.headers.get("Termination")}
    split = split_for_game(gid, seed)
    for ply, node in enumerate(game.mainline(), 1):
        # Scan the entire game for an existing public position, including after
        # the sampling window; otherwise another ply could leak that game.
        fen = board.fen()
        if canonical_fen(fen) in (excluded_fens or set()):
            return [], "public_position_in_game"
        if node.move not in board.legal_moves:
            return [], "illegal_move"
        if min_ply <= ply <= max_ply and not board.is_game_over():
            side = "white" if board.turn else "black"
            phase = phase_of(board, ply)
            rank = digest(f"{seed}:candidate:{gid}:{ply}")
            key = (side, phase)
            if key not in candidates or rank < candidates[key][0]:
                row = {"id": f"v2-{gid}-{ply}", "fen": fen, "game_id": gid,
                       "split": split, "source": common_source, "cohort": source.get("cohort", "elite"),
                       "initial_fen": initial_fen, "history_uci": history.copy(),
                       "history_fens": states[-8:], "played_move": node.move.uci(),
                       "white_elo": we, "black_elo": be,
                       "mover_elo": we if board.turn else be,
                       "rating_bin": rating_bin(we if board.turn else be),
                       "side_to_move": side, "time_control": game.headers.get("TimeControl"),
                       "clock_seconds_before": clocks[board.turn],
                       "opponent_clock_seconds": clocks[not board.turn],
                       "clock_seconds_after_played_move": node.clock(),
                       "clock_source": "pgn_clk_annotation_or_null",
                       "phase": phase, "ply": ply}
                candidates[key] = (rank, row)
        mover = board.turn
        # An absent clock on the mover's latest turn must not reuse an older
        # annotation as though it described the current position.
        clocks[mover] = node.clock()
        history.append(node.move.uci())
        board.push(node.move)
        states.append(board.fen())
    if canonical_fen(board.fen()) in (excluded_fens or set()):
        return [], "public_position_in_game"
    return [entry[1] for entry in candidates.values()], None


def select_balanced(candidates: list[dict], count: int, seed: int = SEED,
                    max_per_game: int = 2) -> tuple[list[dict], dict]:
    if count % 10:
        raise ValueError("count must be divisible by ten for exact side/split balance")
    pools = defaultdict(list)
    for row in candidates:
        pools[(row["split"], row["side_to_move"], row["phase"], row["rating_bin"])].append(row)
    for pool in pools.values():
        pool.sort(key=lambda r: digest(f"{seed}:selection:{r['id']}"))
    selected, fens, ids = [], set(), set()
    games, realized, skips = Counter(), Counter(), Counter()
    targets = {}

    def take(row, key):
        canon = canonical_fen(row["fen"])
        if row["id"] in ids:
            return False
        if games[row["game_id"]] >= max_per_game:
            skips["game_cap"] += 1
            return False
        if canon in fens:
            skips["duplicate_canonical_position"] += 1
            return False
        selected.append(row)
        fens.add(canon)
        ids.add(row["id"])
        games[row["game_id"]] += 1
        realized[key] += 1
        return True

    for split, fraction in SPLITS.items():
        for side in ("white", "black"):
            goal = round(count * fraction / 2)
            keys = [(split, side, phase, rating) for phase in PHASES for rating in RATING_BINS]
            # Give every phase/rating cell a nearly equal target. Smaller pools
            # go first so common cells cannot consume all games from rare ones.
            for i, key in enumerate(keys):
                targets[key] = goal // len(keys) + int(i < goal % len(keys))
            for key in sorted(keys, key=lambda k: (len(pools[k]), k)):
                for row in pools[key]:
                    if realized[key] >= targets[key]:
                        break
                    take(row, key)
            # Underfilled cells are redistributed within the same side/split.
            # Each pass prefers the currently least represented cell.
            cursors = Counter()
            while sum(realized[key] for key in keys) < goal:
                progress = False
                for key in sorted(keys, key=lambda k: (realized[k], k)):
                    pool = pools[key]
                    while cursors[key] < len(pool):
                        row = pool[cursors[key]]
                        cursors[key] += 1
                        if take(row, key):
                            progress = True
                            break
                    if sum(realized[k] for k in keys) >= goal:
                        break
                if not progress:
                    raise ValueError(f"insufficient eligible candidates for {split}/{side}; "
                                     f"got {sum(realized[k] for k in keys)} of {goal}")
    selected.sort(key=lambda r: (list(SPLITS).index(r["split"]), r["game_id"], r["ply"]))
    return selected, {"cell_targets": {"/".join(k): v for k, v in targets.items()},
                      "cell_counts": {"/".join(k): v for k, v in realized.items()},
                      "selection_skip_events": dict(skips)}


def validate_rows(rows: list[dict]) -> dict:
    game_splits, canonical_splits = {}, {}
    for row in rows:
        board = chess.Board(row["initial_fen"])
        states = [board.fen()]
        for uci in row["history_uci"]:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                raise ValueError(f"illegal history: {row['id']}")
            board.push(move)
            states.append(board.fen())
        if board.fen() != row["fen"] or states[-8:] != row["history_fens"]:
            raise ValueError(f"history/FEN mismatch: {row['id']}")
        if len(row["history_uci"]) != row["ply"] - 1:
            raise ValueError(f"ply/history mismatch: {row['id']}")
        if chess.Move.from_uci(row["played_move"]) not in board.legal_moves:
            raise ValueError(f"illegal played move: {row['id']}")
        side = "white" if board.turn else "black"
        if row["side_to_move"] != side or row["mover_elo"] != row[f"{side}_elo"]:
            raise ValueError(f"mover metadata mismatch: {row['id']}")
        gid, split, canon = row["game_id"], row["split"], canonical_fen(row["fen"])
        if gid in game_splits and game_splits[gid] != split:
            raise ValueError("game leaks across splits")
        if canon in canonical_splits:
            raise ValueError("duplicate canonical position")
        game_splits[gid] = split
        canonical_splits[canon] = split
    return {"positions": len(rows), "games": len(game_splits), "history_replay_valid": True,
            "unique_canonical_positions": len(canonical_splits),
            "game_disjoint_splits": True, "player_disjoint_splits": False}


def club_candidates(args, excluded_fens, excluded_games, seen_ids):
    """Read a bounded official compressed prefix, retaining exact source PGNs."""
    import certifi
    import pyzstd
    req = urllib.request.Request(args.club_url, headers={"User-Agent": "machine-unique-chess-research/2"})
    compressed_hash = hashlib.sha256()
    decompressor = pyzstd.EndlessZstdDecompressor()
    info = {"archive": args.club_url.rsplit("/", 1)[-1], "url": args.club_url,
            "cohort": "club", "compressed_bytes_read": 0, "games_scanned": 0,
            "eligible_games": 0, "candidate_positions": 0,
            "compressed_byte_limit": args.club_max_compressed_mb << 20,
            "game_scan_limit": args.club_games_limit,
            "eligible_game_limit": args.club_eligible_target,
            "filters": {"min_both_elo": 1800, "min_base_seconds": 600,
                        "exclude_abandoned": True, "exclude_bot_titles": True}}
    rows, skipped, buffer, stop = [], Counter(), "", False
    # Saved selected-eligible PGNs make the records inspectable without another
    # network request; this is not represented as the entire downloaded prefix.
    args.output.mkdir(parents=True, exist_ok=True)
    preserved = args.output / "club_eligible_games.pgn"
    with urllib.request.urlopen(req, timeout=45,
                                context=ssl.create_default_context(cafile=certifi.where())) as response, preserved.open("w") as saved:
        info["http_etag"] = response.headers.get("ETag")
        info["http_last_modified"] = response.headers.get("Last-Modified")
        while info["compressed_bytes_read"] < info["compressed_byte_limit"] and not stop:
            raw = response.read(min(1 << 20, info["compressed_byte_limit"] - info["compressed_bytes_read"]))
            if not raw:
                info["stop_reason"] = "end_of_stream"
                break
            compressed_hash.update(raw)
            info["compressed_bytes_read"] += len(raw)
            buffer += decompressor.decompress(raw).decode("utf-8", errors="strict")
            while True:
                boundary = buffer.find("\n\n[Event ", 1)
                if boundary < 0:
                    break
                text, buffer = buffer[:boundary], buffer[boundary + 2:]
                info["games_scanned"] += 1
                headers = dict(re.findall(r'^\[(\w+) "([^"\n]*)"\]', text, re.MULTILINE))
                try:
                    qualifies = (min(int(headers.get("WhiteElo", 0)), int(headers.get("BlackElo", 0))) >= 1800
                                 and int(headers.get("TimeControl", "0+0").split("+")[0]) >= 600)
                except ValueError:
                    qualifies = False
                if qualifies:
                    game = chess.pgn.read_game(io.StringIO(text))
                    if game:
                        gid = game_identity(game, info["archive"], "compressed-prefix", info["games_scanned"])
                        source = {"archive": info["archive"], "cohort": "club", "url": args.club_url,
                                  "member": "compressed-prefix", "game_index": info["games_scanned"],
                                  "pgn_sha256": digest(text)}
                        if gid in seen_ids:
                            skipped["duplicate_game"] += 1
                        else:
                            seen_ids.add(gid)
                            items, reason = game_candidates(game, source, seed=args.seed,
                                                            min_ply=args.min_ply, max_ply=args.max_ply,
                                                            excluded_fens=excluded_fens,
                                                            excluded_games=excluded_games)
                            if reason:
                                skipped[reason] += 1
                            elif items:
                                rows.extend(items)
                                saved.write(text + "\n\n")
                                info["eligible_games"] += 1
                                info["candidate_positions"] += len(items)
                                info.setdefault("first_eligible_date", items[0]["source"]["date"])
                                info["last_eligible_date"] = items[0]["source"]["date"]
                else:
                    skipped["club_rating_or_time_filter"] += 1
                if info["eligible_games"] >= args.club_eligible_target:
                    info["stop_reason"] = "eligible_game_limit"
                    stop = True
                elif info["games_scanned"] >= args.club_games_limit:
                    info["stop_reason"] = "game_scan_limit"
                    stop = True
                if stop:
                    break
            print(f"club stream: {info['compressed_bytes_read'] // (1 << 20)} MiB, "
                  f"{info['games_scanned']} games, {info['eligible_games']} eligible", flush=True)
    info.setdefault("stop_reason", "compressed_byte_limit")
    info["compressed_prefix_sha256"] = compressed_hash.hexdigest()
    info["eligible_pgn_file"] = preserved.name
    info["eligible_pgn_sha256"] = file_sha256(preserved)
    for row in rows:
        row["source"]["sha256"] = info["compressed_prefix_sha256"]
        row["source"]["sha256_scope"] = "downloaded_compressed_prefix"
    return rows, info, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archives", nargs="+", type=Path,
                    default=[ROOT / f"data/elite_2025-{m}.zip" for m in ("09", "10", "11")])
    ap.add_argument("--output", type=Path, default=ROOT / "data/mining_v2")
    ap.add_argument("--count", type=int, default=2000)
    ap.add_argument("--games-per-archive", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--min-ply", type=int, default=14)
    ap.add_argument("--max-ply", type=int, default=100)
    ap.add_argument("--club-url", default=CLUB_URL)
    ap.add_argument("--club-max-compressed-mb", type=int, default=64)
    ap.add_argument("--club-games-limit", type=int, default=100000)
    ap.add_argument("--club-eligible-target", type=int, default=2000)
    ap.add_argument("--elite-only", action="store_true", help="Do not stream the club cohort")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    out = args.output / "positions.jsonl"
    if out.exists() and not args.force:
        raise SystemExit(f"{out} exists; choose another output or explicitly use --force")
    excluded_fens, excluded_games, exclusions = public_exclusions()
    candidates, sources, skipped, seen_ids = [], [], Counter(), set()
    for archive in args.archives:
        archive_hash = file_sha256(archive)
        info = {"archive": archive.name, "sha256": archive_hash, "cohort": "elite",
                "bytes": archive.stat().st_size, "games_scanned": 0,
                "eligible_games": 0, "candidate_positions": 0, "members": []}
        with zipfile.ZipFile(archive) as zf:
            for member in sorted(n for n in zf.namelist() if n.endswith(".pgn")):
                info["members"].append(member)
                with zf.open(member) as raw:
                    stream = io.TextIOWrapper(raw, encoding="utf-8", errors="strict")
                    while info["games_scanned"] < args.games_per_archive:
                        game = chess.pgn.read_game(stream)
                        if game is None:
                            break
                        info["games_scanned"] += 1
                        source = {"archive": archive.name, "sha256": archive_hash, "cohort": "elite",
                                  "member": member, "game_index": info["games_scanned"]}
                        gid = game_identity(game, archive.name, member, info["games_scanned"])
                        if gid in seen_ids:
                            skipped["duplicate_game"] += 1
                            continue
                        seen_ids.add(gid)
                        rows, reason = game_candidates(game, source, seed=args.seed,
                                                      min_ply=args.min_ply, max_ply=args.max_ply,
                                                      excluded_fens=excluded_fens,
                                                      excluded_games=excluded_games)
                        if reason:
                            skipped[reason] += 1
                        elif not rows:
                            skipped["no_positions_in_window"] += 1
                        else:
                            candidates.extend(rows)
                            info["eligible_games"] += 1
                            info["candidate_positions"] += len(rows)
                        if info["games_scanned"] % 1000 == 0:
                            print(f"{archive.name}: {info['games_scanned']} games, "
                                  f"{info['candidate_positions']} candidates", flush=True)
                if info["games_scanned"] >= args.games_per_archive:
                    break
        sources.append(info)
    if args.elite_only:
        rows, selection = select_balanced(candidates, args.count, args.seed)
    else:
        club_rows, club_info, club_skipped = club_candidates(args, excluded_fens, excluded_games, seen_ids)
        sources.append(club_info)
        skipped.update(club_skipped)
        elite_rows, elite_selection = select_balanced(candidates, args.count // 2, args.seed)
        elite_canonical = {canonical_fen(row["fen"]) for row in elite_rows}
        before = len(club_rows)
        club_rows = [row for row in club_rows if canonical_fen(row["fen"]) not in elite_canonical]
        selection_cross_cohort_excluded = before - len(club_rows)
        selected_club, club_selection = select_balanced(club_rows, args.count // 2, args.seed)
        rows = elite_rows + selected_club
        selection = {"elite": elite_selection, "club": club_selection,
                     "club_candidates_excluded_for_elite_canonical_overlap": selection_cross_cohort_excluded}
        candidates.extend(club_rows)
    validation = validate_rows(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    tmp.replace(out)
    counts = {name: dict(Counter(str(row[name]) for row in rows))
              for name in ("split", "side_to_move", "phase", "rating_bin", "time_control", "cohort")}
    counts["split_side"] = dict(Counter(f"{r['split']}/{r['side_to_move']}" for r in rows))
    counts["archive"] = dict(Counter(r["source"]["archive"] for r in rows))
    manifest = {"schema_version": 2, "created_at": datetime.now(timezone.utc).isoformat(),
                "seed": args.seed, "positions_sha256": file_sha256(out),
                "script_sha256": file_sha256(Path(__file__)), "sources": sources,
                "settings": {"count": args.count, "games_per_archive": args.games_per_archive,
                             "min_ply": args.min_ply, "max_ply": args.max_ply,
                             "max_positions_per_game": 2, "split_ratios": SPLITS},
                "public_exclusions": exclusions, "excluded_games_by_reason": dict(skipped),
                "candidate_positions": len(candidates), "selection": selection,
                "counts": counts, "validation": validation,
                "clocks": {"before_available": sum(r["clock_seconds_before"] is not None for r in rows),
                           "opponent_available": sum(r["opponent_clock_seconds"] is not None for r in rows),
                           "meaning": "Latest PGN clock annotation for each side; absent clocks are null, never inferred from time control."},
                "method": "Hash-reservoir one candidate per side and phase per game; near-equal phase/rating targets within exact side/split quotas in each cohort, at most two selected positions per game; canonical duplicates rejected within cohorts and final cross-cohort validation requires global uniqueness.",
                "phase_definition": "Endgame: total non-pawn, non-king material <=20 pawn units (N/B=3,R=5,Q=9); otherwise opening through target ply 20, middlegame thereafter.",
                "history_definition": "history_uci includes all moves before target; history_fens is last eight actual chronological states ending at fen, with no padding; ply is one-based next move index from initial_fen.",
                "limitations": ["Bounded first games in each monthly elite archive; not a random sample of the full archive or chess population.",
                                "The 50/50 club/elite mixture is constructed; archive prefixes are ordered in time and neither cohort represents its full source population.",
                                "Splits separate games and selected canonical positions, not players or opening families.",
                                "Public game exclusions combine stored/recovered IDs with scanning all game states for public canonical positions; unknown provenance outside scanned archives cannot be guaranteed.",
                                "Sampling changes do not reweight or repair historical mining results."]}
    (args.output / "sampling_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(out), "validation": validation, "counts": counts,
                      "excluded_games": dict(skipped), "clocks": manifest["clocks"]}, indent=2))


if __name__ == "__main__":
    main()
