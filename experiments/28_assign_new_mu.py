"""Exp 28 — assign the newer machine-unique positions to the eight concepts.

The concepts were clustered (exp 16) from Leela layer-10 embeddings of the first
1,745 machine-unique positions. Later batches found ~3,400 more. Cheap features
cannot place them reliably (63% agreement with the embedding clusters, tested),
so this embeds them the same way and assigns each to its nearest centroid — the
k-means assignment rule, applied to new points in the same space.

Also records a margin (cosine to nearest minus cosine to second-nearest) so the
trainer can prefer positions that sit squarely inside a concept.

Runs in the `leela` conda env. Output: results/28_mu_assignments.csv and
results/emb_cache/mu_new.npy.
"""
import importlib.util
import pathlib

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "results" / "emb_cache"


def main() -> None:
    old = pd.read_csv(ROOT / "results" / "16_mu_families.csv")
    Z_old = np.load(CACHE / "mu_all.npy")
    assert len(Z_old) == len(old)
    allmu = pd.read_csv(ROOT / "results" / "master_machine_unique.csv")
    new = allmu[~allmu.fen.isin(set(old.fen))].drop_duplicates("fen").reset_index(drop=True)
    print(f"{len(old)} clustered, {len(new)} new machine-unique positions to assign")

    cache = CACHE / "mu_new.npy"
    if cache.exists() and len(np.load(cache)) == len(new):
        Z_new = np.load(cache)
    else:
        spec = importlib.util.spec_from_file_location(
            "exp05", ROOT / "experiments" / "05_leela_concepts.py")
        exp05 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exp05)
        from leela_interp import Lc0Model
        model = Lc0Model(str(exp05.WEIGHTS), device="cpu")
        emb = exp05.Embedder(model, layer=10)
        chunks = []
        for i in range(0, len(new), 200):
            chunks.append(emb.embed(new.fen.tolist()[i:i + 200]))
            print(f"  embedded {min(i + 200, len(new))}/{len(new)}", flush=True)
        Z_new = np.concatenate(chunks)
        np.save(cache, Z_new)

    n = lambda Z: Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)
    Zo, Zn = n(Z_old), n(Z_new)
    fams = sorted(old.family.unique())
    C = np.stack([Zo[old.family.to_numpy() == f].mean(0) for f in fams])
    C = n(C)

    # sanity: the rule must reproduce the original labels on the original points
    self_assign = np.array(fams)[(Zo @ C.T).argmax(1)]
    agree = (self_assign == old.family.to_numpy()).mean()
    print(f"nearest-centroid reproduces exp 16 labels on the original set: {agree:.1%}")

    sims = Zn @ C.T
    order = np.argsort(-sims, axis=1)
    top, second = order[:, 0], order[:, 1]
    new["family"] = np.array(fams)[top]
    new["sim"] = sims[np.arange(len(new)), top].round(4)
    new["margin"] = (sims[np.arange(len(new)), top] - sims[np.arange(len(new)), second]).round(4)
    new.to_csv(ROOT / "results" / "28_mu_assignments.csv", index=False)

    print("\nassigned per concept (original -> +new):")
    for f in fams:
        print(f"  Concept {f + 1}: {int((old.family == f).sum()):4d} -> +{int((new.family == f).sum())}")
    print(f"\nmargin quartiles: {np.percentile(new.margin, [25, 50, 75]).round(3)}")
    print("wrote results/28_mu_assignments.csv")


if __name__ == "__main__":
    main()
