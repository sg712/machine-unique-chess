"""Exp 22 — repair the elite game ids.

Every elite position carries game_id "?" because the Elite Database's Site header
is literally "?", so 02b's `Site`-based id collapsed 2,500 games into one. Every
grouped train/test split since has treated the whole elite corpus as a single
game: no leakage, but one fold owned all of elite and the others none.

The archive parses deterministically, so replaying it in generation order
recovers a stable id per game ("e1", "e2", ...). Positions are matched back by
full FEN string — move counters make cross-game collisions rare, and any fen
seen in two games is dropped from the mapping rather than guessed.

Output: data/elite_game_ids.csv (fen -> game id), and patched
positions_elite*.csv. 09_consolidate applies the mapping on every run.
"""
import csv
import io
import pathlib
import zipfile

import chess.pgn
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
WANT_GAMES, EVERY, MIN_PLY, MAX_PLY = 2500, 4, 14, 70


def main() -> None:
    zpath = ROOT / "data" / "elite_2025-11.zip"
    mapping, dupes = {}, set()
    n_games = 0
    with zipfile.ZipFile(zpath) as zf:
        names = [n for n in zf.namelist() if n.endswith(".pgn")]
        for name in names:
            with zf.open(name) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                while n_games < WANT_GAMES:
                    game = chess.pgn.read_game(text)
                    if game is None:
                        break
                    h = game.headers
                    try:
                        int(h.get("WhiteElo", 0)), int(h.get("BlackElo", 0))
                    except ValueError:
                        continue                      # same skip rule as 02b
                    n_games += 1
                    gid = f"e{n_games}"
                    board = game.board()
                    for ply, move in enumerate(game.mainline_moves(), start=1):
                        if MIN_PLY <= ply <= MAX_PLY and ply % EVERY == 0:
                            fen = board.fen()
                            if fen in mapping and mapping[fen] != gid:
                                dupes.add(fen)
                            else:
                                mapping[fen] = gid
                        board.push(move)
            if n_games >= WANT_GAMES:
                break
    for f in dupes:
        del mapping[f]
    print(f"replayed {n_games} games, {len(mapping)} fens mapped, "
          f"{len(dupes)} ambiguous fens dropped")

    with open(ROOT / "data" / "elite_game_ids.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fen", "game_id"])
        for fen, gid in mapping.items():
            w.writerow([fen, gid])

    for name in ["positions_elite.csv", "positions_elite_remaining.csv"]:
        p = ROOT / "data" / name
        df = pd.read_csv(p)
        fixed = df.fen.map(mapping)
        n_fixed = fixed.notna().sum()
        df["game_id"] = fixed.fillna(df.game_id)
        df.to_csv(p, index=False)
        print(f"{name}: {n_fixed}/{len(df)} game ids repaired")


if __name__ == "__main__":
    main()
