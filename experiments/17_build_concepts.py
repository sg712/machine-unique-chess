"""Exp 17 — turn the eight families into teachable concepts.

Each family gets a neutral label and a gloss assembled from its measured signature
(shown alongside, so nothing is hidden), a set of study prototypes with the
engine's line, and a set of drill positions with Maia's human-move distribution
for feedback.

Output: webapp/concepts.json
"""
import json
import pathlib

import chess
import chess.engine
import pandas as pd
from maia2 import inference, model

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE = ROOT / "models" / "stockfish-build" / "src" / "stockfish"
N_STUDY, N_DRILL, DEPTH = 4, 12, 18

# No names. The whole premise is that these groups are not covered by existing chess
# vocabulary — exp 18/19 show the clusters are soft regions in a continuous space, not
# discrete kinds — so a name would assert more than the data supports. Each group gets a
# neutral label and a gloss assembled purely from its measured signature, so every clause
# is checkable against `signature` on the output object.


def describe(fid: int, fam: dict) -> tuple[str, str]:
    phase = max(fam["phase"], key=fam["phase"].get)
    piece = max(fam["pieces"], key=fam["pieces"].get)
    quiet = round(fam["quiet_frac"] * 100)
    motif, cos = fam["motifs"][0]
    if cos <= 0.01:
        nearest = ("it has no measurable similarity to any of the twelve named motifs — "
                   f"the closest, {motif}, sits at {cos:.2f}")
    else:
        nearest = f"this group is closest to {motif} ({cos:.2f}), and only weakly"
    gloss = (
        f"{fam['n']} positions, mostly {phase}. {quiet}% of the moves are quiet — neither "
        f"capture nor check — and the piece moved is most often a {piece}. In the engine's "
        f"representation {nearest}. Real players at the board found these moves "
        f"{fam['real_found'] * 100:.1f}% of the time, losing an average of "
        f"{fam['mean_cost_cp']} centipawns by choosing otherwise."
    )
    return f"Concept {fid + 1}", gloss


def main() -> None:
    fams = {f["id"]: f for f in json.load(open(ROOT / "results" / "16_families.json"))}
    mu = pd.read_csv(ROOT / "results" / "16_mu_families.csv")

    m = model.from_pretrained(type="rapid", device="auto")
    prepared = inference.prepare()
    engine = chess.engine.SimpleEngine.popen_uci(str(ENGINE))
    engine.configure({"Threads": 6, "Hash": 512})

    concepts = []
    try:
        for fid in sorted(fams):
            fam = fams[fid]
            sel = mu[mu.family == fid].sample(frac=1, random_state=3)
            picked = []
            for r in sel.itertuples():
                if len(picked) >= N_STUDY + N_DRILL:
                    break
                b = chess.Board(r.fen)
                if b.is_check() or b.legal_moves.count() < 8:
                    continue
                info = engine.analyse(b, chess.engine.Limit(depth=DEPTH), multipv=2)
                best = info[0]["pv"][0].uci()
                if best != r.engine_best:
                    continue
                pov = b.turn
                cp1 = info[0]["score"].pov(pov).score(mate_score=2000)
                cp2 = info[1]["score"].pov(pov).score(mate_score=2000)
                if cp1 - cp2 < 70:
                    continue

                probs, _ = inference.inference_each(m, prepared, r.fen, 1900, 1900)
                top = sorted(probs.items(), key=lambda kv: -kv[1])[:6]

                pv, bb = [], b.copy()
                for mv in info[0]["pv"][:6]:
                    pv.append({"uci": mv.uci(), "san": bb.san(mv)})
                    bb.push(mv)

                picked.append({
                    "fen": r.fen, "best": best, "best_san": b.san(chess.Move.from_uci(best)),
                    "pv": pv, "gap_cp": int(cp1 - cp2),
                    "cost_cp": int(r.human_cost_cp) if pd.notna(r.human_cost_cp) else None,
                    "stm": "white" if pov else "black",
                    "human": [{"uci": u, "san": (b.san(chess.Move.from_uci(u))
                                                 if chess.Move.from_uci(u) in b.legal_moves else u),
                               "p": round(p, 4)} for u, p in top],
                    "p_best": round(probs.get(best, 0.0), 4),
                    "quiet": bool(r.quiet), "piece": r.piece, "phase": r.phase,
                })
            label, gloss = describe(fid, fam)
            concepts.append({
                "id": fid, "name": label, "label": label, "gloss": gloss,
                "signature": {
                    "positions": fam["n"],
                    "found_by_real_players": fam["real_found"],
                    "quiet_share": fam["quiet_frac"],
                    "avg_cost_cp": fam["mean_cost_cp"],
                    "top_motifs": fam["motifs"][:3],
                    "pieces": fam["pieces"],
                    "phase": fam["phase"],
                },
                "study": picked[:N_STUDY],
                "drill": picked[N_STUDY:N_STUDY + N_DRILL],
            })
            print(f"[{fid}] {label:12s} study={len(picked[:N_STUDY])} drill={len(picked[N_STUDY:])}")
    finally:
        engine.quit()

    out = ROOT / "webapp" / "concepts.json"
    json.dump(concepts, open(out, "w"))
    print(f"\nwrote {out}: {len(concepts)} concepts, "
          f"{sum(len(c['study']) + len(c['drill']) for c in concepts)} positions")


if __name__ == "__main__":
    main()
