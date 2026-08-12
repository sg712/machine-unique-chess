"""Exp 05b — group concept mining.

Exp 05 mined one vector per position: all 30 solved, none generalized (~0.5 = chance),
consistent with the paper's 97.6% attrition. Hypothesis: 72 constraints in 768 dims is
too underdetermined — the LP overfits each position.

Fix tested here: mine ONE vector over a GROUP of positions (stack every group member's
chosen-vs-subpar constraints into a single LP). Evaluate on held-out positions the
vector never saw. If group-mined vectors beat per-position vectors on held-out
separation, generality-by-construction works and scale is the road forward.
"""
import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from concept_mining import mine_concept  # noqa: E402

spec = importlib.util.spec_from_file_location("exp05", ROOT / "experiments" / "05_leela_concepts.py")
exp05 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exp05)


def main() -> None:
    from leela_interp import Lc0Model
    df = pd.read_csv(ROOT / "results" / "03_disagreements.csv")
    fens = df[df.machine_unique].sort_values("human_cost_cp", ascending=False).fen.tolist()[:30]

    model = Lc0Model(str(exp05.WEIGHTS), device="cpu")
    emb = exp05.Embedder(model, layer=10)

    packs_file = ROOT / "results" / "05b_packs.npz"
    packs = []
    if packs_file.exists():
        data = np.load(packs_file, allow_pickle=True)
        packs = list(data["packs"])
        print(f"loaded {len(packs)} cached rollout packs")
    else:
        for i, fen in enumerate(fens):
            try:
                top = emb.policy_top(fen, k=3)
                chosen = exp05.rollout(emb, fen, top[0], 6)
                subpar = []
                for alt in top[1:3]:
                    subpar += exp05.rollout(emb, fen, alt, 6)
                if len(chosen) < 3 or len(subpar) < 3:
                    continue
                packs.append({"fen": fen, "zp": emb.embed(chosen), "zn": emb.embed(subpar)})
                print(f"embedded {i+1}/{len(fens)}")
            except Exception as e:
                print(f"{i+1} failed: {e}")
        np.savez(packs_file, packs=np.array(packs, dtype=object))

    n = len(packs)
    group_size = 5
    rng = np.random.default_rng(0)
    order = rng.permutation(n)
    groups = [order[i:i + group_size] for i in range(0, n - group_size + 1, group_size)]

    print(f"\n{n} packs -> {len(groups)} groups of {group_size}")
    results = []
    for gi, g in enumerate(groups):
        zp = np.concatenate([packs[i]["zp"] for i in g])
        zn = np.concatenate([packs[i]["zn"] for i in g])
        try:
            v, slack = mine_concept(zp, zn)
        except RuntimeError as e:
            print(f"group {gi}: LP failed ({e})")
            continue
        v = v / (np.linalg.norm(v) + 1e-12)
        held = [i for i in range(n) if i not in set(g.tolist())]
        gen = float(np.mean([exp05.separation(v, packs[i]["zp"], packs[i]["zn"]) for i in held]))
        in_group = float(np.mean([exp05.separation(v, packs[i]["zp"], packs[i]["zn"]) for i in g]))
        nz = int((np.abs(v) > 1e-6).sum())
        results.append((gi, nz, slack, in_group, gen))
        print(f"group {gi}: {nz} nonzeros, slack {slack:.1f}, in-group sep {in_group:.3f}, HELD-OUT sep {gen:.3f}")

    if results:
        gens = [r[4] for r in results]
        print(f"\nmean held-out separation: {np.mean(gens):.3f}  (chance = 0.5; exp05 per-position mean was 0.507)")
        print(f"best group: {max(gens):.3f}")


if __name__ == "__main__":
    main()
