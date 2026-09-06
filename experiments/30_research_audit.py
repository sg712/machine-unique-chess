"""Reproducible descriptive audit; does not change mining labels or trainer answers.

Usage: python experiments/30_research_audit.py [--skip-engine]
The engine audit takes eight seeded positions per rating band, with distinct
source games. Every search has a depth target AND a time limit; actual depths
are recorded. Cached engine rows are reused only for the same input and settings.
"""
import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.engine
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
SEED = 20260907
BANDS = ["≤2000", "2000–2200", "2200–2400", "2400–2600", "2600–2800", ">2800"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def band(elo):
    return next((i for i, upper in enumerate([2000, 2200, 2400, 2600, 2800])
                 if float(elo) <= upper), 5)


def found(row):
    return row["played_move"] == row["engine_best"]


def selected(row, gap=100, probability=.05):
    return float(row["human_cost_cp"]) >= gap and float(row["p_max"]) <= probability


def group_interval(rows):
    """Percentile bootstrap of source games, retaining their position counts."""
    games = defaultdict(lambda: [0, 0])
    for row in rows:
        games[row["game_id"]][0] += int(found(row))
        games[row["game_id"]][1] += 1
    counts = np.array(list(games.values()))
    rng = np.random.default_rng(SEED)
    draws = []
    for _ in range(1000):
        total = counts[rng.integers(0, len(counts), len(counts))].sum(axis=0)
        draws.append(total[0] / total[1])
    return np.quantile(draws, [.025, .975]).tolist()


def analyse(engine, row, args):
    board = chess.Board(row["fen"])
    def search(roots=None, multipv=None):
        engine.configure({"Clear Hash": None})
        infos = engine.analyse(board, chess.engine.Limit(depth=args.depth, time=args.seconds),
                               root_moves=roots, multipv=multipv)
        if not isinstance(infos, list):
            infos = [infos]
        result = []
        for info in infos:
            score = info["score"].pov(board.turn)
            result.append({"uci": info["pv"][0].uci(), "cp": score.score(),
                           "mate": score.mate(), "depth": info["depth"],
                           "nodes": info.get("nodes"), "seconds": info.get("time"),
                           "pv": [m.uci() for m in info["pv"][:10]]})
        return result
    top = search(multipv=2)
    roots = {}
    for move in dict.fromkeys([row["engine_best"], row["human_top_2000"], row["played_move"]]):
        roots[move] = search([chess.Move.from_uci(move)])[0]
    old, human, played = (roots[row[k]] for k in ["engine_best", "human_top_2000", "played_move"])
    scores = top + list(roots.values())
    all_cp = all(s["cp"] is not None for s in scores)
    best_seen = max(s["cp"] for s in scores) if all_cp else None
    return {"fen": row["fen"], "game_id": row["game_id"], "band": BANDS[band(row["mover_elo"])],
            "original_best": row["engine_best"], "played_move": row["played_move"],
            "human_top_2000": row["human_top_2000"], "top": top, "restricted": roots,
            "same_top_move": top[0]["uci"] == row["engine_best"],
            "all_searches_reached_target": all(s["depth"] >= args.depth for s in scores),
            "minimum_depth": min(s["depth"] for s in scores),
            "mate_in_search": not all_cp,
            "original_move_gap_to_maia_cp": old["cp"] - human["cp"] if all_cp else None,
            "played_loss_vs_best_seen_cp": best_seen - played["cp"] if all_cp else None,
            "original_loss_vs_best_seen_cp": best_seen - old["cp"] if all_cp else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-engine", action="store_true")
    parser.add_argument("--per-band", type=int, default=8)
    parser.add_argument("--depth", type=int, default=20)
    parser.add_argument("--seconds", type=float, default=3)
    args = parser.parse_args()
    master = RESULTS / "master_all.csv"
    rows = list(csv.DictReader(master.open()))
    mu = [r for r in rows if selected(r)]
    assert sum(r["machine_unique"] == "True" for r in rows) == len(mu)
    frontier = list(csv.DictReader((RESULTS / "06_frontier_2600.csv").open()))
    output = {"generated_at": datetime.now(timezone.utc).isoformat(), "seed": SEED,
              "inputs": {p.name: digest(p) for p in [master, RESULTS / "06_frontier_2600.csv"]},
              "n": len(rows), "mu_n": len(mu), "mu_rate": len(mu) / len(rows),
              "exact_matches": sum(found(r) for r in mu),
              "hard_core_n": sum(not found(r) for r in mu),
              "missed_by_2500_plus": sum(not found(r) and float(r["mover_elo"]) >= 2500 for r in mu),
              "bands": [], "thresholds": [], "frontier": [], "batches": [],
              "near_alternatives": [{"below_cp": cp,
                  "n": sum(float(r["engine_margin"]) < cp for r in mu),
                  "rate": sum(float(r["engine_margin"]) < cp for r in mu) / len(mu)}
                  for cp in [10, 20, 50, 100]]}
    sample, seen_games = [], set()
    rng = random.Random(SEED)
    for i, label in enumerate(BANDS):
        pool = [r for r in mu if band(r["mover_elo"]) == i]
        output["bands"].append({"label": label, "all_n": sum(band(r["mover_elo"]) == i for r in rows),
            "n": len(pool), "games": len({r["game_id"] for r in pool}),
            "exact_n": sum(found(r) for r in pool), "exact_rate": sum(found(r) for r in pool) / len(pool),
            "ci": group_interval(pool)})
        rng.shuffle(pool)
        chosen = 0
        for row in pool:
            if row["game_id"] in seen_games:
                continue
            sample.append(row)
            seen_games.add(row["game_id"])
            chosen += 1
            if chosen == args.per_band:
                break
        assert chosen == args.per_band
    for gap in [50, 100, 200]:
        for probability in [.01, .025, .05, .10]:
            subset = [r for r in rows if selected(r, gap, probability)]
            output["thresholds"].append({"gap_cp": gap, "p_max": probability, "n": len(subset),
                "rate": len(subset) / len(rows), "exact_rate": sum(found(r) for r in subset) / len(subset)})
    for batch in sorted({r["batch"] for r in rows}):
        subset = [r for r in rows if r["batch"] == batch]
        output["batches"].append({"batch": batch, "n": len(subset), "mu_n": sum(selected(r) for r in subset)})
    for group in ["machine_unique", "control"]:
        for elo in [1100, 1500, 2000, 2300, 2600]:
            subset = [r for r in frontier if r["set"] == group and int(r["elo"]) == elo]
            output["frontier"].append({"group": group, "elo": elo, "n": len(subset),
                "top1": sum(r["rank"] == "1.0" for r in subset) / len(subset),
                "top5": sum(bool(r["rank"]) for r in subset) / len(subset)})
    # FEN includes move counters; state deduplication is a distinct sensitivity check.
    states = Counter(" ".join(r["fen"].split()[:4]) for r in rows)
    output["duplicate_board_states"] = sum(n - 1 for n in states.values())
    if not args.skip_engine:
        binary = ROOT / "models" / "stockfish-build" / "src" / "stockfish"
        settings = {"depth_target": args.depth, "time_cap_seconds_per_search": args.seconds,
                    "threads": 1, "hash_mb": 128, "clear_hash_each_search": True,
                    "per_band": args.per_band, "binary_sha256": digest(binary),
                    "master_sha256": digest(master), "seed": SEED}
        path = RESULTS / "30_engine_audit.json"
        cache = json.loads(path.read_text()) if path.exists() else {}
        records = cache.get("positions", []) if cache.get("settings") == settings else []
        by_fen = {r["fen"]: r for r in records}
        with chess.engine.SimpleEngine.popen_uci(str(binary)) as engine:
            engine.configure({"Threads": 1, "Hash": 128})
            for index, row in enumerate(sample):
                if row["fen"] not in by_fen:
                    by_fen[row["fen"]] = analyse(engine, row, args)
                records = [by_fen[r["fen"]] for r in sample if r["fen"] in by_fen]
                path.write_text(json.dumps({"settings": settings, "engine": engine.id,
                                           "positions": records}, indent=2) + "\n")
                print(f"Engine audit {index + 1}/{len(sample)}; minimum depth {by_fen[row['fen']]['minimum_depth']}", flush=True)
        numeric = [r for r in records if not r["mate_in_search"]]
        complete = [r for r in records if r["all_searches_reached_target"]]
        output["engine"] = {"settings": settings, "n": len(records), "numeric_n": len(numeric),
            "complete_n": len(complete), "minimum_depth": min(r["minimum_depth"] for r in records),
            "same_top_n": sum(r["same_top_move"] for r in records),
            "complete_same_top_n": sum(r["same_top_move"] for r in complete),
            "old_gap_at_least_100_n": sum(r["original_move_gap_to_maia_cp"] >= 100 for r in numeric),
            "played_exact_n": sum(r["played_move"] == r["original_best"] for r in numeric),
            "played_within_20_n": sum(r["played_loss_vs_best_seen_cp"] <= 20 for r in numeric),
            "old_within_20_n": sum(r["original_loss_vs_best_seen_cp"] <= 20 for r in numeric)}
    (RESULTS / "30_research_audit.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({k: output[k] for k in ["n", "mu_n", "hard_core_n"]}), flush=True)


if __name__ == "__main__":
    main()
