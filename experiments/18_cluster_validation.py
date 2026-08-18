"""Exp 18 — is the clustering real, and how many groups are there?

Exp 16 used k=8 with no justification. This tests whether the structure exists
at all, and if so at what k, using four independent criteria:

  1. Silhouette across k = 2..16 — internal separation
  2. Bootstrap stability (adjusted Rand index over resamples) — do the same
     positions keep landing together when the sample changes?
  3. Null comparison — same procedure on rotated/shuffled embeddings, to see
     what silhouette a structureless cloud of this shape produces
  4. External validity — does cluster membership predict how often real players
     found the move, beyond chance? (permutation test on between-cluster variance)

A clustering that beats the null and predicts an outside variable is real.
One that doesn't is a Rorschach test.

Output: results/18_validation.json
"""
import json
import pathlib

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "results" / "emb_cache"
KS = list(range(2, 17))
N_BOOT = 25
SEED = 0


def load():
    mu = pd.read_csv(ROOT / "results" / "16_mu_families.csv")
    Z = np.load(CACHE / "mu_all.npy")
    assert len(Z) == len(mu), (len(Z), len(mu))
    Zn = Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)
    return mu, Zn


def silhouettes(Zn, ks, seed=SEED):
    out = {}
    for k in ks:
        lab = KMeans(n_clusters=k, n_init=8, random_state=seed).fit_predict(Zn)
        out[k] = float(silhouette_score(Zn, lab, sample_size=1200, random_state=seed))
    return out


def null_silhouettes(Zn, ks, rng):
    """Structureless control with the same dimensionality and scale: a random
    rotation of the data destroys cluster structure but preserves the spectrum."""
    d = Zn.shape[1]
    Q, _ = np.linalg.qr(rng.normal(size=(d, d)))
    shuffled = np.column_stack([rng.permutation(Zn[:, j]) for j in range(d)])
    shuffled /= np.linalg.norm(shuffled, axis=1, keepdims=True) + 1e-9
    return silhouettes(shuffled, ks)


def bootstrap_stability(Zn, k, n_boot=N_BOOT, rng=None):
    """Cluster two overlapping resamples; compare labels on their intersection."""
    n = len(Zn)
    base = KMeans(n_clusters=k, n_init=8, random_state=SEED).fit(Zn)
    scores = []
    for b in range(n_boot):
        idx = rng.choice(n, size=int(n * 0.8), replace=False)
        lab = KMeans(n_clusters=k, n_init=8, random_state=1000 + b).fit_predict(Zn[idx])
        scores.append(adjusted_rand_score(base.labels_[idx], lab))
    return float(np.mean(scores)), float(np.std(scores))


def external_validity(mu, labels, rng, n_perm=2000):
    """Do clusters differ in how often real players found the move, more than
    random groupings of the same sizes would?"""
    found = mu["real_found"].to_numpy().astype(float)
    df = pd.DataFrame({"lab": labels, "f": found})
    obs = df.groupby("lab").f.mean().var()
    null = np.empty(n_perm)
    for i in range(n_perm):
        null[i] = pd.DataFrame({"lab": rng.permutation(labels), "f": found}) \
                    .groupby("lab").f.mean().var()
    p = float((null >= obs).mean())
    return {"observed_variance": float(obs), "null_mean": float(null.mean()),
            "p_value": p, "significant": p < 0.05}


def main() -> None:
    rng = np.random.default_rng(SEED)
    mu, Zn = load()
    print(f"{len(Zn)} positions, {Zn.shape[1]} dims\n")

    print("silhouette by k (real vs null)")
    real = silhouettes(Zn, KS)
    null = null_silhouettes(Zn, KS, rng)
    for k in KS:
        margin = real[k] - null[k]
        flag = "  <<<" if margin == max(real[j] - null[j] for j in KS) else ""
        print(f"  k={k:2d}  real={real[k]:.4f}  null={null[k]:.4f}  margin={margin:+.4f}{flag}")

    best_k = max(KS, key=lambda k: real[k] - null[k])
    print(f"\nbest margin over null at k={best_k}")

    print("\nbootstrap stability (adjusted Rand, 80% resamples)")
    stab = {}
    for k in sorted({4, 6, 8, 10, best_k}):
        m, s = bootstrap_stability(Zn, k, rng=rng)
        stab[k] = {"mean_ari": m, "std": s}
        verdict = "stable" if m >= 0.6 else ("moderate" if m >= 0.4 else "unstable")
        print(f"  k={k:2d}  ARI={m:.3f} ± {s:.3f}   {verdict}")

    print("\nexternal validity — do clusters predict human find-rate?")
    ext = {}
    for k in sorted({8, best_k}):
        lab = KMeans(n_clusters=k, n_init=8, random_state=SEED).fit_predict(Zn)
        ext[k] = external_validity(mu, lab, rng)
        print(f"  k={k:2d}  observed var={ext[k]['observed_variance']:.5f}  "
              f"null={ext[k]['null_mean']:.5f}  p={ext[k]['p_value']:.4f}  "
              f"{'SIGNIFICANT' if ext[k]['significant'] else 'not significant'}")

    out = {"n": len(Zn), "silhouette_real": real, "silhouette_null": null,
           "best_k_by_margin": best_k, "stability": stab, "external_validity": ext}
    json.dump(out, open(ROOT / "results" / "18_validation.json", "w"), indent=1)
    print(f"\nwrote results/18_validation.json")


if __name__ == "__main__":
    main()
