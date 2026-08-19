"""Exp 21 — is the difficulty model data-hungry or saturated?

Before spending hours mining more positions, ask what more data is worth: hold out
a fixed 20% of games, train on growing subsets of the rest, and watch test AUC.
A curve still rising at the full 43,603 says more positions will help; a flat one
says the model has learned what this feature set can express.

Split is by game, as everywhere else in this project — positions from one game
never straddle the train/test boundary.

Output: results/21_learning_curve.json
"""
import json
import pathlib

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEED = 0
SIZES = [2000, 5000, 10000, 20000, 30000, None]   # None = every training game
N_SEEDS = 3

import importlib.util
spec = importlib.util.spec_from_file_location(
    "exp20", ROOT / "experiments" / "20_difficulty_model.py")
exp20 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exp20)


def main() -> None:
    df = pd.read_csv(ROOT / "results" / "master_all.csv")
    df["found"] = (df.played_move == df.engine_best).astype(int)
    meta = pd.DataFrame([exp20.move_meta(r.fen, r.engine_best) for r in df.itertuples()])
    df = pd.concat([df.reset_index(drop=True), meta], axis=1)
    df = df[meta.notna().all(axis=1).values].reset_index(drop=True)

    games = df.game_id.astype(str).unique()
    rng = np.random.default_rng(SEED)
    rng.shuffle(games)
    test_games = set(games[:int(len(games) * 0.2)])
    is_test = df.game_id.astype(str).isin(test_games).to_numpy()

    kinds = ["surface", "engine", "maia", "elo"]
    X = exp20.design(df, kinds)
    y = df["found"].to_numpy()
    X_te, y_te = X[is_test], y[is_test]
    train_idx = np.flatnonzero(~is_test)
    train_games = df.game_id.astype(str).to_numpy()

    print(f"{len(df)} positions | test: {is_test.sum()} in {len(test_games)} games | "
          f"train pool: {len(train_idx)}\n")

    out = []
    for size in SIZES:
        aucs = []
        for seed in range(N_SEEDS):
            if size is None:
                idx = train_idx
            else:
                # sample whole games until the position budget is met, so subsets
                # stay game-clustered like the real data
                r = np.random.default_rng(100 + seed)
                gs = df.game_id.astype(str).iloc[train_idx].unique()
                r.shuffle(gs)
                picked, total = [], 0
                counts = df.iloc[train_idx].groupby(df.game_id.astype(str)).size()
                for g in gs:
                    picked.append(g)
                    total += counts.get(g, 0)
                    if total >= size:
                        break
                sel = set(picked)
                idx = train_idx[np.isin(train_games[train_idx], list(sel))]
            clf = HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.06, max_leaf_nodes=15,
                l2_regularization=1.0, random_state=seed)
            clf.fit(X[idx], y[idx])
            aucs.append(roc_auc_score(y_te, clf.predict_proba(X_te)[:, 1]))
            if size is None:
                break                                  # no sampling noise to average
        n = len(idx)
        out.append({"train_n": int(n), "auc_mean": float(np.mean(aucs)),
                    "auc_sd": float(np.std(aucs))})
        print(f"  train n={n:6d}   AUC={np.mean(aucs):.4f} ± {np.std(aucs):.4f}")

    gain_last = out[-1]["auc_mean"] - out[-2]["auc_mean"]
    print(f"\n  slope at the end (last step of ~{out[-1]['train_n']-out[-2]['train_n']} "
          f"positions): {gain_last:+.4f} AUC")
    json.dump({"test_n": int(is_test.sum()), "curve": out,
               "auc_gain_last_step": float(gain_last)},
              open(ROOT / "results" / "21_learning_curve.json", "w"), indent=1)
    print("wrote results/21_learning_curve.json")


if __name__ == "__main__":
    main()
