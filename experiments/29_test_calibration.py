"""Exp 29 — calibrate the blind-spot test items.

The site's 12-position test should place a visitor on the rating staircase, and
"you scored 4/12 = 33%" is not a placement — different positions have different
difficulty, so the same raw score means different things depending on which
items you drew. The psychometric fix (item response theory in spirit): give
every test item a difficulty curve — P(a player of band b finds this move) —
then score a test session by maximum likelihood over bands.

The curves come from the exp-20 difficulty model, which is calibrated within
about a point on held-out games: for each drill position, predict find
probability with mover_elo set to each band's representative rating.

Output: webapp/test_items.json  {"<concept>:<idx>": [p1900, p2100, ..., p2900]}
plus a sanity table (per-band mean prediction vs the real staircase).
"""
import importlib.util
import json
import pathlib

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT = pathlib.Path(__file__).resolve().parents[1]
BAND_ELOS = [1900.0, 2100.0, 2300.0, 2500.0, 2700.0, 2900.0]
BAND_LABELS = ["1800-2000", "2000-2200", "2200-2400", "2400-2600", "2600-2800", "2800+"]
SEED = 0

spec = importlib.util.spec_from_file_location("exp20", ROOT / "experiments" / "20_difficulty_model.py")
exp20 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exp20)


def main() -> None:
    df = pd.read_csv(ROOT / "results" / "master_all.csv")
    df["found"] = (df.played_move == df.engine_best).astype(int)
    meta = pd.DataFrame([exp20.move_meta(r.fen, r.engine_best) for r in df.itertuples()])
    df = pd.concat([df.reset_index(drop=True), meta], axis=1)
    df = df[meta.notna().all(axis=1).values].reset_index(drop=True)

    concepts = json.load(open(ROOT / "webapp" / "concepts.json"))
    keys, fens = [], []
    for c in concepts:
        for i, pos in enumerate(c["drill"]):
            keys.append(f"{c['id']}:{i}")
            fens.append(pos["fen"])
    lookup = df.drop_duplicates("fen").set_index("fen")
    ok = [f in lookup.index for f in fens]
    print(f"{sum(ok)}/{len(fens)} drill positions found in master")

    # one scoring copy per band elo, all encoded together with the training rows
    subs = []
    for elo in BAND_ELOS:
        s = lookup.loc[[f for f, o in zip(fens, ok) if o]].reset_index()
        s["mover_elo"] = elo
        subs.append(s)
    combined = pd.concat([df] + subs, ignore_index=True)
    X_all = exp20.design(combined, ["surface", "engine", "maia", "elo"])
    X_train = X_all[:len(df)]
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                         max_leaf_nodes=15, l2_regularization=1.0,
                                         random_state=SEED)
    clf.fit(X_train, df["found"].to_numpy())

    n_items = sum(ok)
    items = {k: [] for k, o in zip(keys, ok) if o}
    live_keys = [k for k, o in zip(keys, ok) if o]
    off = len(df)
    for b, elo in enumerate(BAND_ELOS):
        preds = clf.predict_proba(X_all[off + b * n_items: off + (b + 1) * n_items])[:, 1]
        for k, p in zip(live_keys, preds):
            items[k].append(round(float(p), 4))

    # sanity: monotone in rating? and band means vs the real MU staircase
    mono = sum(all(b >= a - 0.02 for a, b in zip(v, v[1:])) for v in items.values())
    print(f"items rising (within 2pp slack) across bands: {mono}/{len(items)}")
    means = np.array(list(items.values())).mean(axis=0)
    real = [0.066, 0.130, 0.159, 0.170, 0.274, 0.569]
    print("\n  band        model-mean   real staircase (all MU)")
    for lab, m, r in zip(BAND_LABELS, means, real):
        print(f"  {lab:10s}   {m:6.3f}       {r:.3f}")

    json.dump({"band_labels": BAND_LABELS, "band_elos": BAND_ELOS,
               "staircase": real, "items": items},
              open(ROOT / "webapp" / "test_items.json", "w"))
    print(f"\nwrote webapp/test_items.json ({len(items)} items x {len(BAND_ELOS)} bands)")


if __name__ == "__main__":
    main()
