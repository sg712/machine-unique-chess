"""Experiment 01 — the legibility frontier, v0.

For each of the four concept-prototype positions from Schut et al. (arXiv:2310.16410),
sweep Maia-2 across its supported skill range and record the probability human players
at each level assign to (a) AlphaZero's concept move and (b) the grandmaster's actual/
preferred move from the study.

Hypothesis (the paper's novelty claim, tested with a different instrument): the AZ
concept moves are "machine-unique", so their human-play probability should stay low
and roughly flat across ALL skill levels, while the GM moves should rise with Elo.
If instead P(AZ move) climbs at high Elo, the concept is partially human-visible and
the novelty filter overclaimed.

Output: results/01_frontier.csv and a printed summary table.
"""
import pathlib

import chess
import pandas as pd
from maia2 import inference, model

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The four prototype positions (transcribed from the paper's figures 8, 10, 14).
POSITIONS = [
    {
        "id": "fig8_provoke_h6",
        "fen": "r1bqk2r/ppp2pbp/3p1np1/3Pp3/2PnP3/P1N2N1P/1P3PP1/R1BQKB1R w KQkq - 0 9",
        "az_move": "c1g5",   # 9.Bg5!  (provokes h6, enables the strategic queen sac)
        "gm_move": "c1e3",   # 9.Be3   (the 2700's actual choice)
    },
    {
        "id": "fig10_both_flanks",
        "fen": "1k1r3r/1p1n1p2/p1p1pnp1/q1Pp4/3P1PPP/1PN5/P1Q1B3/1K1R3R w - - 0 21",
        "az_move": "c2d2",   # 21.Qd2! (prepares b4 with king on b1 - "not natural")
        "gm_move": "g4g5",   # 21.g5   (the GM's suggested plan)
    },
    {
        "id": "fig14L_space_over_material",
        "fen": "r5k1/1b2qpp1/p1prp2p/1pR5/1P1PBP2/4P2P/3Q2PK/R7 w - - 0 33",
        "az_move": "g2g4",   # 33.g4   (GM also found this - human-visible control)
        "gm_move": "g2g4",   # same move: this row calibrates the instrument
    },
    {
        "id": "fig14R_structure_over_material",
        "fen": "3qkb1r/1p3pp1/2p1p1p1/r7/2p3P1/P1Q1P2P/3P1PB1/R3K2R w KQk - 0 18",
        "az_move": "a3a4",   # 18.a4!  (GM rejected this outright - concept not learned)
        "gm_move": None,     # GM's preference unstated; use Maia's top move per level
    },
]

ELOS = list(range(1100, 2001, 100))


def main() -> None:
    m = model.from_pretrained(type="rapid", device="auto")
    prepared = inference.prepare()

    rows = []
    for pos in POSITIONS:
        board = chess.Board(pos["fen"])
        legal = {mv.uci() for mv in board.legal_moves}
        assert pos["az_move"] in legal, f"{pos['id']}: AZ move not legal — FEN transcription error?"
        for elo in ELOS:
            move_probs, _ = inference.inference_each(m, prepared, pos["fen"], elo, elo)
            top3 = sorted(move_probs, key=move_probs.get, reverse=True)[:3]
            rows.append({
                "position": pos["id"],
                "elo": elo,
                "p_az_move": round(move_probs.get(pos["az_move"], 0.0), 4),
                "p_gm_move": round(move_probs.get(pos["gm_move"], 0.0), 4) if pos["gm_move"] else None,
                "maia_top": top3[0],
                "p_top": round(move_probs[top3[0]], 4),
                "top3": " ".join(f"{t}:{move_probs[t]:.3f}" for t in top3),
            })
            print(f"{pos['id']:34s} elo={elo}  P(AZ)={rows[-1]['p_az_move']:.4f}  "
                  f"P(GM)={rows[-1]['p_gm_move'] if rows[-1]['p_gm_move'] is not None else '  -  '}  "
                  f"top={rows[-1]['maia_top']} ({rows[-1]['p_top']:.3f})")

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out / "01_frontier.csv", index=False)

    print("\n=== summary: mean P(AZ move) low-Elo (1100-1400) vs high-Elo (1700-2000) ===")
    for pos_id, grp in df.groupby("position"):
        lo = grp[grp.elo <= 1400]["p_az_move"].mean()
        hi = grp[grp.elo >= 1700]["p_az_move"].mean()
        d = hi - lo
        verdict = "RISING (partially human-visible)" if d > 0.02 else ("FALLING (skill moves humans AWAY)" if d < -0.02 else "FLAT (invisible at every level)")
        print(f"{pos_id:34s} low={lo:.4f}  high={hi:.4f}  {verdict}")
    print(f"\nwrote {out/'01_frontier.csv'}")


if __name__ == "__main__":
    main()
