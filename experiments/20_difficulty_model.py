"""Exp 20 — can we predict human difficulty, and does the engine's representation
beat the obvious baseline?

Exp 19 showed Leela's embedding adds +0.062 AUC over surface chess features when
predicting whether the player at the board found the move. That test was missing
its most important control: **Maia**. Maia is a neural network trained specifically
to predict human moves. If the embedding adds nothing on top of Maia's own output,
then "the engine representation knows something about human difficulty" is not a
finding — it is a slower way of asking Maia.

Part A (n=1,745 machine-unique, cached embeddings): a ladder of feature sets, ending
with Maia + engine + surface as the strong baseline, then + embedding.

Part B (n=43,603, all mined positions): the usable model. No Leela embedding —
just what is cheap to compute — trained to predict whether a human at the board plays
the engine's best move. This is the scorer the trainer can actually use, so it is
checked for calibration, not only ranking.

Both parts split by game_id (GroupKFold): positions from the same game must never
straddle the train/test boundary.

Output: results/20_difficulty.json, results/20_position_difficulty.csv
"""
import json
import pathlib

import chess
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "results" / "emb_cache"
N_PC = 40
SEED = 0

MAIA_COLS = ["p_engine_move_1100", "p_engine_move_1400",
             "p_engine_move_1700", "p_engine_move_2000", "p_max", "p_slope"]
ENGINE_COLS = ["best_cp", "engine_margin", "human_cost_cp"]
SURF_NUM = ["quiet", "capture", "check", "pawn_move", "king_move",
            "advance", "retreat", "ply"]


# ── features ──────────────────────────────────────────────────────────────────
def move_meta(fen: str, uci: str) -> dict:
    """Everything a chess player can see without a neural network."""
    b = chess.Board(fen)
    try:
        mv = chess.Move.from_uci(uci)
    except ValueError:
        mv = None
    if mv is None or mv.from_square is None:
        return {}
    piece = b.piece_at(mv.from_square)
    npm = sum(len(b.pieces(pt, c)) for c in chess.COLORS
              for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN))
    fr, tr = chess.square_rank(mv.from_square), chess.square_rank(mv.to_square)
    d = (tr - fr) if b.turn else (fr - tr)
    legal = b.legal_moves.count()
    return {
        "piece": chess.piece_name(piece.piece_type) if piece else "?",
        "capture": b.is_capture(mv), "check": b.gives_check(mv),
        "quiet": not (b.is_capture(mv) or b.gives_check(mv)),
        "phase": "endgame" if npm <= 6 else ("opening" if b.fullmove_number <= 12 else "middlegame"),
        "advance": d > 0, "retreat": d < 0,
        "pawn_move": piece is not None and piece.piece_type == chess.PAWN,
        "king_move": piece is not None and piece.piece_type == chess.KING,
        "n_legal": legal, "in_check": b.is_check(),
    }


def block(df: pd.DataFrame, kind: str) -> np.ndarray:
    if kind == "surface":
        cat = OneHotEncoder(sparse_output=False, handle_unknown="ignore") \
            .fit_transform(df[["piece", "phase"]].astype(str))
        num = df[SURF_NUM + ["n_legal", "in_check"]].astype(float).to_numpy()
        return np.hstack([cat, num])
    if kind == "maia":
        return df[MAIA_COLS].astype(float).fillna(0).to_numpy()
    if kind == "engine":
        return df[ENGINE_COLS].astype(float).fillna(0).to_numpy()
    if kind == "elo":
        return df[["mover_elo"]].astype(float).fillna(1500).to_numpy()
    raise ValueError(kind)


def design(df: pd.DataFrame, kinds: list[str], emb: np.ndarray | None = None) -> np.ndarray:
    parts = [block(df, k) for k in kinds if k != "embed"]
    if "embed" in kinds:
        parts.append(emb)
    return np.hstack(parts)


# ── evaluation ────────────────────────────────────────────────────────────────
def cv_score(X, y, groups, model="logit", n_splits=5):
    """Grouped CV by game. Returns mean AUC, sd, and out-of-fold predictions."""
    gkf = GroupKFold(n_splits=n_splits)
    aucs, oof = [], np.zeros(len(y))
    for tr, te in gkf.split(X, y, groups):
        if model == "logit":
            clf = make_pipeline(StandardScaler(),
                                LogisticRegression(max_iter=3000, C=0.5))
        else:
            clf = HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.06, max_leaf_nodes=15,
                l2_regularization=1.0, random_state=SEED)
        clf.fit(X[tr], y[tr])
        p = clf.predict_proba(X[te])[:, 1]
        oof[te] = p
        aucs.append(roc_auc_score(y[te], p))
    return float(np.mean(aucs)), float(np.std(aucs)), oof


def part_a() -> dict:
    print("=" * 70)
    print("PART A — does the embedding survive a Maia control? (machine-unique only)")
    print("=" * 70)
    mu = pd.read_csv(ROOT / "results" / "16_mu_families.csv")
    Z = np.load(CACHE / "mu_all.npy")
    assert len(Z) == len(mu), (len(Z), len(mu))

    meta = pd.DataFrame([move_meta(r.fen, r.engine_best) for r in mu.itertuples()])
    for c in meta.columns:
        if c not in mu.columns:
            mu[c] = meta[c].values
        else:
            mu[c] = meta[c].values          # recompute consistently
    y = mu["real_found"].astype(int).to_numpy()
    groups = mu["game_id"].astype(str).to_numpy()
    print(f"n={len(mu)}  found rate={y.mean():.3f}  "
          f"{mu.game_id.nunique()} distinct games\n")

    Zn = Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)
    emb = PCA(n_components=N_PC, random_state=SEED).fit_transform(Zn)

    ladder = [
        ("surface only", ["surface"]),
        ("Maia only", ["maia"]),
        ("engine only", ["engine"]),
        ("embedding only", ["embed"]),
        ("surface + engine", ["surface", "engine"]),
        ("surface + engine + Maia", ["surface", "engine", "maia"]),
        ("surface + engine + Maia + elo", ["surface", "engine", "maia", "elo"]),
        ("  ...+ EMBEDDING", ["surface", "engine", "maia", "elo", "embed"]),
    ]
    out = {}
    base_key = "surface + engine + Maia + elo"
    for name, kinds in ladder:
        X = design(mu, kinds, emb)
        m, s, _ = cv_score(X, y, groups)
        out[name.strip()] = {"auc": m, "sd": s, "n_features": X.shape[1]}
        print(f"  {name:32s} AUC={m:.3f} ± {s:.3f}   ({X.shape[1]} features)")

    # Fair-comparison sweep: adding 40 PCs to 246 positives can lose on
    # dimensionality alone, which would be a fact about sample size, not about
    # the embedding. Vary the width, and test with and without mover_elo (which
    # is a property of the player, not the position).
    print("\n  dimensionality sweep — is the drop just overfitting?")
    sweep = {}
    for npc in (2, 5, 10, 20, 40):
        e_k = PCA(n_components=npc, random_state=SEED).fit_transform(Zn)
        for tag, kinds in [("position-only baseline", ["surface", "engine", "maia"]),
                           ("+ elo", ["surface", "engine", "maia", "elo"])]:
            m, s_, _ = cv_score(design(mu, kinds + ["embed"], e_k), y, groups)
            base = out["surface + engine + Maia" if tag == "position-only baseline"
                       else "surface + engine + Maia + elo"]["auc"]
            sweep[f"{tag} + {npc}PC"] = {"auc": m, "sd": s_, "gain": m - base}
            print(f"    {tag:24s} + {npc:2d} PCs   AUC={m:.3f}  ({m - base:+.3f})")
    out["_sweep"] = sweep
    best_gain = max(v["gain"] for v in sweep.values())
    out["_best_embedding_gain_any_width"] = best_gain
    print(f"\n  best gain at any width: {best_gain:+.3f}")

    gain = out["...+ EMBEDDING"]["auc"] - out[base_key]["auc"]
    print(f"\n  embedding's gain over the full non-embedding baseline: {gain:+.3f}")
    verdict = ("the embedding survives the Maia control" if best_gain > 0.01 else
               "the embedding does NOT survive the Maia control at any width")
    print(f"  -> {verdict}")
    out["_embedding_gain_over_baseline"] = gain
    out["_verdict"] = verdict
    return out


def part_b() -> tuple[dict, pd.DataFrame]:
    print("\n" + "=" * 70)
    print("PART B — a usable difficulty scorer over all mined positions")
    print("=" * 70)
    df = pd.read_csv(ROOT / "results" / "master_all.csv")
    df["found"] = (df.played_move == df.engine_best).astype(int)
    meta = pd.DataFrame([move_meta(r.fen, r.engine_best) for r in df.itertuples()])
    df = pd.concat([df.reset_index(drop=True), meta], axis=1)
    df = df[meta.notna().all(axis=1).values].reset_index(drop=True)

    y = df["found"].to_numpy()
    groups = df["game_id"].astype(str).to_numpy()
    print(f"n={len(df)}  found rate={y.mean():.3f}  {df.game_id.nunique()} games\n")

    res = {}
    for name, kinds in [("surface only", ["surface"]),
                        ("Maia only", ["maia"]),
                        ("surface + engine", ["surface", "engine"]),
                        ("everything cheap", ["surface", "engine", "maia", "elo"])]:
        X = design(df, kinds)
        m, s, oof = cv_score(X, y, groups, model="gbm")
        res[name] = {"auc": m, "sd": s}
        print(f"  {name:24s} AUC={m:.3f} ± {s:.3f}")
        if name == "everything cheap":
            best_oof = oof

    brier = brier_score_loss(y, best_oof)
    frac, mean_pred = calibration_curve(y, best_oof, n_bins=10, strategy="quantile")
    print(f"\n  Brier score {brier:.4f} (lower is better; "
          f"always predicting the base rate gives {y.mean() * (1 - y.mean()):.4f})")
    print("\n  calibration — predicted vs actual find-rate, by decile")
    for p, a in zip(mean_pred, frac):
        bar = "#" * int(a * 40)
        print(f"    predicted {p:5.1%}   actual {a:5.1%}  {bar}")

    mu_mask = df.machine_unique.astype(bool).to_numpy()
    print(f"\n  mean predicted find-rate:  ordinary {best_oof[~mu_mask].mean():.1%}   "
          f"machine-unique {best_oof[mu_mask].mean():.1%}")
    print(f"  actual:                    ordinary {y[~mu_mask].mean():.1%}   "
          f"machine-unique {y[mu_mask].mean():.1%}")

    res["_brier"] = float(brier)
    res["_base_rate"] = float(y.mean())
    res["_calibration"] = [{"predicted": float(p), "actual": float(a)}
                           for p, a in zip(mean_pred, frac)]
    res["_pred_mu"] = float(best_oof[mu_mask].mean())
    res["_pred_ordinary"] = float(best_oof[~mu_mask].mean())

    scored = df[["fen", "engine_best", "game_id", "machine_unique", "found"]].copy()
    scored["predicted_find_rate"] = best_oof
    return res, scored


def part_c(scored: pd.DataFrame) -> dict:
    """Score the trainer's positions at a fixed rating.

    The CV model uses mover_elo, which is a property of the original player and
    meaningless for someone using the trainer. So refit on everything and ask a
    counterfactual instead: how often would a 1900-rated player find this move?
    That matches the rating band the trainer already quotes in its feedback.
    """
    print("\n" + "=" * 70)
    print("PART C — scoring the trainer's positions at a fixed rating")
    print("=" * 70)
    df = pd.read_csv(ROOT / "results" / "master_all.csv")
    df["found"] = (df.played_move == df.engine_best).astype(int)
    meta = pd.DataFrame([move_meta(r.fen, r.engine_best) for r in df.itertuples()])
    df = pd.concat([df.reset_index(drop=True), meta], axis=1)
    df = df[meta.notna().all(axis=1).values].reset_index(drop=True)

    kinds = ["surface", "engine", "maia", "elo"]
    concepts = json.load(open(ROOT / "webapp" / "concepts.json"))

    # Collect every trainer position, then build the design matrix for training and
    # scoring rows *together* — block() fits its one-hot encoder per call, so a
    # separately-encoded batch would not line up with the fitted model's columns.
    slots, fens = [], []
    for c in concepts:
        for slot in ("study", "drill"):
            for pos in c[slot]:
                slots.append((c, pos))
                fens.append(pos["fen"])
    lookup = df.drop_duplicates("fen").set_index("fen")
    present = [f in lookup.index for f in fens]
    sub = lookup.loc[[f for f, ok in zip(fens, present) if ok]].reset_index()
    sub["mover_elo"] = 1900.0

    combined = pd.concat([df, sub], ignore_index=True)
    X_all = design(combined, kinds)
    X_train, X_score = X_all[:len(df)], X_all[len(df):]

    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                         max_leaf_nodes=15, l2_regularization=1.0,
                                         random_state=SEED)
    clf.fit(X_train, df["found"].to_numpy())
    preds = clf.predict_proba(X_score)[:, 1]

    by_concept, k = {}, 0
    for (c, pos), ok in zip(slots, present):
        if not ok:
            continue
        pos["predicted_find_1900"] = round(float(preds[k]), 4)
        by_concept.setdefault(c["label"], []).append(float(preds[k]))
        k += 1
    per_concept = {}
    for c in concepts:
        vals = by_concept.get(c["label"], [])
        per_concept[c["label"]] = round(float(np.mean(vals)), 4) if vals else None
        c["signature"]["predicted_find_1900"] = per_concept[c["label"]]
    json.dump(concepts, open(ROOT / "webapp" / "concepts.json", "w"))

    hit, miss = sum(present), len(present) - sum(present)
    print(f"  scored {hit} trainer positions ({miss} not found in master_all)")
    print("\n  predicted find-rate at 1900, by group (vs observed over the board):")
    for c in concepts:
        obs = c["signature"]["found_by_real_players"]
        pc = per_concept[c["label"]]
        print(f"    {c['label']:11s} predicted {pc:.1%}   observed {obs:.1%}")
    return {"per_concept_predicted_find_1900": per_concept,
            "positions_scored": hit, "positions_unmatched": miss}


def main() -> None:
    a = part_a()
    b, scored = part_b()
    c = part_c(scored)
    json.dump({"part_a_embedding_vs_maia": a, "part_b_difficulty_model": b,
               "part_c_trainer_scores": c},
              open(ROOT / "results" / "20_difficulty.json", "w"), indent=1)
    scored.to_csv(ROOT / "results" / "20_position_difficulty.csv", index=False)
    print("\nwrote results/20_difficulty.json and results/20_position_difficulty.csv")


if __name__ == "__main__":
    main()
