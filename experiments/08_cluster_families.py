"""Exp 08 — group the machine-unique positions into candidate pattern families.

K-means over Leela latent embeddings (reusing exp 07's cache), enriched with:
  * nearest human-motif directions (soft labels from exp 07's basis)
  * chess metadata: piece moved by the engine's choice, capture?, check?, phase
  * how often REAL humans found the move (from played_move)

Output: results/08_families.json + results/families.html (board gallery per family)
"""
import json
import pathlib
import sys

import chess
import chess.svg
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
K = 8


def meta(fen: str, uci: str) -> dict:
    b = chess.Board(fen)
    mv = chess.Move.from_uci(uci)
    piece = b.piece_at(mv.from_square)
    npm = sum(len(b.pieces(pt, c)) for c in chess.COLORS
              for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN))
    return {
        "piece": chess.piece_name(piece.piece_type) if piece else "?",
        "capture": b.is_capture(mv),
        "check": b.gives_check(mv),
        "quiet": not (b.is_capture(mv) or b.gives_check(mv)),
        "pawn_move": piece is not None and piece.piece_type == chess.PAWN,
        "phase": "endgame" if npm <= 6 else ("opening" if b.fullmove_number <= 10 else "middlegame"),
    }


def main() -> None:
    from sklearn.cluster import KMeans
    cache = ROOT / "results" / "emb_cache"
    mu = pd.read_csv(ROOT / "results" / "master_machine_unique.csv").reset_index(drop=True)
    Z = np.load(cache / "mu.npy")
    assert len(Z) == len(mu), (len(Z), len(mu))
    Zn = Z / np.linalg.norm(Z, axis=1, keepdims=True)

    km = KMeans(n_clusters=K, n_init=10, random_state=0).fit(Zn)
    mu["family"] = km.labels_

    # motif soft-labels from exp07 basis
    comp = json.load(open(ROOT / "results" / "07_composition.json"))
    themes = comp["themes"]
    B = []
    base = np.load(cache / "puzzle_baseline.npy").mean(0)
    for t in themes:
        B.append(np.load(cache / f"theme_{t}.npy").mean(0) - base)
    B = np.stack(B)
    Bn = B / np.linalg.norm(B, axis=1, keepdims=True)
    ctl_mean = np.load(cache / "control.npy").mean(0)

    md = pd.DataFrame([meta(r.fen, r.engine_best) for r in mu.itertuples()])
    mu = pd.concat([mu, md], axis=1)
    mu["real_found"] = mu.played_move == mu.engine_best

    fams = []
    for f in range(K):
        sel = mu[mu.family == f]
        Zf = Zn[mu.index[mu.family == f]]
        d = Zf.mean(0) - ctl_mean / np.linalg.norm(ctl_mean)
        cos = (Bn @ (d / np.linalg.norm(d))).round(3)
        top_motifs = sorted(zip(themes, cos.tolist()), key=lambda x: -x[1])[:3]
        fams.append({
            "family": int(f), "n": int(len(sel)),
            "quiet_frac": round(float(sel.quiet.mean()), 2),
            "pawn_frac": round(float(sel.pawn_move.mean()), 2),
            "piece_top": sel.piece.value_counts().head(3).to_dict(),
            "phase_top": sel.phase.value_counts().head(2).to_dict(),
            "real_found_rate": round(float(sel.real_found.mean()), 3),
            "nearest_motifs": top_motifs,
            "sample_fens": sel.sort_values("human_cost_cp", ascending=False).head(4)[["fen", "engine_best", "human_top_2000"]].to_dict("records"),
        })
        print(f"family {f}: n={len(sel)} quiet={fams[-1]['quiet_frac']} pieces={fams[-1]['piece_top']} motifs={top_motifs}")

    json.dump(fams, open(ROOT / "results" / "08_families.json", "w"), indent=2)
    mu.to_csv(ROOT / "results" / "08_mu_with_families.csv", index=False)

    # gallery
    css = ("body{font-family:Georgia,serif;max-width:60rem;margin:2rem auto;background:#faf6ee;color:#2a2118}"
           ".fam{border-top:2px solid #8c5a2b;margin-top:2rem;padding-top:1rem}"
           ".boards{display:flex;flex-wrap:wrap;gap:1rem}.b{text-align:center;font-size:.8rem}"
           "svg{width:280px;height:auto;border:1px solid #ccc}")
    html = [f"<title>Machine-unique pattern families (k={K})</title><style>{css}</style>",
            f"<h1>646 machine-unique positions, {K} candidate families</h1>"]
    for fam in fams:
        html.append(f'<div class="fam"><h2>Family {fam["family"]} — n={fam["n"]}</h2>'
                    f'<p>quiet-move share {fam["quiet_frac"]}, real humans found {fam["real_found_rate"]*100:.0f}%, '
                    f'pieces {fam["piece_top"]}, nearest motifs {fam["nearest_motifs"]}</p><div class="boards">')
        for s in fam["sample_fens"]:
            b = chess.Board(s["fen"])
            mv = chess.Move.from_uci(s["engine_best"])
            svg = chess.svg.board(b, size=280, arrows=[chess.svg.Arrow(mv.from_square, mv.to_square, color="#15781B")],
                                  lastmove=None)
            html.append(f'<div class="b">{svg}engine: {b.san(mv)} · humans: {chess.Board(s["fen"]).san(chess.Move.from_uci(s["human_top_2000"])) if s["human_top_2000"] else "?"}</div>')
        html.append("</div></div>")
    (ROOT / "results" / "families.html").write_text("\n".join(html))
    print(f"\nwrote results/08_families.json + families.html")


if __name__ == "__main__":
    main()
