"""Exp 02a — build a positions dataset from real human games.

Streams the lichess open database (.pgn.zst) without downloading the whole month,
keeps rapid/classical games where both players are >= --min-elo, samples mid-game
positions, and writes data/positions.csv with (game_id, ply, fen, played_move, elos).

Usage: python experiments/02_build_dataset.py --games 3000 --min-elo 1800
"""
import argparse
import csv
import io
import pathlib
import urllib.request

import chess.pgn
import pyzstd

ROOT = pathlib.Path(__file__).resolve().parents[1]
MONTHS = ["2026-06", "2026-05", "2026-04"]  # try newest first
URL = "https://database.lichess.org/standard/lichess_db_standard_rated_{m}.pgn.zst"


def stream_games(month: str, want: int, min_elo: int):
    """Yield chess.pgn.Game objects parsed from a streaming decompress of the archive."""
    req = urllib.request.Request(URL.format(m=month), headers={"User-Agent": "unnamed-concepts research"})
    resp = urllib.request.urlopen(req, timeout=60)
    dctx = pyzstd.EndlessZstdDecompressor()
    buf, kept, seen = "", 0, 0
    while kept < want:
        chunk = resp.read(1 << 20)
        if not chunk:
            break
        buf += dctx.decompress(chunk).decode("utf-8", errors="replace")
        # split on game boundaries, keep the tail fragment in the buffer
        while True:
            cut = buf.find("\n\n[Event ", 1)
            if cut == -1 or kept >= want:
                break
            gtext, buf = buf[:cut], buf[cut + 2:]
            seen += 1
            game = chess.pgn.read_game(io.StringIO(gtext))
            if game is None:
                continue
            h = game.headers
            try:
                we, be = int(h.get("WhiteElo", 0)), int(h.get("BlackElo", 0))
                base = int(h.get("TimeControl", "0+0").split("+")[0])
            except ValueError:
                continue
            if we >= min_elo and be >= min_elo and base >= 600 and h.get("Termination") != "Abandoned":
                kept += 1
                yield game
    resp.close()
    print(f"[{month}] scanned {seen} games, kept {kept}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=3000)
    ap.add_argument("--min-elo", type=int, default=1800)
    ap.add_argument("--every", type=int, default=4, help="sample every Nth ply")
    ap.add_argument("--min-ply", type=int, default=14)
    ap.add_argument("--max-ply", type=int, default=70)
    args = ap.parse_args()

    out = ROOT / "data"
    out.mkdir(exist_ok=True)
    rows, n_games = 0, 0
    with open(out / "positions.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["game_id", "ply", "fen", "played_move", "white_elo", "black_elo"])
        got = False
        for month in MONTHS:
            try:
                for game in stream_games(month, args.games, args.min_elo):
                    n_games += 1
                    gid = game.headers.get("Site", f"g{n_games}").rsplit("/", 1)[-1]
                    we, be = game.headers.get("WhiteElo"), game.headers.get("BlackElo")
                    board = game.board()
                    for ply, move in enumerate(game.mainline_moves(), start=1):
                        if args.min_ply <= ply <= args.max_ply and ply % args.every == 0:
                            w.writerow([gid, ply, board.fen(), move.uci(), we, be])
                            rows += 1
                        board.push(move)
                got = True
                break
            except Exception as e:  # try an older month on 404 etc.
                print(f"[{month}] failed: {e}")
        if not got:
            raise SystemExit("no month worked")
    print(f"wrote {rows} positions from {n_games} games -> {out/'positions.csv'}")


if __name__ == "__main__":
    main()
