"""Exp 05 — dynamic concept mining on Leela (Schut et al. §4.1.2, open-weights).

For each machine-unique position (from exp 03, else the 4 Schut prototypes):
  1. Roll out Leela's CHOSEN line (repeatedly take the top policy move, depth T)
     and two SUBPAR lines (start with the 2nd/3rd policy move, then top policy).
  2. Embed every state along each line: residual stream at --layer, mean-pooled
     over the 64 squares -> 768-d vectors.
  3. Solve the paper's LP (min ||v||_1 s.t. v separates chosen from subpar at
     every step) -> one candidate concept vector per position.
  4. Filter by GENERALIZATION: v must also separate chosen/subpar rollouts on
     other positions it never saw (proxy for the paper's teachability filter).
  5. Cluster surviving vectors (cosine); for each cluster retrieve top-scoring
     PROTOTYPE positions from the real-games corpus and render them as boards.

Run inside the `leela` conda env (python 3.11, leela-interp installed):
    python experiments/05_leela_concepts.py --layer 10 --depth 6 --n-positions 30
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import torch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from concept_mining import mine_concept  # noqa: E402

from leela_interp import Lc0Model, LeelaBoard  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "models" / "leela-weights" / "lc0.onnx"

SCHUT_FENS = [
    "r1bqk2r/ppp2pbp/3p1np1/3Pp3/2PnP3/P1N2N1P/1P3PP1/R1BQKB1R w KQkq - 0 9",
    "1k1r3r/1p1n1p2/p1p1pnp1/q1Pp4/3P1PPP/1PN5/P1Q1B3/1K1R3R w - - 0 21",
    "r5k1/1b2qpp1/p1prp2p/1pR5/1P1PBP2/4P2P/3Q2PK/R7 w - - 0 33",
    "3qkb1r/1p3pp1/2p1p1p1/r7/2p3P1/P1Q1P2P/3P1PB1/R3K2R w KQk - 0 18",
]


class Embedder:
    """Forward positions through Leela, capture one layer's residual stream."""

    def __init__(self, model: Lc0Model, layer: int):
        self.model = model
        self.name = f"encoder{layer}/ln2"

    def policy_top(self, fen: str, k: int = 3) -> list[str]:
        board = LeelaBoard.from_fen(fen)
        x = self.model.make_inputs([board])
        with torch.no_grad():
            logits = self.model(x)[0]
        probs = self.model.logits_to_probs([board], logits.clone())[0]
        return list(self.model.top_moves(board, probs, top_k=k).keys())

    def embed(self, fens: list[str], batch: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(fens), batch):
            boards = [LeelaBoard.from_fen(f) for f in fens[i:i + batch]]
            x = self.model.make_inputs(boards)
            with torch.no_grad(), self.model.capturing([self.name]) as acts:
                self.model(x)
            z = acts[self.name]                     # (B*64, 768) or (B, 64, 768)
            z = z.reshape(len(boards), 64, -1)
            out.append(z.mean(dim=1).cpu().numpy())  # mean-pool squares -> (B, 768)
        return np.concatenate(out)


def rollout(emb: Embedder, fen: str, first_uci: str | None, depth: int) -> list[str]:
    """Play forward: forced first move (if given), then Leela's top policy move."""
    import chess
    board = chess.Board(fen)
    fens = []
    for t in range(depth):
        if t == 0 and first_uci:
            mv = first_uci
        else:
            try:
                mv = emb.policy_top(board.fen(), k=1)[0]
            except Exception:
                break
        try:
            board.push(chess.Move.from_uci(mv))
        except Exception:
            break
        fens.append(board.fen())
        if board.is_game_over():
            break
    return fens


def separation(v: np.ndarray, zp: np.ndarray, zn: np.ndarray) -> float:
    """Fraction of (pos, neg) step pairs the vector orders correctly."""
    s = (zp @ v)[:, None] - (zn @ v)[None, :]
    return float((s > 0).mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", type=int, default=10)
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--n-positions", type=int, default=30)
    ap.add_argument("--corpus-sample", type=int, default=5000)
    ap.add_argument("--gen-threshold", type=float, default=0.65)
    args = ap.parse_args()

    # source positions: machine-unique from exp 03, else the Schut four
    dis = ROOT / "results" / "03_disagreements.csv"
    if dis.exists():
        df = pd.read_csv(dis)
        fens = df[df.machine_unique].sort_values("human_cost_cp", ascending=False).fen.tolist()
        print(f"exp03 machine-unique positions available: {len(fens)}")
        fens = fens[: args.n_positions]
    else:
        fens = SCHUT_FENS
        print("exp03 results not found — using the 4 Schut prototype positions")

    model = Lc0Model(str(WEIGHTS), device="cpu")   # MPS gives NaNs per repo README
    emb = Embedder(model, args.layer)

    # 1-3: rollouts -> embeddings -> LP per position
    packs, vectors = [], []
    for i, fen in enumerate(fens):
        try:
            top = emb.policy_top(fen, k=3)
            chosen = rollout(emb, fen, top[0], args.depth)
            subpar = []
            for alt in top[1:3]:
                subpar += rollout(emb, fen, alt, args.depth)
            if len(chosen) < 3 or len(subpar) < 3:
                continue
            zp, zn = emb.embed(chosen), emb.embed(subpar)
            v, slack = mine_concept(zp, zn)
            if np.abs(v).sum() < 1e-8:
                continue
            packs.append({"fen": fen, "zp": zp, "zn": zn})
            vectors.append(v / (np.linalg.norm(v) + 1e-12))
            print(f"[{i+1}/{len(fens)}] mined v: {int((np.abs(v)>1e-6).sum())} nonzeros, slack {slack:.2f}")
        except Exception as e:
            print(f"[{i+1}/{len(fens)}] failed: {type(e).__name__}: {e}")

    if not vectors:
        raise SystemExit("no vectors mined — check the smoke test")

    # 4: generalization filter — does v_i separate rollouts of OTHER positions?
    V = np.stack(vectors)
    n = len(V)
    gen = np.zeros(n)
    for i in range(n):
        scores = [separation(V[i], p["zp"], p["zn"]) for j, p in enumerate(packs) if j != i]
        gen[i] = float(np.mean(scores)) if scores else 0.0
    keep = np.flatnonzero(gen >= args.gen_threshold)
    print(f"\ngeneralization filter: {len(keep)}/{n} vectors survive (threshold {args.gen_threshold})")
    print("gen scores:", np.round(sorted(gen, reverse=True), 3).tolist())

    # 5: cluster survivors, retrieve prototypes from the games corpus
    corpus = pd.read_csv(ROOT / "data" / "positions.csv").sample(
        min(args.corpus_sample, 10**9), random_state=0)
    cache = ROOT / "results" / f"corpus_emb_L{args.layer}_{len(corpus)}.npy"
    if cache.exists():
        Z = np.load(cache)
    else:
        print(f"embedding {len(corpus)} corpus positions (cached after first run)...")
        Z = emb.embed(corpus.fen.tolist())
        np.save(cache, Z)

    # greedy cosine clustering
    clusters: list[list[int]] = []
    for i in keep[np.argsort(-gen[keep])]:
        for cl in clusters:
            if float(V[i] @ V[cl[0]]) > 0.6:
                cl.append(int(i))
                break
        else:
            clusters.append([int(i)])

    report = []
    for ci, cl in enumerate(clusters):
        v = V[cl].mean(axis=0)
        scores = Z @ v
        top_idx = np.argsort(-scores)[:8]
        report.append({
            "cluster": ci,
            "n_vectors": len(cl),
            "mean_generalization": round(float(gen[cl].mean()), 3),
            "source_fens": [packs[i]["fen"] for i in cl],
            "prototype_fens": corpus.iloc[top_idx].fen.tolist(),
            "prototype_scores": np.round(scores[top_idx], 3).tolist(),
        })

    out = ROOT / "results"
    np.savez(out / "05_concept_vectors.npz", V=V, gen=gen, keep=keep)
    (out / "05_concepts.json").write_text(json.dumps(report, indent=1))
    print(f"\n{len(clusters)} concept clusters -> {out/'05_concepts.json'}")
    for r in report:
        print(f"  cluster {r['cluster']}: {r['n_vectors']} vectors, gen {r['mean_generalization']}")


if __name__ == "__main__":
    main()
