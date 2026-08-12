"""Exp 03 — mine engine/human disagreements at scale.

For every position from real games (data/positions.csv):
  * Stockfish  -> best move + eval, and eval of the move humans actually favour
  * Maia-2     -> P(move) for simulated humans at several Elo levels

A position is a MACHINE-UNIQUE candidate when the engine's best move is clearly
best (large eval gap over the human favourite) yet no simulated human at ANY
level would play it. Those are the positions where engine knowledge is invisible
to human pattern-recognition — the raw material for concept mining.

Output: results/03_disagreements.csv (one row per position)
"""
import argparse
import pathlib

import chess
import chess.engine
import pandas as pd
from maia2 import inference, model

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE = ROOT / "models" / "stockfish-build" / "src" / "stockfish"
ELOS = [1100, 1400, 1700, 2000]


def cp(score: chess.engine.PovScore, pov: bool) -> float:
    """Centipawns from `pov`'s side, mates clamped."""
    return score.pov(pov).score(mate_score=2000)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--input", default=None, help="positions csv (default data/positions.csv)")
    ap.add_argument("--output", default="03_disagreements.csv")
    ap.add_argument("--depth", type=int, default=16)
    ap.add_argument("--gap", type=float, default=100.0, help="min centipawn gap to count as 'clearly best'")
    ap.add_argument("--pmax", type=float, default=0.05, help="max human prob to count as 'invisible'")
    args = ap.parse_args()

    positions = pd.read_csv(args.input or (ROOT / "data" / "positions.csv")).iloc[args.offset:args.offset + args.limit]
    m = model.from_pretrained(type="rapid", device="auto")
    prepared = inference.prepare()
    engine = chess.engine.SimpleEngine.popen_uci(str(ENGINE))
    engine.configure({"Threads": 6, "Hash": 512})
    limit = chess.engine.Limit(depth=args.depth)

    rows = []
    try:
        for i, r in enumerate(positions.itertuples(index=False), start=1):
            board = chess.Board(r.fen)
            pov = board.turn
            # engine's top 2 moves
            info = engine.analyse(board, limit, multipv=2)
            best_move = info[0]["pv"][0].uci()
            best_cp = cp(info[0]["score"], pov)
            second_cp = cp(info[1]["score"], pov) if len(info) > 1 else best_cp

            # human model across skill levels
            probs_by_elo, human_top = {}, {}
            for elo in ELOS:
                mp, _ = inference.inference_each(m, prepared, r.fen, elo, elo)
                probs_by_elo[elo] = mp.get(best_move, 0.0)
                human_top[elo] = max(mp, key=mp.get)

            # eval cost of the human favourite at the top level
            hm = human_top[max(ELOS)]
            if hm == best_move:
                human_cost = 0.0
            else:
                try:
                    hinfo = engine.analyse(board, limit, root_moves=[chess.Move.from_uci(hm)])
                    human_cost = best_cp - cp(hinfo["score"], pov)
                except Exception:
                    human_cost = float("nan")

            p_all = [probs_by_elo[e] for e in ELOS]
            rows.append({
                "fen": r.fen, "ply": r.ply, "game_id": r.game_id,
                "engine_best": best_move, "best_cp": best_cp,
                "engine_margin": best_cp - second_cp,
                "played_move": r.played_move,
                **{f"p_engine_move_{e}": round(probs_by_elo[e], 4) for e in ELOS},
                **{f"human_top_{e}": human_top[e] for e in ELOS},
                "human_cost_cp": round(human_cost, 1),
                "p_max": round(max(p_all), 4),
                "p_slope": round(probs_by_elo[ELOS[-1]] - probs_by_elo[ELOS[0]], 4),
                "machine_unique": bool(human_cost >= args.gap and max(p_all) <= args.pmax),
            })
            if i % 100 == 0:
                n_mu = sum(x["machine_unique"] for x in rows)
                print(f"{i}/{len(positions)} positions, {n_mu} machine-unique so far")
    finally:
        engine.quit()

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out / args.output, index=False)

    mu = df[df.machine_unique]
    print(f"\n=== {len(df)} positions analysed ===")
    print(f"machine-unique candidates: {len(mu)} ({100*len(mu)/max(1,len(df)):.1f}%)")
    print("\nmean P(engine best move) by simulated human level:")
    for e in ELOS:
        print(f"  {e}: {df[f'p_engine_move_{e}'].mean():.4f}   (machine-unique subset: {mu[f'p_engine_move_{e}'].mean() if len(mu) else float('nan'):.4f})")
    print(f"\nmean eval cost of the top human move: {df.human_cost_cp.mean():.1f} cp")
    print(f"positions where humans agree with engine at 2000: {(df.human_top_2000 == df.engine_best).mean()*100:.1f}%")
    print(f"\nwrote {out/args.output}")


if __name__ == "__main__":
    main()
