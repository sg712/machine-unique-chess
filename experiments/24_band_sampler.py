"""Exp 24 — band-targeted position sampling, to even out the rating coverage.

The 63k master is lopsided: ~21k positions under 2000 but only ~4.3k in
2200-2400. This samples new games so every reported band reaches ~20k:

    2000-2200  +10.5k   club stream, both players in band
    2200-2400  +15.7k   club stream, both players in band
    2400-2600   +1.8k   elite zip,   both players in band
    2600+       +9.8k   elite zip,   both players >= 2600

"Both players in band" guarantees every sampled position's mover falls in the
band. Filters mirror the original samplers exactly — club: rapid/classical
(base >= 600s), not abandoned; elite: no time-control filter (02b had none).
Sampling grid identical everywhere: plies 14-70, every 4th.

Club games stream from a *different month* than the original download, and any
game_id already in master is skipped — no duplicates. Elite ids are generated
as E{month}_{n}; the Site header is "?" (see exp 22), never used.

Output: data/positions_band_club.csv, data/positions_band_elite.csv
"""
import csv
import io
import pathlib
import re
import urllib.request
import zipfile

import chess.pgn
import pandas as pd
import pyzstd

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLUB_MONTHS = ["2026-07", "2026-05", "2026-04"]      # original club used 2026-06
CLUB_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_{m}.pgn.zst"
ELITE_MONTHS = ["2025-10", "2025-09", "2024-12"]     # original elite used 2025-11
ELITE_URL = "https://database.nikonoel.fr/lichess_elite_{m}.zip"

EVERY, MIN_PLY, MAX_PLY = 4, 14, 70
MAX_CLUB_BYTES = 6 << 30                             # hard cap on the stream
RX = {k: re.compile(rf'\[{k} "([^"]*)"\]') for k in
      ("WhiteElo", "BlackElo", "TimeControl", "Termination", "Site")}

# band -> (lo, hi, games wanted); games ~= rows/12 with ~10% buffer
CLUB_QUOTAS = {"2000-2200": [2000, 2199, 970], "2200-2400": [2200, 2399, 1440]}
ELITE_QUOTAS = {"2400-2600": [2400, 2599, 165], "2600+": [2600, 9999, 900]}


def hdr(gtext, key):
    m = RX[key].search(gtext)
    return m.group(1) if m else ""


def game_blocks(chunks):
    """Split a stream of text chunks into PGN game blocks."""
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


def club_chunks(month):
    req = urllib.request.Request(CLUB_URL.format(m=month),
                                 headers={"User-Agent": "unnamed-concepts research"})
    resp = urllib.request.urlopen(req, timeout=60)
    dctx = pyzstd.EndlessZstdDecompressor()
    read = 0
    while read < MAX_CLUB_BYTES:
        chunk = resp.read(1 << 20)
        if not chunk:
            break
        read += len(chunk)
        yield dctx.decompress(chunk).decode("utf-8", errors="replace")
    resp.close()


def elite_chunks(month):
    dest = ROOT / "data" / f"elite_{month}.zip"
    if not dest.exists():
        print(f"downloading {ELITE_URL.format(m=month)} ...", flush=True)
        req = urllib.request.Request(ELITE_URL.format(m=month),
                                     headers={"User-Agent": "unnamed-concepts research"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as fh:
            while chunk := r.read(1 << 20):
                fh.write(chunk)
    with zipfile.ZipFile(dest) as zf:
        for name in zf.namelist():
            if not name.endswith(".pgn"):
                continue
            with zf.open(name) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                while chunk := text.read(1 << 20):
                    yield chunk


def sample(gtext):
    """Replay one game, return sampled position rows (without game_id)."""
    game = chess.pgn.read_game(io.StringIO(gtext))
    if game is None:
        return []
    rows, board = [], game.board()
    for ply, move in enumerate(game.mainline_moves(), start=1):
        if MIN_PLY <= ply <= MAX_PLY and ply % EVERY == 0:
            rows.append([ply, board.fen(), move.uci()])
        board.push(move)
    return rows


def run(tag, chunks, quotas, known_ids, gid_of, club_rules):
    out = ROOT / "data" / f"positions_band_{tag}.csv"
    counts = {b: 0 for b in quotas}         # games kept per band
    rows_out, seen, n = {b: 0 for b in quotas}, 0, 0
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["game_id", "ply", "fen", "played_move", "white_elo", "black_elo"])
        for gtext in game_blocks(chunks):
            seen += 1
            if seen % 50000 == 0:
                print(f"[{tag}] scanned {seen}, kept {counts}", flush=True)
            if all(counts[b] >= quotas[b][2] for b in quotas):
                break
            try:
                we, be = int(hdr(gtext, "WhiteElo")), int(hdr(gtext, "BlackElo"))
            except ValueError:
                continue
            band = next((b for b, (lo, hi, want) in quotas.items()
                         if counts[b] < want and lo <= we <= hi and lo <= be <= hi), None)
            if band is None:
                continue
            if club_rules:
                try:
                    base = int(hdr(gtext, "TimeControl").split("+")[0])
                except ValueError:
                    continue
                if base < 600 or hdr(gtext, "Termination") == "Abandoned":
                    continue
            n += 1
            gid = gid_of(gtext, n)
            if gid in known_ids:
                continue
            known_ids.add(gid)
            rows = sample(gtext)
            if not rows:
                continue
            counts[band] += 1
            rows_out[band] += len(rows)
            for r in rows:
                w.writerow([gid, *r, we, be])
    print(f"[{tag}] done: scanned {seen} games")
    for b in quotas:
        print(f"  {b}: {counts[b]}/{quotas[b][2]} games, {rows_out[b]} positions")
    return sum(rows_out.values())


def main() -> None:
    known = set(pd.read_csv(ROOT / "results" / "master_all.csv", usecols=["game_id"]).game_id)
    print(f"{len(known)} known game ids will be skipped\n")

    total = 0
    for month in ELITE_MONTHS:
        try:
            total += run("elite", elite_chunks(month), ELITE_QUOTAS, known,
                         lambda g, n, m=month: f"E{m}_{n}", club_rules=False)
            break
        except Exception as e:
            print(f"elite {month} failed: {e}")

    for month in CLUB_MONTHS:
        try:
            total += run("club", club_chunks(month), CLUB_QUOTAS, known,
                         lambda g, n: hdr(g, "Site").rsplit("/", 1)[-1] or f"c{n}",
                         club_rules=True)
            break
        except Exception as e:
            print(f"club {month} failed: {e}")

    print(f"\n{total} new positions sampled")


if __name__ == "__main__":
    main()
