"""Exp 23 — what did the second elite batch actually buy?

Global AUC is saturated (exp 21), but the global number is dominated by club
positions. The new batch doubled the elite corpus, so the fair question is
band-wise: two models — one trained only on the pre-batch data, one on
everything — evaluated on the same held-out games, scored per rating band.

Output: results/23_band_value.json
"""
import json
import pathlib

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, brier_score_loss

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEED = 0

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
    old = df.batch != "03_elite_top"        # everything before the 2600-2800/2800+ batch

    games = df.game_id.astype(str).unique()
    rng = np.random.default_rng(SEED)
    rng.shuffle(games)
    test_games = set(games[:int(len(games) * 0.25)])
    is_test = df.game_id.astype(str).isin(test_games).to_numpy()

    X = exp20.design(df, ["surface", "engine", "maia", "elo"])
    y = df["found"].to_numpy()

    def fit(mask):
        clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                             max_leaf_nodes=15, l2_regularization=1.0,
                                             random_state=SEED)
        clf.fit(X[mask], y[mask])
        return clf.predict_proba(X[is_test])[:, 1]

    p_old = fit(~is_test & old.to_numpy())
    p_full = fit(~is_test)

    bands = pd.cut(df.mover_elo[is_test], [0, 2000, 2300, 2600, 2800, 4000],
                   labels=["<2000", "2000-2300", "2300-2600", "2600-2800", "2800+"])
    y_te = y[is_test]
    out = {}
    print(f"test: {is_test.sum()} positions | old train: {(~is_test & old.to_numpy()).sum()} "
          f"| full train: {(~is_test).sum()}\n")
    print(f"  {'band':10s} {'n':>6s}   {'AUC old':>8s} {'AUC full':>9s} {'delta':>7s}"
          f"   {'Brier old':>9s} {'Brier full':>10s}")
    for b in bands.cat.categories:
        sel = (bands == b).to_numpy()
        if sel.sum() < 100 or y_te[sel].std() == 0:
            continue
        a_o = roc_auc_score(y_te[sel], p_old[sel])
        a_f = roc_auc_score(y_te[sel], p_full[sel])
        b_o = brier_score_loss(y_te[sel], p_old[sel])
        b_f = brier_score_loss(y_te[sel], p_full[sel])
        out[str(b)] = {"n": int(sel.sum()), "auc_old": a_o, "auc_full": a_f,
                       "delta_auc": a_f - a_o, "brier_old": b_o, "brier_full": b_f}
        print(f"  {b:10s} {sel.sum():6d}   {a_o:8.4f} {a_f:9.4f} {a_f-a_o:+7.4f}"
              f"   {b_o:9.4f} {b_f:10.4f}")

    json.dump(out, open(ROOT / "results" / "23_band_value.json", "w"), indent=1)
    print("\nwrote results/23_band_value.json")


if __name__ == "__main__":
    main()
