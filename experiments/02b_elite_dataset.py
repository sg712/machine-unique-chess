"""Exp 02b — positions dataset from the Lichess Elite Database (2500+ vs 2300+).

Downloads a monthly elite zip (real games by lichess 2500+ players — FM/IM/GM
territory), samples mid-game positions exactly like exp 02, writes
data/positions_elite.csv. Feed to exp 03 with --input/--output for the
GM-level frontier validation.
"""
import csv
import io
import pathlib
import urllib.request
import zipfile

import chess.pgn

ROOT = pathlib.Path(__file__).resolve().parents[1]
MONTHS = ["2025-11", "2024-12", "2024-11"]
URL = "https://database.nikonoel.fr/lichess_elite_{m}.zip"


def main(want_games: int = 2500, every: int = 4, min_ply: int = 14, max_ply: int = 70) -> None:
    out = ROOT / "data"
    out.mkdir(exist_ok=True)
    zpath = None
    for m in MONTHS:
        try:
            dest = out / f"elite_{m}.zip"
            if not dest.exists():
                print(f"downloading {URL.format(m=m)} ...")
                req = urllib.request.Request(URL.format(m=m), headers={"User-Agent": "unnamed-concepts research"})
                with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as fh:
                    while chunk := r.read(1 << 20):
                        fh.write(chunk)
            zpath = dest
            break
        except Exception as e:
            print(f"{m} failed: {e}")
    if zpath is None:
        raise SystemExit("no elite month downloadable")

    rows, n_games = 0, 0
    with zipfile.ZipFile(zpath) as zf, open(out / "positions_elite.csv", "w", newline="") as ofh:
        w = csv.writer(ofh)
        w.writerow(["game_id", "ply", "fen", "played_move", "white_elo", "black_elo"])
        names = [n for n in zf.namelist() if n.endswith(".pgn")]
        print(f"{zpath.name}: {names}")
        for name in names:
            with zf.open(name) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                while n_games < want_games:
                    game = chess.pgn.read_game(text)
                    if game is None:
                        break
                    h = game.headers
                    try:
                        we, be = int(h.get("WhiteElo", 0)), int(h.get("BlackElo", 0))
                    except ValueError:
                        continue
                    n_games += 1
                    gid = h.get("Site", f"e{n_games}").rsplit("/", 1)[-1]
                    board = game.board()
                    for ply, move in enumerate(game.mainline_moves(), start=1):
                        if min_ply <= ply <= max_ply and ply % every == 0:
                            w.writerow([gid, ply, board.fen(), move.uci(), we, be])
                            rows += 1
                        board.push(move)
            if n_games >= want_games:
                break
    print(f"wrote {rows} positions from {n_games} elite games -> {out/'positions_elite.csv'}")


if __name__ == "__main__":
    main()
