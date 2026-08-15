"""Exp 17 — turn the eight families into teachable concepts.

Each family gets a name and description authored from its measured signature
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

# Names and glosses authored from each family's measured signature. The evidence
# for each sits in `signature` on the output object, so a reader can check them.
NAMES = {
    0: ("The heavy-piece pause",
        "Queens and rooks making quiet, non-committal moves. Nothing is attacked and nothing is "
        "defended in the obvious sense — the piece simply stands better afterwards, and the "
        "position is easier to play for reasons that show up several moves later."),
    1: ("The unpaid sacrifice",
        "Material goes and no combination follows. This is the family humans fail hardest — the "
        "average human choice here costs five pawns of evaluation. The compensation is real but "
        "it arrives slowly, and a human wants to see the payoff before paying the price."),
    2: ("Order of operations",
        "The right ideas in an order nobody considers. A clearance or a pin inserted before the "
        "natural continuation, which changes what the natural continuation is worth. The single "
        "largest family, and the one where the human move costs least — these are near-misses."),
    3: ("Against the book",
        "Opening positions where the engine's preference diverges from what people actually play. "
        "Almost entirely knight and pawn moves in the first dozen moves, where human choice is "
        "driven by theory and habit rather than by the position in front of them."),
    4: ("The one with no name",
        "This family matches no named motif — its cosine to all twelve is zero or negative. It is "
        "also the most tactical of the eight and carries the joint-highest cost. Whatever the "
        "engine is seeing here, human chess vocabulary has no word for it."),
    5: ("Nothing happens",
        "The quietest family: 94% of the moves neither capture nor check, and barely one in "
        "twenty takes anything. Mostly endgames and late middlegames where the position looks "
        "settled and is not."),
    6: ("The long fuse",
        "Middlegame sacrifices, attractions and pins that set up a payoff far enough away that "
        "the connection is invisible. Related to the unpaid sacrifice, but sharper and always "
        "with pieces still on the board."),
    7: ("Walking into the fire",
        "By far the strongest king-exposure signal of the eight. Moves that open lines toward a "
        "king — often the engine's own — where human instinct is to shelter first and calculate "
        "afterwards. The smallest family, and one of the most alien."),
}


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
            name, gloss = NAMES[fid]
            concepts.append({
                "id": fid, "name": name, "gloss": gloss,
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
            print(f"[{fid}] {name:26s} study={len(picked[:N_STUDY])} drill={len(picked[N_STUDY:])}")
    finally:
        engine.quit()

    out = ROOT / "webapp" / "concepts.json"
    json.dump(concepts, open(out, "w"))
    print(f"\nwrote {out}: {len(concepts)} concepts, "
          f"{sum(len(c['study']) + len(c['drill']) for c in concepts)} positions")


if __name__ == "__main__":
    main()
