"""Exp 16 — cluster all machine-unique positions into teachable concepts.

Re-runs the family analysis on the full 1,745-position set (the old one used 646),
then characterises each cluster along every axis we can measure:

  * nearest named motifs (cosine to the twelve puzzle-theme directions)
  * what piece moves, whether the move is quiet, which phase
  * how often real players at the board found it
  * how visible it is to simulated humans

Each family becomes a concept in the product, with prototypes to study and
positions to drill. Output: webapp/concepts.json
"""
import json
import pathlib
import sys

import chess
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "models" / "leela-interp" / "src"))
CACHE = ROOT / "results" / "emb_cache"
K = 8
THEMES = ["pin", "fork", "skewer", "discoveredAttack", "deflection", "attraction",
          "sacrifice", "quietMove", "defensiveMove", "clearance", "intermezzo", "exposedKing"]


def embed_all(fens: list[str]) -> np.ndarray:
    f = CACHE / "mu_all.npy"
    if f.exists():
        Z = np.load(f)
        if len(Z) == len(fens):
            return Z
    import importlib.util
    spec = importlib.util.spec_from_file_location("exp05", ROOT / "experiments" / "05_leela_concepts.py")
    exp05 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exp05)
    from leela_interp import Lc0Model
    model = Lc0Model(str(exp05.WEIGHTS), device="cpu")
    emb = exp05.Embedder(model, layer=10)
    Z = np.zeros((len(fens), 0))
    chunks = []
    for i in range(0, len(fens), 200):
        chunks.append(emb.embed(fens[i:i + 200]))
        print(f"embedded {min(i+200, len(fens))}/{len(fens)}")
    Z = np.concatenate(chunks)
    np.save(f, Z)
    return Z


def move_meta(fen: str, uci: str) -> dict:
    b = chess.Board(fen)
    mv = chess.Move.from_uci(uci)
    piece = b.piece_at(mv.from_square)
    npm = sum(len(b.pieces(pt, c)) for c in chess.COLORS
              for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN))
    # does the move retreat, advance, or move laterally, from the mover's view?
    fr, tr = chess.square_rank(mv.from_square), chess.square_rank(mv.to_square)
    d = (tr - fr) if b.turn else (fr - tr)
    return {
        "piece": chess.piece_name(piece.piece_type) if piece else "?",
        "capture": b.is_capture(mv),
        "check": b.gives_check(mv),
        "quiet": not (b.is_capture(mv) or b.gives_check(mv)),
        "phase": "endgame" if npm <= 6 else ("opening" if b.fullmove_number <= 12 else "middlegame"),
        "advance": d > 0, "retreat": d < 0,
        "pawn_move": piece is not None and piece.piece_type == chess.PAWN,
        "king_move": piece is not None and piece.piece_type == chess.KING,
        "toward_own_king": False,
    }


def name_family(f: dict) -> tuple[str, str]:
    """A descriptive name and one-line gloss from the family's measured signature."""
    m = dict(f["motifs"])
    top = f["motifs"][0][0]
    piece = max(f["pieces"], key=f["pieces"].get)
    quiet, pawn, retreat = f["quiet_frac"], f["pawn_frac"], f["retreat_frac"]
    endgame = f["phase"].get("endgame", 0) / max(f["n"], 1)

    if m.get("sacrifice", 0) > 0.3 and quiet > 0.75:
        return ("The unpaid sacrifice",
                "Material goes, and nothing comes back right away. No combination follows — "
                "the compensation is position, and it arrives later than a human is willing to wait.")
    if m.get("exposedKing", 0) > 0.35:
        return ("Walking into the fire",
                "Moves that expose or advance near a king — the engine's own, or its opponent's — "
                "where human instinct says shelter first and ask questions later.")
    if top == "defensiveMove" or (m.get("defensiveMove", 0) > 0.15 and quiet > 0.75):
        return ("Cold defence",
                "Worse positions, defended precisely. Humans check out when the position looks lost; "
                "the engine keeps finding the move that makes winning hardest.")
    if pawn > 0.28 and quiet > 0.8:
        return ("The pawn that isn't urgent",
                "Quiet pawn moves that change the structure for reasons that pay off many moves "
                "later — nothing about them looks forcing.")
    if retreat > 0.3:
        return ("Backwards on purpose",
                "Retreats and regroupings that look like lost time. The piece is going somewhere "
                "better; humans see only the tempo it costs.")
    if endgame > 0.4:
        return ("Endgame against instinct",
                "Simplified positions where the natural human plan is measurably second-best.")
    if m.get("intermezzo", 0) > 0.18 or m.get("clearance", 0) > 0.18:
        return ("Order of operations",
                "The right moves in an order humans don't consider — an in-between move, or a "
                "clearance, inserted before the obvious continuation.")
    return (f"Quiet {piece} play",
            f"Unforcing {piece} moves whose justification sits outside the usual vocabulary.")


def main() -> None:
    from sklearn.cluster import KMeans

    mu = pd.read_csv(ROOT / "results" / "master_machine_unique.csv").reset_index(drop=True)
    mu = mu[mu.engine_best.astype(str).str.len() == 4].reset_index(drop=True)
    print(f"clustering {len(mu)} machine-unique positions")

    Z = embed_all(mu.fen.tolist())
    Zn = Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)
    km = KMeans(n_clusters=K, n_init=12, random_state=0).fit(Zn)
    mu["family"] = km.labels_

    base = np.load(CACHE / "puzzle_baseline.npy").mean(0)
    B = np.stack([np.load(CACHE / f"theme_{t}.npy").mean(0) - base for t in THEMES])
    Bn = B / np.linalg.norm(B, axis=1, keepdims=True)
    ctl = np.load(CACHE / "control.npy").mean(0)
    ctln = ctl / np.linalg.norm(ctl)

    meta = pd.DataFrame([move_meta(r.fen, r.engine_best) for r in mu.itertuples()])
    mu = pd.concat([mu, meta], axis=1)
    mu["real_found"] = mu.played_move == mu.engine_best

    fams = []
    for f in range(K):
        sel = mu[mu.family == f]
        Zf = Zn[mu.index[mu.family == f]]
        d = Zf.mean(0) - ctln
        d /= np.linalg.norm(d) + 1e-9
        cos = sorted(zip(THEMES, (Bn @ d).round(3).tolist()), key=lambda x: -x[1])
        fam = {
            "id": int(f), "n": int(len(sel)),
            "motifs": cos[:4],
            "pieces": sel.piece.value_counts().head(3).to_dict(),
            "phase": sel.phase.value_counts().to_dict(),
            "quiet_frac": round(float(sel.quiet.mean()), 3),
            "pawn_frac": round(float(sel.pawn_move.mean()), 3),
            "retreat_frac": round(float(sel.retreat.mean()), 3),
            "capture_frac": round(float(sel.capture.mean()), 3),
            "real_found": round(float(sel.real_found.mean()), 3),
            "mean_cost_cp": int(sel.human_cost_cp.mean()),
            "mean_p_human": round(float(sel.p_max.mean()), 4),
        }
        fam["name"], fam["gloss"] = name_family(fam)
        fams.append(fam)
        print(f"[{f}] {fam['name']:32s} n={fam['n']:4d} quiet={fam['quiet_frac']:.2f} "
              f"found={fam['real_found']*100:4.1f}%  {[m[0] for m in fam['motifs'][:3]]}")

    mu.to_csv(ROOT / "results" / "16_mu_families.csv", index=False)
    json.dump(fams, open(ROOT / "results" / "16_families.json", "w"), indent=1)
    print(f"\nwrote results/16_families.json and 16_mu_families.csv")


if __name__ == "__main__":
    main()
