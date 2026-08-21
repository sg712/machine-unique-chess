"""Exp 29 — triple the drill pool using the newly assigned positions.

Keeps every existing study and drill position (live progress is keyed on them)
and appends N_NEW engine-verified drills per concept from exp 28's assignments,
preferring positions with a clear centroid margin. Each new drill passes the
same checks as exp 17: not in check, >= 8 legal moves, Stockfish at depth 18
still picks the mined move with >= 70cp over second-best; Maia's 1900 move
distribution is attached. Signatures are recomputed over the enlarged families
(counts, find-rate, quiet share, cost, piece/phase mix); motif cosines stay from
exp 16. Glosses regenerate from the signature.

Output: webapp/concepts.json (run exp 20 afterwards to restamp predictions).
"""
import importlib.util
import json
import pathlib

import chess
import chess.engine
import pandas as pd
from maia2 import inference, model

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE = ROOT / "models" / "stockfish-build" / "src" / "stockfish"
N_NEW, DEPTH, MIN_MARGIN = 24, 18, 0.05

spec = importlib.util.spec_from_file_location("exp17", ROOT / "experiments" / "17_build_concepts.py")
exp17 = importlib.util.module_from_spec(spec); spec.loader.exec_module(exp17)
spec = importlib.util.spec_from_file_location("exp16", ROOT / "experiments" / "16_concept_families.py")
exp16 = importlib.util.module_from_spec(spec); spec.loader.exec_module(exp16)


def main() -> None:
    concepts = json.load(open(ROOT / "webapp" / "concepts.json"))
    fams16 = {f["id"]: f for f in json.load(open(ROOT / "results" / "16_families.json"))}
    old = pd.read_csv(ROOT / "results" / "16_mu_families.csv")
    new = pd.read_csv(ROOT / "results" / "28_mu_assignments.csv")
    meta = pd.DataFrame([exp16.move_meta(r.fen, r.engine_best) for r in new.itertuples()])
    new = pd.concat([new.reset_index(drop=True), meta], axis=1)
    used = {p["fen"] for c in concepts for p in c["study"] + c["drill"]}

    m = model.from_pretrained(type="rapid", device="auto")
    prepared = inference.prepare()
    engine = chess.engine.SimpleEngine.popen_uci(str(ENGINE))
    engine.configure({"Threads": 6, "Hash": 512})

    try:
        for c in concepts:
            fid = c["id"]
            pool = new[(new.family == fid) & (new.margin >= MIN_MARGIN) & ~new.fen.isin(used)]
            pool = pool.sample(frac=1, random_state=11)
            added = []
            for r in pool.itertuples():
                if len(added) >= N_NEW:
                    break
                b = chess.Board(r.fen)
                if b.is_check() or b.legal_moves.count() < 8 or len(str(r.engine_best)) != 4:
                    continue
                info = engine.analyse(b, chess.engine.Limit(depth=DEPTH), multipv=2)
                best = info[0]["pv"][0].uci()
                if best != r.engine_best or len(info) < 2:
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
                added.append({
                    "fen": r.fen, "best": best, "best_san": b.san(chess.Move.from_uci(best)),
                    "pv": pv, "gap_cp": int(cp1 - cp2),
                    "cost_cp": int(r.human_cost_cp) if pd.notna(r.human_cost_cp) else None,
                    "stm": "white" if pov else "black",
                    "human": [{"uci": u, "san": (b.san(chess.Move.from_uci(u))
                                                 if chess.Move.from_uci(u) in b.legal_moves else u),
                               "p": round(p, 4)} for u, p in top],
                    "p_best": round(probs.get(best, 0.0), 4),
                    "quiet": bool(r.quiet), "piece": r.piece, "phase": r.phase,
                    "batch": "exp28",
                })
                used.add(r.fen)
            c["drill"].extend(added)

            # signature over the enlarged family
            o, nn = old[old.family == fid], new[new.family == fid]
            both = pd.concat([o, nn])
            fam = {
                "n": int(len(both)),
                "real_found": round(float(both.real_found.mean()), 3),
                "quiet_frac": round(float(both.quiet.mean()), 3),
                "mean_cost_cp": int(round(both.human_cost_cp.mean())),
                "motifs": fams16[fid]["motifs"],
                "pieces": both.piece.value_counts().head(3).to_dict(),
                "phase": both.phase.value_counts().to_dict(),
            }
            label, gloss = exp17.describe(fid, fam)
            c["name"] = c["label"] = label
            c["gloss"] = gloss
            c["signature"].update({
                "positions": fam["n"], "found_by_real_players": fam["real_found"],
                "quiet_share": fam["quiet_frac"], "avg_cost_cp": fam["mean_cost_cp"],
                "pieces": fam["pieces"], "phase": fam["phase"],
            })
            print(f"[{fid}] {label}: +{len(added)} drills -> {len(c['drill'])} total | "
                  f"family {len(o)} -> {fam['n']}, found {fam['real_found']:.1%}", flush=True)
    finally:
        engine.quit()

    json.dump(concepts, open(ROOT / "webapp" / "concepts.json", "w"))
    print("wrote webapp/concepts.json")


if __name__ == "__main__":
    main()
