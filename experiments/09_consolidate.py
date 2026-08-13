"""Exp 09 — consolidate all mining batches and define the hard core.

Merges every 03_* results file, rebuilds the master datasets, and defines two tiers:

  * machine_unique — engine clearly right, invisible to simulated humans (Maia <=5% at every level)
  * hard_core      — machine_unique AND the real player in the game failed to find the move

The hard core is the more defensible target set after exp 06: real masters recover
~30-50% of Maia-invisible moves by calculation, so "invisible to simulation" alone
overstates the wall. Hard-core positions resisted a real human who was actually there.

Output: results/master_all.csv, master_machine_unique.csv, hard_core.csv + printed stats.
"""
import glob
import pathlib

import chess
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
R = ROOT / "results"


def main() -> None:
    frames = []
    for f in sorted(glob.glob(str(R / "03_*.csv"))):
        df = pd.read_csv(f)
        df["source"] = "elite" if "elite" in f else "club"
        df["batch"] = pathlib.Path(f).stem
        frames.append(df)
        print(f"{pathlib.Path(f).name}: {len(df)} rows, {df.machine_unique.sum()} MU")
    allpos = pd.concat(frames).drop_duplicates("fen").reset_index(drop=True)

    # attach player ratings from the position files
    pos = pd.concat([
        pd.read_csv(ROOT / "data" / "positions.csv"),
        pd.read_csv(ROOT / "data" / "positions_elite.csv"),
    ]).drop_duplicates("fen")[["fen", "white_elo", "black_elo"]]
    allpos = allpos.merge(pos, on="fen", how="left")

    def mover_elo(r):
        try:
            return r.white_elo if chess.Board(r.fen).turn else r.black_elo
        except Exception:
            return float("nan")

    allpos["mover_elo"] = allpos.apply(mover_elo, axis=1)
    allpos["real_found"] = allpos.played_move == allpos.engine_best
    allpos["hard_core"] = allpos.machine_unique & ~allpos.real_found

    mu = allpos[allpos.machine_unique]
    hc = allpos[allpos.hard_core]

    allpos.to_csv(R / "master_all.csv", index=False)
    mu.to_csv(R / "master_machine_unique.csv", index=False)
    hc.to_csv(R / "hard_core.csv", index=False)

    print(f"\n=== master: {len(allpos)} positions ===")
    print(f"machine-unique: {len(mu)} ({100*len(mu)/len(allpos):.1f}%)")
    print(f"hard core (MU + real player failed): {len(hc)}")
    print(f"  of which from elite (2300+) games: {(hc.source=='elite').sum()}")
    print(f"  failed by a 2500+ rated mover:     {(hc.mover_elo>=2500).sum()}")

    print("\nreal players finding the engine move, by band:")
    allpos["band"] = pd.cut(allpos.mover_elo, [0, 2000, 2200, 2400, 2600, 4000],
                            labels=["<2000", "2000-2200", "2200-2400", "2400-2600", "2600+"])
    t = allpos.pivot_table(index="band", columns="machine_unique", values="real_found",
                           aggfunc=["mean", "count"], observed=False)
    t.columns = ["normal %", "MU %", "n normal", "n MU"]
    t["normal %"] = (t["normal %"] * 100).round(1)
    t["MU %"] = (t["MU %"] * 100).round(1)
    print(t)


if __name__ == "__main__":
    main()
