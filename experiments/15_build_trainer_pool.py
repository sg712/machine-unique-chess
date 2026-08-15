"""Exp 15 — build the trainer's position pool.

For each machine-unique position we precompute everything the product needs to
give instant, interesting feedback:

  * the engine's move and a short principal variation (Stockfish, depth 18)
  * the eval swing between the engine's move and the human favourite
  * Maia's human-move distribution at 1900, so we can tell a player how common
    their own choice was
  * a difficulty tier from how visible the move is to simulated humans

Output: webapp/pool.json
"""
import json
import pathlib

import chess
import chess.engine
import pandas as pd
from maia2 import inference, model

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE = ROOT / "models" / "stockfish-build" / "src" / "stockfish"
OUT = ROOT / "webapp" / "pool.json"
TARGET = 300
DEPTH = 18


def main() -> None:
    hc = pd.read_csv(ROOT / "results" / "hard_core.csv")
    hc = hc.sample(frac=1, random_state=5)
    print(f"hard-core pool: {len(hc)}")

    m = model.from_pretrained(type="rapid", device="auto")
    prepared = inference.prepare()
    engine = chess.engine.SimpleEngine.popen_uci(str(ENGINE))
    engine.configure({"Threads": 6, "Hash": 512})

    out = []
    try:
        for r in hc.itertuples():
            if len(str(r.engine_best)) != 4:
                continue
            b = chess.Board(r.fen)
            if b.is_check() or b.legal_moves.count() < 8:
                continue

            info = engine.analyse(b, chess.engine.Limit(depth=DEPTH), multipv=2)
            best = info[0]["pv"][0].uci()
            if best != r.engine_best:                      # unstable at higher depth
                continue
            pov = b.turn
            cp1 = info[0]["score"].pov(pov).score(mate_score=2000)
            cp2 = info[1]["score"].pov(pov).score(mate_score=2000)
            if cp1 - cp2 < 70:                             # second move nearly as good
                continue

            probs, _ = inference.inference_each(m, prepared, r.fen, 1900, 1900)
            top = sorted(probs.items(), key=lambda kv: -kv[1])[:5]
            p_best = probs.get(best, 0.0)

            pv, bb = [], b.copy()
            for mv in info[0]["pv"][:6]:
                pv.append({"uci": mv.uci(), "san": bb.san(mv)})
                bb.push(mv)

            out.append({
                "id": len(out) + 1,
                "fen": r.fen,
                "best": best,
                "pv": pv,
                "gap_cp": int(cp1 - cp2),
                "cost_cp": int(r.human_cost_cp) if pd.notna(r.human_cost_cp) else None,
                "human": [{"uci": u, "p": round(p, 4)} for u, p in top],
                "p_best": round(p_best, 4),
                "stm": "white" if pov else "black",
                "tier": 1 if p_best >= 0.02 else (2 if p_best >= 0.005 else 3),
                "quiet": not (b.is_capture(chess.Move.from_uci(best))
                              or b.gives_check(chess.Move.from_uci(best))),
            })
            if len(out) % 25 == 0:
                print(f"{len(out)}/{TARGET}")
            if len(out) >= TARGET:
                break
    finally:
        engine.quit()

    json.dump(out, open(OUT, "w"))
    tiers = pd.Series([p["tier"] for p in out]).value_counts().sort_index()
    print(f"\nwrote {OUT}: {len(out)} positions")
    print("tiers (1=easiest):", tiers.to_dict())
    print("quiet moves:", sum(p["quiet"] for p in out))


if __name__ == "__main__":
    main()
