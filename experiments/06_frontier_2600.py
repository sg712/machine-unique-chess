"""Exp 06 — does machine-uniqueness survive at 2600?

Maia-2 capped the frontier at Elo 2000. Maia-3 (Chessformer, ICLR 2026) conditions on
continuous Elo trained through 2600+. Question: do the 77 machine-unique positions stay
invisible to simulated 2600-level humans, or does the strongest human band finally see them?

For each position and each Elo in {1100, 1500, 2000, 2300, 2600}:
  ask Maia-3 (MultiPV=5, nodes=1) for the most likely human moves,
  record the rank of the engine's best move (1..5 or absent).

Controls: a random sample of NON-machine-unique positions where the engine's move was
clearly best but humans-at-2000 already often found it — convergence should continue there.

Usage (inside `unnamed-concepts` env):
    python experiments/06_frontier_2600.py --model maia3-79m --device cpu
"""
import argparse
import pathlib
import sys

import chess
import chess.engine
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
ELOS = [1100, 1500, 2000, 2300, 2600]


def maia3_ranks(eng, fen: str, target_uci: str, multipv: int = 5) -> int | None:
    """Rank of target move among Maia-3's most likely human moves (1-based), or None."""
    board = chess.Board(fen)
    info = eng.analyse(board, chess.engine.Limit(nodes=1), multipv=multipv)
    for rank, line in enumerate(info, start=1):
        pv = line.get("pv")
        if pv and pv[0].uci() == target_uci:
            return rank
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="maia3-79m")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--n-control", type=int, default=60)
    args = ap.parse_args()

    df = pd.read_csv(ROOT / "results" / "03_disagreements.csv")
    mu = df[df.machine_unique].copy()
    # control: engine move also clearly best, but visible to Maia-2 humans at 2000
    ctrl = df[(~df.machine_unique) & (df.human_cost_cp >= 100) & (df.p_engine_move_2000 >= 0.2)]
    ctrl = ctrl.sample(min(args.n_control, len(ctrl)), random_state=0)
    print(f"machine-unique: {len(mu)}, control: {len(ctrl)}")

    cmd = [sys.executable, "-m", "maia3.uci", "--model", args.model,
           "--device", args.device, "--no-use-amp"]
    rows = []
    for elo in ELOS:
        eng = chess.engine.SimpleEngine.popen_uci(cmd)
        try:
            eng.configure({"Elo": elo})
        except Exception as e:
            print(f"configure Elo failed ({e}) — trying SelfElo/OppoElo")
            eng.configure({"SelfElo": elo, "OppoElo": elo})
        for label, sub in (("machine_unique", mu), ("control", ctrl)):
            for r in sub.itertuples(index=False):
                rank = maia3_ranks(eng, r.fen, r.engine_best)
                rows.append({"set": label, "elo": elo, "fen": r.fen,
                             "engine_best": r.engine_best, "rank": rank})
        eng.quit()
        d = pd.DataFrame(rows)
        for label in ("machine_unique", "control"):
            s = d[(d.elo == elo) & (d.set == label)]
            print(f"elo {elo} {label:15s}: top1 {(s['rank'] == 1).mean()*100:5.1f}%   "
                  f"top5 {s['rank'].notna().mean()*100:5.1f}%")

    out = ROOT / "results" / "06_frontier_2600.csv"
    pd.DataFrame(rows).to_csv(out, index=False)

    d = pd.DataFrame(rows)
    print("\n=== summary: engine move is Maia-3's TOP-1 human move ===")
    piv = d.assign(top1=(d["rank"] == 1)).pivot_table(index="elo", columns="set", values="top1")
    print((piv * 100).round(1))
    print("\n=== engine move in Maia-3's TOP-5 human moves ===")
    piv5 = d.assign(top5=d["rank"].notna()).pivot_table(index="elo", columns="set", values="top5")
    print((piv5 * 100).round(1))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
