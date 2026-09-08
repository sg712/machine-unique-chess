"""Recover exact historical Lichess games from a bounded resumable PGN prefix.

This preserves source PGNs only. It does not add corpus rows or synthesize any
history. Game IDs are supplied by the historical provenance audit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.mining_v2_sampling import ROOT, file_sha256
from scripts.mining_v3_sampling import cached_zstd_chunks, game_blocks


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--month", default="2026-07")
    ap.add_argument("--targets", type=Path, default=ROOT / "data/mining_v3/missing_club_games.json")
    ap.add_argument("--max-mb", type=int, default=4096)
    args = ap.parse_args()
    target = json.loads(args.targets.read_text())[args.month]
    requested = set(target["game_ids"])
    out = args.targets.parent
    preserved = out / f"recovered_club_{args.month}.pgn"
    cache = out / f"recovery_club_{args.month}_prefix.pgn.zst"
    manifest_path = out / f"recovered_club_{args.month}_manifest.json"
    found = set()
    if preserved.exists():
        with preserved.open() as f:
            for line in f:
                if line.startswith('[Site "'):
                    found.add(line.split('"')[1].rsplit('/', 1)[-1])
    url = f"https://database.lichess.org/standard/lichess_db_standard_rated_{args.month}.pgn.zst"
    stats = {"source_url": url, "target_games": len(requested),
             "historical_rows": target.get("rows"), "games_scanned": 0,
             "compressed_byte_limit": args.max_mb << 20}
    site = re.compile(r'^\[Site "https://lichess\.org/([A-Za-z0-9]{8})"\]', re.M)
    remaining = requested - found

    def report():
        stats.update(updated_at=datetime.now(timezone.utc).isoformat(),
                     recovered_games=len(requested & found),
                     missing_games=len(requested - found))
        manifest_path.write_text(json.dumps(stats, indent=2) + "\n")
        print(json.dumps(stats), flush=True)

    if remaining:
        with preserved.open("a") as saved:
            for text in game_blocks(cached_zstd_chunks(url, cache, args.max_mb, stats)):
                stats["games_scanned"] += 1
                match = site.search(text)
                gid = match.group(1) if match else None
                if gid in remaining:
                    saved.write(text + "\n\n")
                    saved.flush()
                    found.add(gid)
                    remaining.remove(gid)
                if stats["games_scanned"] % 100000 == 0:
                    report()
                if not remaining:
                    stats["stop_reason"] = "all_requested_game_ids_recovered"
                    break
    if cache.exists():
        stats["compressed_prefix_sha256"] = file_sha256(cache)
        stats["compressed_bytes_read"] = cache.stat().st_size
    if preserved.exists():
        stats["preserved_pgn_sha256"] = file_sha256(preserved)
    stats["targets_sha256"] = file_sha256(args.targets)
    stats["script_sha256"] = file_sha256(Path(__file__))
    stats["missing_game_ids"] = sorted(requested - found)
    stats["complete"] = not bool(requested - found)
    report()
    if requested - found:
        raise SystemExit("Some requested games remain outside this bounded prefix; resume with a larger limit.")


if __name__ == "__main__":
    main()
