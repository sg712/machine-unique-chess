"""Exp 04 — turn mined disagreements into a page of boards.

Reads results/03_disagreements.csv, picks the starkest machine-unique positions
(engine's move is clearly best; no simulated human at any level would play it),
and renders them as a chess-book-style HTML page: board, engine move, what humans
play instead, and what it costs them.
"""
import pathlib

import chess
import chess.svg
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
ELOS = [1100, 1400, 1700, 2000]


def san(fen: str, uci: str) -> str:
    b = chess.Board(fen)
    try:
        return b.san(chess.Move.from_uci(uci))
    except Exception:
        return uci


def board_svg(fen: str, uci: str | None) -> str:
    b = chess.Board(fen)
    mv = None
    if uci:
        try:
            mv = chess.Move.from_uci(uci)
        except Exception:
            mv = None
    return chess.svg.board(b, size=320, lastmove=None, arrows=(
        [chess.svg.Arrow(mv.from_square, mv.to_square, color="#c46a2f")] if mv else []))


def main(top_n: int = 12) -> None:
    df = pd.read_csv(ROOT / "results" / "03_disagreements.csv")
    mu = df[df.machine_unique].copy()
    if mu.empty:
        raise SystemExit("no machine-unique positions found — loosen --gap/--pmax in exp 03")

    # starkest = biggest eval cost to humans, tie-broken by lowest human probability
    mu["starkness"] = mu.human_cost_cp - 1000 * mu.p_max
    mu = mu.sort_values("starkness", ascending=False).head(top_n)

    cards = []
    for i, r in enumerate(mu.itertuples(index=False), start=1):
        eng_san = san(r.fen, r.engine_best)
        hum_san = san(r.fen, r.human_top_2000)
        probs = " · ".join(f"{e}: {getattr(r, f'p_engine_move_{e}')*100:.1f}%" for e in ELOS)
        turn = "White" if chess.Board(r.fen).turn else "Black"
        cards.append(f'''<article class="card">
<div class="boardwrap">{board_svg(r.fen, r.engine_best)}</div>
<div class="body">
<span class="idx">{i:02d}</span>
<h3>{turn} to play &mdash; engine plays <strong>{eng_san}</strong></h3>
<p class="humans">Humans at every level play <strong>{hum_san}</strong> instead. It costs <strong>{r.human_cost_cp:.0f} centipawns</strong>.</p>
<p class="probs">Chance a human finds {eng_san} &mdash; {probs}</p>
<p class="fen"><a href="https://lichess.org/analysis/{r.fen.replace(" ", "_")}">open on lichess</a> &middot; <code>{r.fen}</code></p>
</div>
</article>''')

    n_mu, n_all = len(df[df.machine_unique]), len(df)
    page = f'''<title>Machine-unique positions — mined from real games</title>
<style>
:root {{ --paper:#faf6ee; --ink:#2a2118; --muted:#6f6252; --accent:#8c5a2b; --rule:#e4d9c6; --inset:#f3ecdd;
  --serif:Charter,"Bitstream Charter",Cambria,Georgia,serif; --sans:ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --paper:#221c15; --ink:#e8ddcc; --muted:#a3937d; --accent:#d3a05f; --rule:#3a3128; --inset:#2b241b; }} }}
:root[data-theme="dark"] {{ --paper:#221c15; --ink:#e8ddcc; --muted:#a3937d; --accent:#d3a05f; --rule:#3a3128; --inset:#2b241b; }}
body {{ background:var(--paper); color:var(--ink); font-family:var(--serif); line-height:1.6; margin:0; }}
main {{ max-width:52rem; margin:0 auto; padding:3rem 1.25rem 5rem; }}
.eyebrow {{ font-family:var(--sans); font-size:.72rem; letter-spacing:.09em; text-transform:uppercase; color:var(--accent); font-weight:600; }}
h1 {{ font-size:2rem; line-height:1.15; margin:.4rem 0 .8rem; text-wrap:balance; }}
.lede {{ font-size:1.05rem; margin:0; }}
.stats {{ display:flex; flex-wrap:wrap; gap:1.5rem; margin:1.6rem 0 0; padding:1rem 1.2rem; background:var(--inset); border-radius:4px; }}
.stat {{ font-family:var(--sans); }}
.stat b {{ display:block; font-size:1.5rem; color:var(--accent); font-variant-numeric:tabular-nums; }}
.stat span {{ font-size:.75rem; color:var(--muted); letter-spacing:.04em; text-transform:uppercase; }}
.card {{ display:grid; grid-template-columns:320px 1fr; gap:1.5rem; margin-top:2.5rem; padding-top:1.6rem; border-top:1px solid var(--rule); align-items:start; }}
@media (max-width:44rem) {{ .card {{ grid-template-columns:1fr; }} }}
.boardwrap svg {{ width:100%; max-width:320px; height:auto; border:1px solid var(--rule); border-radius:3px; }}
.idx {{ font-family:var(--sans); font-size:.72rem; letter-spacing:.09em; color:var(--accent); font-weight:700; }}
.card h3 {{ font-size:1.1rem; margin:.3rem 0 .5rem; text-wrap:balance; }}
.humans {{ margin:0 0 .5rem; }}
.probs {{ font-family:var(--sans); font-size:.82rem; color:var(--muted); margin:0 0 .5rem; font-variant-numeric:tabular-nums; }}
.fen {{ font-size:.75rem; color:var(--muted); margin:0; overflow-wrap:anywhere; }}
.fen code {{ font-size:.72rem; }}
a {{ color:var(--accent); }}
footer {{ margin-top:3.5rem; border-top:1px solid var(--rule); padding-top:1rem; font-size:.85rem; color:var(--muted); }}
</style>
<main>
<header>
<span class="eyebrow">unnamed-concepts &middot; experiment 03</span>
<h1>Positions where engine knowledge is invisible to humans</h1>
<p class="lede">Mined automatically from real lichess games (1800+). For each position Stockfish&nbsp;17.1 gives the best move; Maia&mdash;2 predicts what humans at 1100, 1400, 1700 and 2000 would actually play. These are the positions where the engine is clearly right and <em>no</em> simulated human at <em>any</em> level finds it &mdash; the raw material for concept mining.</p>
<div class="stats">
<div class="stat"><b>{n_all:,}</b><span>positions analysed</span></div>
<div class="stat"><b>{n_mu:,}</b><span>machine-unique</span></div>
<div class="stat"><b>{100*n_mu/n_all:.1f}%</b><span>of all positions</span></div>
<div class="stat"><b>{df.human_cost_cp.mean():.0f}</b><span>mean cp lost by humans</span></div>
</div>
</header>
{"".join(cards)}
<footer><p>Criteria: the top human move at 2000 costs &ge;100 centipawns against Stockfish depth 16, and the engine&rsquo;s move draws &le;5% probability from Maia&mdash;2 at every level tested. Arrow marks the engine&rsquo;s move. Reproduce: <code>experiments/03_disagreement_mining.py</code>.</p></footer>
</main>'''

    out = ROOT / "results" / "machine_unique.html"
    out.write_text(page)
    print(f"rendered {len(cards)} positions -> {out}")


if __name__ == "__main__":
    main()
