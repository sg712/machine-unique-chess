"""Exp 19 — is the Leela embedding telling us anything surface features don't?

Exp 18 showed the clusters are real but weak, and that k is underdetermined.
The sharper question: when a cluster predicts how often humans found the move,
is that because the engine's internal representation captures something, or
because the cluster is a proxy for obvious things like "quiet queen move in an
endgame"?

Three tests, all cross-validated:

  A. Predict `real_found` from surface chess features alone (piece, quiet,
     phase, capture, check, cost) — the baseline any chess player could build.
  B. Predict it from the cluster label alone.
  C. Predict it from surface features + cluster label.

If C beats A, the embedding carries information beyond surface features. If it
doesn't, the clusters are an expensive way to say "quiet queen endgame move".

Also sweeps external validity across k to find where cluster structure best
predicts human failure.

Output: results/19_embedding_value.json
"""
import json
import pathlib

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import OneHotEncoder

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "results" / "emb_cache"
SEED = 0
KS = [4, 5, 6, 7, 8, 9, 10, 12]


def surface_matrix(mu: pd.DataFrame) -> np.ndarray:
    """What any chess player can see without a neural network."""
    cat = mu[["piece", "phase"]].astype(str)
    enc = OneHotEncoder(sparse_output=False, handle_unknown="ignore").fit_transform(cat)
    num = mu[["quiet", "capture", "check", "pawn_move", "king_move",
              "advance", "retreat"]].astype(float).to_numpy()
    cost = mu[["human_cost_cp"]].fillna(0).to_numpy()
    pmax = mu[["p_max"]].fillna(0).to_numpy() if "p_max" in mu else np.zeros((len(mu), 1))
    return np.hstack([enc, num, cost, pmax])


def score(X: np.ndarray, y: np.ndarray, seed=SEED) -> tuple[float, float]:
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    clf = GradientBoostingClassifier(random_state=seed, n_estimators=120, max_depth=3)
    s = cross_val_score(clf, X, y, cv=cv, scoring="roc_auc")
    return float(s.mean()), float(s.std())


def main() -> None:
    mu = pd.read_csv(ROOT / "results" / "16_mu_families.csv")
    Z = np.load(CACHE / "mu_all.npy")
    Zn = Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)
    y = mu["real_found"].astype(int).to_numpy()
    print(f"{len(mu)} positions; {y.mean()*100:.1f}% found by the player at the board\n")

    base_auc, base_sd = score(surface_matrix(mu), y)
    dummy = cross_val_score(DummyClassifier(strategy="stratified", random_state=SEED),
                            surface_matrix(mu), y,
                            cv=StratifiedKFold(5, shuffle=True, random_state=SEED),
                            scoring="roc_auc").mean()
    print(f"A. surface features only      AUC = {base_auc:.4f} ± {base_sd:.4f}")
    print(f"   (random baseline           AUC = {dummy:.4f})\n")

    out = {"n": len(mu), "found_rate": float(y.mean()),
           "surface_auc": base_auc, "surface_sd": base_sd, "random_auc": float(dummy),
           "by_k": {}}

    print(f"{'k':>3} {'cluster only':>14} {'surface+cluster':>17} {'gain over surface':>19}")
    for k in KS:
        lab = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit_predict(Zn)
        onehot = OneHotEncoder(sparse_output=False).fit_transform(lab.reshape(-1, 1))
        c_auc, c_sd = score(onehot, y)
        both_auc, both_sd = score(np.hstack([surface_matrix(mu), onehot]), y)
        gain = both_auc - base_auc
        out["by_k"][k] = {"cluster_auc": c_auc, "cluster_sd": c_sd,
                          "combined_auc": both_auc, "combined_sd": both_sd,
                          "gain_over_surface": gain}
        flag = "  <<<" if gain > 0.01 else ""
        print(f"{k:>3} {c_auc:>10.4f}     {both_auc:>13.4f}     {gain:>+15.4f}{flag}")

    # Does the raw embedding (no clustering) beat surface features?
    print("\nD. raw embedding, 40 principal components (no clustering)")
    Zc = Zn - Zn.mean(0)
    U, S, Vt = np.linalg.svd(Zc, full_matrices=False)
    pcs = Zc @ Vt[:40].T
    raw_auc, raw_sd = score(pcs, y)
    comb_auc, _ = score(np.hstack([surface_matrix(mu), pcs]), y)
    out["raw_embedding_auc"] = raw_auc
    out["surface_plus_raw_auc"] = comb_auc
    print(f"   embedding only             AUC = {raw_auc:.4f} ± {raw_sd:.4f}")
    print(f"   surface + embedding        AUC = {comb_auc:.4f}   "
          f"(gain {comb_auc - base_auc:+.4f})")

    best_k = max(KS, key=lambda k: out["by_k"][k]["gain_over_surface"])
    out["best_k_by_gain"] = best_k
    print(f"\nbest cluster gain at k={best_k}: "
          f"{out['by_k'][best_k]['gain_over_surface']:+.4f} AUC")

    json.dump(out, open(ROOT / "results" / "19_embedding_value.json", "w"), indent=1)
    print("\nwrote results/19_embedding_value.json")


if __name__ == "__main__":
    main()
