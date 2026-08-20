"""Exp 25 — extend the band ladder to Lichess 2800+.

These are Lichess ratings, whose scale runs to ~3200 — "2600+" lumped 2650s with
3000s, and splitting it showed why that mattered: find-rate on machine-unique
moves jumps from 27.3% (2600-2800) to 61.8% (2800+). This samples enough new
positions to give both top bands the same ~20k footing as the rest.

Design change vs exp 24: at 2800+ requiring BOTH players in band starves the
sampler, so a game qualifies if EITHER player is in band — and only the plies
where the in-band player is to move are kept. mover_elo lands in-band by
construction; the opponent's plies are simply not sampled.

Output: data/positions_band_elite_top.csv
"""
import csv
import io
import pathlib
import re
import urllib.request
import zipfile

import chess.pgn
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
MONTHS = ["2025-09", "2025-08", "2025-07", "2025-06"]
URL = "https://database.nikonoel.fr/lichess_elite_{m}.zip"
EVERY, MIN_PLY, MAX_PLY = 4, 14, 70
RX = {k: re.compile(rf'\[{k} "([^"]*)"\]') for k in ("WhiteElo", "BlackElo")}

# band -> [lo, hi, positions wanted]
QUOTAS = {"2600-2800": [2600, 2799, 6500], "2800+": [2800, 9999, 13700]}


def hdr(gtext, key):
    m = RX[key].search(gtext)
    return m.group(1) if m else ""


def game_blocks(chunks):
    buf = ""
    for chunk in chunks:
        buf += chunk
        while True:
            cut = buf.find("\n\n[Event ", 1)
            if cut == -1:
                break
            gtext, buf = buf[:cut], buf[cut + 2:]
            yield gtext
    if buf.strip():
        yield buf


def zip_chunks(month):
    dest = ROOT / "data" / f"elite_{month}.zip"
    if not dest.exists():
        print(f"downloading {URL.format(m=month)} ...", flush=True)
        req = urllib.request.Request(URL.format(m=month),
                                     headers={"User-Agent": "unnamed-concepts research"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as fh:
            while chunk := r.read(1 << 20):
                fh.write(chunk)
    with zipfile.ZipFile(dest) as zf:
        for name in zf.namelist():
            if name.endswith(".pgn"):
                with zf.open(name) as raw:
                    text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                    while chunk := text.read(1 << 20):
                        yield chunk


def sample_side(gtext, white_side):
    """Rows for plies where the chosen side is to move (ply odd = white)."""
    game = chess.pgn.read_game(io.StringIO(gtext))
    if game is None:
        return []
    rows, board = [], game.board()
    for ply, move in enumerate(game.mainline_moves(), start=1):
        if MIN_PLY <= ply <= MAX_PLY and ply % EVERY == 0 and board.turn == white_side:
            rows.append([ply, board.fen(), move.uci()])
        board.push(move)
    return rows


def main() -> None:
    known_fens = set(pd.read_csv(ROOT / "results" / "master_all.csv", usecols=["fen"]).fen)
    print(f"{len(known_fens)} known fens will be skipped")
    got = {b: 0 for b in QUOTAS}
    out = ROOT / "data" / "positions_band_elite_top.csv"
    n = 0
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["game_id", "ply", "fen", "played_move", "white_elo", "black_elo"])
        for month in MONTHS:
            if all(got[b] >= QUOTAS[b][2] for b in QUOTAS):
                break
            seen = 0
            try:
                for gtext in game_blocks(zip_chunks(month)):
                    seen += 1
                    if seen % 50000 == 0:
                        print(f"[{month}] scanned {seen}, got {got}", flush=True)
                    if all(got[b] >= QUOTAS[b][2] for b in QUOTAS):
                        break
                    try:
                        we, be = int(hdr(gtext, "WhiteElo")), int(hdr(gtext, "BlackElo"))
                    except ValueError:
                        continue
                    # prefer the scarcer band if both players qualify
                    pick = None
                    for b in ("2800+", "2600-2800"):
                        lo, hi, want = QUOTAS[b]
                        if got[b] >= want:
                            continue
                        if lo <= we <= hi:
                            pick, white_side = b, True
                            break
                        if lo <= be <= hi:
                            pick, white_side = b, False
                            break
                    if pick is None:
                        continue
                    rows = [r for r in sample_side(gtext, white_side)
                            if r[1] not in known_fens]
                    if not rows:
                        continue
                    n += 1
                    gid = f"T{month}_{n}"
                    for r in rows:
                        known_fens.add(r[1])
                        w.writerow([gid, *r, we, be])
                    got[pick] += len(rows)
            except Exception as e:
                print(f"[{month}] failed: {e}")
            print(f"[{month}] done: scanned {seen}, got {got}", flush=True)
    print(f"\nfinal: {got} from {n} games")


if __name__ == "__main__":
    main()
