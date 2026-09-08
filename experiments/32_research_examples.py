"""Build three deliberately curated illustrations, separate from the random audit.

Each opening move must remain first at depth 20 with >=70cp over the runner-up.
One related drill per group must come from a different source game and pass the
same check. This selection is for explanation, not an estimate of stability.
"""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.engine

ROOT = Path(__file__).resolve().parents[1]
EDITORIAL = {
    0: {"title": "Look beyond the advancing pawn", "prompt": "Black has a pawn on a3. Would you push it, or improve another piece first?",
        "explanation": "Maia's favourite is the direct pawn push ...a2. The engine instead retreats the knight from c5 to b7, where it protects the bishop on d6. In the engine line, Nxd6 can now be answered by ...Nxd6; after the immediate pawn push, White takes on d6 without that knight recapture. The retreat has a concrete defensive purpose. It does not establish that all positions in this group share one new concept."},
    3: {"title": "Consider the pawn move before the capture", "prompt": "The bishop can capture the knight on e5. Is that the move you would choose?",
        "explanation": "Maia strongly favours ...Bxe5. Stockfish prefers ...g5, which supports Black's pawn on f4. In the alternative line, ...Bxe5 dxe5 ...Rxe5 Bxf4 lets White take the undefended f4-pawn. The pawn move changes that tactical detail: a bishop taking on f4 would face ...gxf4. This is one concrete difference to inspect in the continuations, not a complete explanation of the engine evaluation. A quiet move can have a tactical purpose."},
    5: {"title": "A rook move while the knight is attacked", "prompt": "White's f3-pawn attacks the knight on g4. Does Black have to move that knight?",
        "explanation": "Maia's favourite, ...Nge5, moves the attacked knight. Stockfish chooses ...Rb8, putting the rook on the same file as White's bishop on b6. In the saved continuation, ...Rxb6 follows fxg4. This illustrates a concrete trade-off to calculate, not a general rule to leave pieces attacked."},
}


def main():
    concepts_path = ROOT / "webapp/concepts.json"
    concepts = json.loads(concepts_path.read_text())
    source = {r["fen"]: r for r in csv.DictReader((ROOT / "results/master_all.csv").open())}
    examples = []
    with chess.engine.SimpleEngine.popen_uci(str(ROOT / "models/stockfish-build/src/stockfish")) as engine:
        engine.configure({"Threads": 1, "Hash": 128})
        def inspect(pos):
            board = chess.Board(pos["fen"])
            engine.configure({"Clear Hash": None})
            infos = engine.analyse(board, chess.engine.Limit(depth=20, time=12), multipv=2)
            scores = [i["score"].pov(board.turn).score() for i in infos]
            if min(i["depth"] for i in infos) < 20 or None in scores or len(scores) < 2:
                return None
            if infos[0]["pv"][0].uci() != pos["best"] or scores[0] - scores[1] < 70:
                return None
            favourite = pos["human"][0]
            engine.configure({"Clear Hash": None})
            human = engine.analyse(board, chess.engine.Limit(depth=20, time=12),
                                   root_moves=[chess.Move.from_uci(favourite["uci"])])
            if human["depth"] < 20 or human["score"].pov(board.turn).score() is None:
                return None
            def line(info):
                bb = board.copy(); moves = []
                for move in info["pv"][:10]:
                    moves.append({"uci": move.uci(), "san": bb.san(move)})
                    bb.push(move)
                return moves
            return {"fen": pos["fen"], "game_id": source[pos["fen"]]["game_id"],
                    "best": pos["best"], "best_san": pos["best_san"], "pv": line(infos[0]),
                    "human": {**favourite, "pv": line(human)}, "maia_rating": 1900,
                    "depth": 20, "best_cp": scores[0], "runner_up_cp": scores[1],
                    "human_cp": human["score"].pov(board.turn).score()}
        for cid, copy in EDITORIAL.items():
            group = concepts[cid]
            primary = inspect(group["study"][0])
            if primary is None:
                raise RuntimeError(f"Featured illustration {cid} failed verification")
            related = None
            for index, pos in enumerate(group["drill"]):
                if source[pos["fen"]]["game_id"] == primary["game_id"]:
                    continue
                related = inspect(pos)
                if related:
                    related["drill_index"] = index
                    break
            if related is None:
                raise RuntimeError(f"No verified related illustration for {cid}")
            examples.append({"concept": cid, **copy, "primary": primary, "related": related})
            print(cid, "engine:", ' '.join(x['san'] for x in primary['pv']),
                  "Maia line:", ' '.join(x['san'] for x in primary['human']['pv']), flush=True)
        output = {"generated_at": datetime.now(timezone.utc).isoformat(), "engine": engine.id,
                  "concepts_sha256": hashlib.sha256(concepts_path.read_bytes()).hexdigest(),
                  "selection": "curated; not part of the random robustness sample", "examples": examples}
    (ROOT / "webapp/research_examples.json").write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
