"""Exp 27 — the same embeddings under four other unsupervised methods.

K-means (exp 16/18) found soft structure and an underdetermined k. Before
trusting that summary, look through lenses with different inductive biases:

  1. HDBSCAN     — density-based; allowed to answer "most points are noise"
  2. GMM + BIC   — model-based; picks k by likelihood, can prefer k=1
  3. Agglomerative — hierarchy; does merging structure agree with k-means?
  4. Dictionary learning — sparse parts instead of partitions; which atoms
     fire for machine-unique positions but not for ordinary ones?

If every lens agrees the structure is soft, the k-means verdict stands on
much firmer ground than one method's opinion.

Output: results/27_other_lenses.json
"""
import json
import pathlib

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans, AgglomerativeClustering, HDBSCAN
from sklearn.decomposition import DictionaryLearning, PCA
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.mixture import GaussianMixture

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "results" / "emb_cache"
SEED = 0
THEMES = ["attraction", "clearance", "defensiveMove", "deflection", "discoveredAttack",
          "exposedKing", "fork", "intermezzo", "pin", "quietMove", "sacrifice", "skewer"]


def norm(Z):
    return Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)


def main() -> None:
    mu = pd.read_csv(ROOT / "results" / "16_mu_families.csv")
    Z = norm(np.load(CACHE / "mu_all.npy"))
    C = norm(np.load(CACHE / "control.npy"))
    print(f"{len(Z)} machine-unique embeddings, {len(C)} control\n")
    out = {}

    # 1 — HDBSCAN on PCA-reduced (density needs moderate dims)
    P = PCA(n_components=40, random_state=SEED).fit(Z)
    Zp = P.transform(Z)
    print("=== HDBSCAN ===")
    hdb_res = {}
    for mcs in (15, 25, 50):
        lab = HDBSCAN(min_cluster_size=mcs).fit_predict(Zp)
        n_c = len(set(lab)) - (1 in set(-lab))
        n_c = len([c for c in set(lab) if c != -1])
        noise = float((lab == -1).mean())
        km8 = KMeans(8, n_init=8, random_state=SEED).fit_predict(Z)
        ari = adjusted_rand_score(km8[lab != -1], lab[lab != -1]) if n_c > 1 else 0.0
        hdb_res[mcs] = {"clusters": n_c, "noise_frac": noise, "ari_vs_kmeans8": ari}
        print(f"  min_cluster_size={mcs:3d}: {n_c} clusters, {noise:.0%} labelled noise, "
              f"ARI vs k-means8 on non-noise = {ari:.2f}")
    out["hdbscan"] = hdb_res

    # 2 — Gaussian mixture, BIC across k
    print("\n=== Gaussian mixture BIC (lower is better) ===")
    bics = {}
    for k in (1, 2, 4, 6, 8, 10, 12):
        g = GaussianMixture(k, covariance_type="diag", random_state=SEED,
                            n_init=2).fit(Zp)
        bics[k] = float(g.bic(Zp))
    best = min(bics, key=bics.get)
    for k, v in bics.items():
        print(f"  k={k:2d}  BIC={v:12.0f}{'   <<< best' if k == best else ''}")
    out["gmm_bic"] = {"bic": bics, "best_k": best}

    # 3 — agreement between agglomerative and k-means at k=8
    agg = AgglomerativeClustering(8).fit_predict(Z)
    km8 = KMeans(8, n_init=8, random_state=SEED).fit_predict(Z)
    ari = adjusted_rand_score(agg, km8)
    sil_a = silhouette_score(Z, agg, sample_size=1200, random_state=SEED)
    print(f"\n=== agglomerative k=8: silhouette {sil_a:.3f}, ARI vs k-means {ari:.2f} ===")
    out["agglomerative"] = {"silhouette": float(sil_a), "ari_vs_kmeans8": float(ari)}

    # 4 — sparse dictionary: atoms enriched in MU vs control
    print("\n=== dictionary learning (32 atoms, sparse codes) ===")
    both = np.vstack([Z, C])
    dl = DictionaryLearning(n_components=32, alpha=0.5, max_iter=300,
                            random_state=SEED, transform_alpha=0.5,
                            transform_algorithm="lasso_lars")
    codes = dl.fit(both).transform(both)
    act = codes != 0
    mu_rate, c_rate = act[:len(Z)].mean(0), act[len(Z):].mean(0)
    theme_dirs = {}
    for t in THEMES:
        T = norm(np.load(CACHE / f"theme_{t}.npy"))
        theme_dirs[t] = T.mean(0) / np.linalg.norm(T.mean(0))
    atoms = []
    for a in np.argsort(-(mu_rate - c_rate))[:8]:
        cos = {t: float(dl.components_[a] @ v /
                        (np.linalg.norm(dl.components_[a]) + 1e-9))
               for t, v in theme_dirs.items()}
        top = sorted(cos.items(), key=lambda kv: -abs(kv[1]))[:2]
        atoms.append({"atom": int(a), "mu_rate": float(mu_rate[a]),
                      "control_rate": float(c_rate[a]),
                      "closest_themes": top})
        print(f"  atom {a:2d}: fires {mu_rate[a]:5.1%} MU vs {c_rate[a]:5.1%} control  "
              f"closest: {top[0][0]} {top[0][1]:+.2f}, {top[1][0]} {top[1][1]:+.2f}")
    out["dictionary_atoms_mu_enriched"] = atoms

    json.dump(out, open(ROOT / "results" / "27_other_lenses.json", "w"), indent=1)
    print("\nwrote results/27_other_lenses.json")


if __name__ == "__main__":
    main()
