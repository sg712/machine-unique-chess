"""Exp 26 — why is the engine's move invisible? An interpretable contrast study.

Everything so far asked "where do engines and humans disagree" through embeddings.
This asks it through plain chess language. Two groups with IDENTICAL stakes —
the engine's move is >=100cp better than the human favourite in both — differing
only in visibility:

    INVISIBLE  p_max <= 0.05   (machine-unique; real players find 18%)
    VISIBLE    p_max >= 0.30   (real players find 60%)

Every position gets ~25 hand-crafted, human-readable features of the engine's
move. Three analyses:
  1. per-feature enrichment (invisible rate / visible rate), with a
     dose-response check across the p_max spectrum — real signals should
     trend monotonically through the in-between group
  2. L2 logistic regression — odds ratios, and how separable the groups are
     from readable features alone
  3. a depth-3 decision tree, printed as rules

Output: results/26_why_invisible.json
"""
import json
import pathlib

import chess
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier, export_text

ROOT = pathlib.Path(__file__).resolve().parents[1]
VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5,
       chess.QUEEN: 9, chess.KING: 0}


def exchange_balance(board: chess.Board, sq: int, side: bool) -> int:
    """Crude static exchange: attackers minus defenders count on sq, from the
    perspective of `side` being captured there. Positive = piece is en prise."""
    return len(board.attackers(not side, sq)) - len(board.attackers(side, sq))


def features(fen: str, uci: str) -> dict | None:
    b = chess.Board(fen)
    try:
        mv = chess.Move.from_uci(uci)
    except ValueError:
        return None
    if mv not in b.legal_moves:
        return None
    us = b.turn
    piece = b.piece_at(mv.from_square)
    if piece is None:
        return None
    pval = VAL[piece.piece_type]
    cap = b.piece_at(mv.to_square)
    capval = VAL[cap.piece_type] if cap else 0

    fr, tr = chess.square_rank(mv.from_square), chess.square_rank(mv.to_square)
    ff, tf = chess.square_file(mv.from_square), chess.square_file(mv.to_square)
    fwd = (tr - fr) if us else (fr - tr)

    our_king = b.king(us)
    their_king = b.king(not us)

    # pre-move facts
    from_attacked = b.is_attacked_by(not us, mv.from_square)
    to_attacked = b.is_attacked_by(not us, mv.to_square)
    to_attacked_by_pawn = any(b.piece_at(s) and b.piece_at(s).piece_type == chess.PAWN
                              for s in b.attackers(not us, mv.to_square))
    n_legal = b.legal_moves.count()
    our_mat = sum(VAL[p.piece_type] for p in b.piece_map().values() if p.color == us)
    their_mat = sum(VAL[p.piece_type] for p in b.piece_map().values() if p.color != us)
    tension = sum(1 for m in b.legal_moves if b.is_capture(m))
    gives_check = b.gives_check(mv)

    # own-king shelter pressure before/after (opponent attacks into king ring)
    def king_pressure(bd, king_sq, attacker):
        if king_sq is None:
            return 0
        ring = chess.SquareSet(chess.BB_KING_ATTACKS[king_sq])
        return sum(len(bd.attackers(attacker, s)) for s in ring)

    kp_before = king_pressure(b, our_king, not us)

    b.push(mv)
    # post-move facts
    landed_en_prise = exchange_balance(b, mv.to_square, us) > 0
    landed_att_by_lesser = any(
        VAL[b.piece_at(s).piece_type] < max(pval, 1)
        for s in b.attackers(not us, mv.to_square) if b.piece_at(s))
    kp_after = king_pressure(b, b.king(us), not us)
    # does the move create a threat on a bigger or undefended piece?
    creates_threat = False
    for s in b.attacks(mv.to_square):
        tgt = b.piece_at(s)
        if tgt and tgt.color != us and (VAL[tgt.piece_type] > pval
                                        or not b.attackers(not us, s)):
            creates_threat = True
            break
    their_replies = b.legal_moves.count()
    b.pop()

    npm = sum(len(b.pieces(pt, c)) for c in chess.COLORS
              for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN))
    return {
        "piece_pawn": piece.piece_type == chess.PAWN,
        "piece_minor": piece.piece_type in (chess.KNIGHT, chess.BISHOP),
        "piece_rook": piece.piece_type == chess.ROOK,
        "piece_queen": piece.piece_type == chess.QUEEN,
        "piece_king": piece.piece_type == chess.KING,
        "is_capture": cap is not None,
        "captures_smaller": cap is not None and capval < pval,
        "gives_check": gives_check,
        "quiet": cap is None and not gives_check,
        "retreat": fwd < 0,
        "deep_retreat": fwd <= -2,
        "advance2plus": fwd >= 2,
        "sideways": fwd == 0,
        "long_move": max(abs(tr - fr), abs(tf - ff)) >= 3,
        "to_rim": tf in (0, 7) or tr in (0, 7),
        "escapes_attack": from_attacked and not to_attacked,
        "into_attack": (not from_attacked) and to_attacked,
        "to_pawn_attacked": to_attacked_by_pawn and pval > 1,
        "lands_en_prise": landed_en_prise,
        "att_by_lesser_after": landed_att_by_lesser,
        "offers_material": (landed_en_prise or landed_att_by_lesser) and capval < pval,
        "creates_threat": creates_threat,
        "weakens_own_king": kp_after > kp_before,
        "king_walk": piece.piece_type == chess.KING and npm > 6,
        "toward_their_king": their_king is not None and
            chess.square_distance(mv.to_square, their_king) <
            chess.square_distance(mv.from_square, their_king),
        "restricting": their_replies < n_legal * 0.85,
        "material_down": our_mat < their_mat - 1,
        "endgame": npm <= 6,
        "many_options": n_legal >= 35,
        "high_tension": tension >= 6,
    }


def main() -> None:
    d = pd.read_csv(ROOT / "results" / "master_all.csv")
    big = d[d.human_cost_cp >= 100].copy()
    big["grp"] = np.where(big.p_max <= 0.05, "invisible",
                  np.where(big.p_max >= 0.30, "visible", "mid"))
    print(f"{len(big)} positions with >=100cp at stake "
          f"({(big.grp == 'invisible').sum()} invisible, "
          f"{(big.grp == 'mid').sum()} mid, {(big.grp == 'visible').sum()} visible)")

    feats = [features(r.fen, r.engine_best) for r in big.itertuples()]
    ok = [f is not None for f in feats]
    big = big[ok].reset_index(drop=True)
    F = pd.DataFrame([f for f in feats if f is not None]).astype(float)
    names = list(F.columns)
    print(f"{len(F)} rows featurised, {len(names)} features\n")

    # 1 — enrichment with dose response
    print("=== enrichment: share of positions with feature, by visibility ===")
    print(f"{'feature':22s} {'invis':>7s} {'mid':>7s} {'visible':>7s}   ratio  dose-monotone")
    enrich = {}
    for c in names:
        iv = F.loc[big.grp == "invisible", c].mean()
        md = F.loc[big.grp == "mid", c].mean()
        vs = F.loc[big.grp == "visible", c].mean()
        ratio = iv / vs if vs > 0.002 else float("inf")
        mono = (iv >= md >= vs) or (iv <= md <= vs)
        enrich[c] = {"invisible": iv, "mid": md, "visible": vs,
                     "ratio": ratio if np.isfinite(ratio) else None, "monotone": bool(mono)}
    for c, e in sorted(enrich.items(),
                       key=lambda kv: -(kv[1]["ratio"] or 99)):
        r = e["ratio"]
        print(f"{c:22s} {e['invisible']:7.1%} {e['mid']:7.1%} {e['visible']:7.1%}   "
              f"{('%5.2f' % r) if r else '  inf'}  {'yes' if e['monotone'] else 'NO'}")

    # 2 — logistic regression on the two extreme groups
    two = big.grp != "mid"
    X = F[two.values].to_numpy()
    y = (big.grp[two] == "invisible").astype(int).to_numpy()
    groups = big.game_id[two].astype(str).to_numpy()
    aucs = []
    for tr, te in GroupKFold(5).split(X, y, groups):
        clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))
        clf.fit(X[tr], y[tr])
        aucs.append(roc_auc_score(y[te], clf.predict_proba(X[te])[:, 1]))
    print(f"\n=== logistic: invisible vs visible, grouped 5-fold "
          f"AUC = {np.mean(aucs):.3f} ± {np.std(aucs):.3f} ===")
    final = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5)).fit(X, y)
    coefs = final[-1].coef_[0]
    order = np.argsort(-np.abs(coefs))
    print(f"{'feature':22s} {'odds ratio':>10s}")
    odds = {}
    for i in order:
        odds[names[i]] = float(np.exp(coefs[i]))
        if abs(coefs[i]) > 0.10:
            print(f"{names[i]:22s} {np.exp(coefs[i]):10.2f}")

    # 3 — shallow tree as rules
    tree = DecisionTreeClassifier(max_depth=3, min_samples_leaf=150, random_state=0).fit(X, y)
    rules = export_text(tree, feature_names=names, decimals=0, show_weights=True)
    print("\n=== depth-3 tree (class 1 = invisible) ===")
    print(rules)

    # 4 — within the invisible group: what do strong humans still find?
    inv = big.grp == "invisible"
    Xi, yi = F[inv.values].to_numpy(), big.real_found[inv].astype(int).to_numpy()
    fr = {}
    print("=== within invisible: feature vs found-by-real-player ===")
    for j, c in enumerate(names):
        has, hasnt = yi[Xi[:, j] > 0], yi[Xi[:, j] == 0]
        if len(has) >= 80 and len(hasnt) >= 80:
            fr[c] = {"found_with": float(has.mean()), "found_without": float(hasnt.mean()),
                     "n_with": int(len(has))}
    for c, e in sorted(fr.items(), key=lambda kv: kv[1]["found_with"]):
        print(f"{c:22s} found {e['found_with']:5.1%} with, {e['found_without']:5.1%} without  "
              f"(n={e['n_with']})")

    json.dump({"n": int(len(F)), "auc_logistic": float(np.mean(aucs)),
               "auc_sd": float(np.std(aucs)), "enrichment": enrich,
               "odds_ratios": odds, "tree_rules": rules, "invisible_found_by": fr},
              open(ROOT / "results" / "26_why_invisible.json", "w"), indent=1, default=float)
    print("\nwrote results/26_why_invisible.json")


if __name__ == "__main__":
    main()
