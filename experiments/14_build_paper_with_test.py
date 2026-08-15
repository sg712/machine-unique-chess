"""Exp 14 — the preprint landing page with a live embedded test.

Selects public test positions (disjoint from every subject-experiment set,
verified stable at depth 20), then builds site/paper.html: the academic
two-column preprint from direction 1, with a full-width interactive apparatus
where a visitor attempts the positions and is scored against the study's
reference rates. Result export uses the `downloads` runtime capability.
"""
import base64
import json
import pathlib

import chess
import chess.engine
import chess.svg
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE = ROOT / "models" / "stockfish-build" / "src" / "stockfish"
N_TEST = 8
CACHE = ROOT / "results" / "experiment" / "public_test.json"


def pick_positions() -> list[dict]:
    if CACHE.exists():
        return json.load(open(CACHE))

    manifest = json.load(open(ROOT / "results" / "experiment" / "manifest.json"))
    used = {p["fen"] for s in manifest.values() for p in s}

    mu = pd.read_csv(ROOT / "results" / "08_mu_with_families.csv")
    mu = mu[~mu.fen.isin(used)]
    mu = mu.sample(frac=1, random_state=11)

    engine = chess.engine.SimpleEngine.popen_uci(str(ENGINE))
    engine.configure({"Threads": 6, "Hash": 512})
    out = []
    try:
        for r in mu.itertuples():
            if len(str(r.engine_best)) != 4:
                continue
            b = chess.Board(r.fen)
            if b.is_check() or b.legal_moves.count() < 8:
                continue
            info = engine.analyse(b, chess.engine.Limit(depth=20), multipv=2)
            if info[0]["pv"][0].uci() != r.engine_best:
                continue                                    # unstable: drop
            pov = b.turn
            gap = (info[0]["score"].pov(pov).score(mate_score=2000)
                   - info[1]["score"].pov(pov).score(mate_score=2000))
            if gap < 80:                                    # second move nearly as good
                continue
            out.append({
                "fen": r.fen, "best": r.engine_best, "human_top": r.human_top_2000,
                "family": int(r.family), "cost_cp": float(r.human_cost_cp), "gap_cp": float(gap),
            })
            print(f"kept {len(out)}/{N_TEST}")
            if len(out) == N_TEST:
                break
    finally:
        engine.quit()
    json.dump(out, open(CACHE, "w"), indent=1)
    return out


def main() -> None:
    tests = pick_positions()

    boards, meta = [], []
    for i, p in enumerate(tests):
        b = chess.Board(p["fen"])
        orient = b.turn
        boards.append(
            f'<div class="tpos" id="tp{i}" style="display:none">'
            + chess.svg.board(b, size=360, orientation=orient, coordinates=True,
                              colors={"square light": "#f2ece0", "square dark": "#b9906b"})
            + "</div>")
        meta.append({"i": i, "o": "w" if orient else "b",
                     "stm": "White" if orient else "Black",
                     "b64": base64.b64encode(p["best"].encode()).decode(),
                     "h64": base64.b64encode(str(p["human_top"]).encode()).decode(),
                     "cp": round(p["cost_cp"])})

    # figures ---------------------------------------------------------------
    XS = {1100: 0.0, 1500: 0.25, 2000: 0.5, 2300: 0.75, 2600: 1.0}
    CTRL = [(1100, 46.4), (1500, 55.4), (2000, 55.4), (2300, 64.3), (2600, 67.9)]
    TOP5 = [(1100, 28.6), (1500, 32.5), (2000, 45.5), (2300, 51.9), (2600, 57.1)]
    TOP1 = [(1100, 0.0), (1500, 0.0), (2000, 1.3), (2300, 2.6), (2600, 2.6)]
    W, H, PL, PR, PT, PB = 700, 300, 64, 140, 18, 42
    iw, ih = W - PL - PR, H - PT - PB

    def pt(e, v):
        return f"{PL + XS[e] * iw:.1f},{PT + ih - (v / 70) * ih:.1f}"

    fig = []
    for y in (0, 20, 40, 60):
        yy = PT + ih - (y / 70) * ih
        fig.append(f'<line x1="{PL}" x2="{PL+iw}" y1="{yy:.1f}" y2="{yy:.1f}" class="grid"/>')
        fig.append(f'<text x="{PL-10}" y="{yy+4:.1f}" class="ax" text-anchor="end">{y}%</text>')
    for e, f in XS.items():
        fig.append(f'<text x="{PL+f*iw:.1f}" y="{H-PB+24}" class="ax" text-anchor="middle">{e}</text>')
    for cls, s in (("c1", CTRL), ("c2", TOP5), ("c3", TOP1)):
        fig.append(f'<polyline points="{" ".join(pt(e, v) for e, v in s)}" class="l {cls}"/>')
    ytop = lambda v: PT + ih - (v / 70) * ih
    fig.append(f'<text x="{PL+iw+12}" y="{ytop(67.9)+4:.0f}" class="ann r">control positions</text>')
    fig.append(f'<text x="{PL+iw+12}" y="{ytop(57.1)+4:.0f}" class="ann">considered (top-5)</text>')
    fig.append(f'<text x="{PL+iw+12}" y="{ytop(2.6)+4:.0f}" class="ann">played (top-1)</text>')
    FIG2 = "".join(fig)

    board1 = chess.svg.board(
        chess.Board("1k1r3r/1p1n1p2/p1p1pnp1/q1Pp4/3P1PPP/1PN5/P1Q1B3/1K1R3R w - - 0 21"),
        size=300, coordinates=False, colors={"square light": "#f2ece0", "square dark": "#b9906b"},
        arrows=[chess.svg.Arrow(chess.B3, chess.B4, color="#00000045")])

    LINKS = [
        ("The four positions that started it",
         "The Schut et al. grandmaster experiment, reconstructed board by board.",
         "https://claude.ai/code/artifact/444cbb5f-35f0-4d0d-9aee-0c9bdfedd165"),
        ("Twelve machine-unique positions",
         "The starkest examples from real games — engine move, human move, the gap.",
         "https://claude.ai/code/artifact/6597c319-24bd-4c8b-aaa8-a26de2cfc2ed"),
        ("Eight candidate pattern families",
         "Cluster analysis of the mined positions: motif fingerprints and human find-rates.",
         "https://claude.ai/code/artifact/dcc6d34c-0f56-49fb-b346-d0a0e80c6b8e"),
        ("Study phase of the transfer experiment",
         "Prototype positions with the engine's line, shown without explanation.",
         "https://claude.ai/code/artifact/626eec47-4059-478f-a035-ffc1583f5e78"),
    ]
    mats = "".join(f'<a href="{u}">{t}<br><span>{d}</span></a>' for t, d, u in LINKS)

    page = f"""<title>Machine-unique knowledge in chess — working paper</title>
<style>
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#fdfdfb; color:#16150f;
  font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  font-size:16.5px; line-height:1.55; }}
.sheet {{ max-width:53rem; margin:0 auto; padding:4.5rem 2rem 6rem; }}
.stamp {{ font-family:"SF Mono",Menlo,monospace; font-size:.72rem; letter-spacing:.14em;
  text-transform:uppercase; color:#8a1f11; border-bottom:1px solid #d8d4c6;
  padding-bottom:.6rem; margin-bottom:2.4rem; display:flex; justify-content:space-between;
  gap:1rem; flex-wrap:wrap; }}
h1 {{ font-size:2.45rem; line-height:1.14; font-weight:400; margin:0 0 .9rem;
  letter-spacing:-.012em; max-width:30ch; text-wrap:balance; }}
.authors {{ font-size:.95rem; color:#5c584a; margin:0 0 2.2rem; font-style:italic; }}
.abstract {{ border-left:2px solid #16150f; padding-left:1.4rem; margin:0 0 2.4rem; max-width:44rem; }}
.abstract h2 {{ font-family:"SF Mono",Menlo,monospace; font-size:.7rem; letter-spacing:.16em;
  text-transform:uppercase; margin:0 0 .5rem; color:#5c584a; font-weight:400; }}
.abstract p {{ margin:0; font-size:1.02rem; line-height:1.62; }}
.jump {{ margin:0 0 2.8rem; font-size:.95rem; }}
.jump a {{ color:#8a1f11; }}
.cols {{ column-count:2; column-gap:2.6rem; column-rule:1px solid #eae6d8; text-align:justify;
  hyphens:auto; }}
@media (max-width:720px) {{ .cols {{ column-count:1; }} }}
.cols h2 {{ font-size:.82rem; font-family:"SF Mono",Menlo,monospace; letter-spacing:.13em;
  text-transform:uppercase; font-weight:400; color:#8a1f11; margin:1.6rem 0 .5rem; break-after:avoid; }}
.cols h2:first-child {{ margin-top:0; }}
.cols p {{ margin:0 0 .85rem; }} .cols p + p {{ text-indent:1.3em; }}
b {{ font-weight:600; font-variant-numeric:tabular-nums; }}
figure {{ break-inside:avoid; margin:1.4rem 0 1.6rem; }}
figure svg {{ display:block; width:100%; height:auto; }}
figcaption {{ font-size:.82rem; line-height:1.45; color:#5c584a; margin-top:.5rem; text-align:left; }}
figcaption b {{ color:#16150f; }}
.wide {{ column-span:all; margin:2.2rem 0; border-top:1px solid #d8d4c6;
  border-bottom:1px solid #d8d4c6; padding:1.6rem 0; }}
.grid {{ stroke:#e8e4d6; stroke-width:1; }}
.ax {{ font:11px "SF Mono",Menlo,monospace; fill:#8b8778; }}
.l {{ fill:none; stroke-linejoin:round; }}
.c1 {{ stroke:#8a1f11; stroke-width:1.8; }}
.c2 {{ stroke:#16150f; stroke-width:1.2; stroke-dasharray:4 4; opacity:.55; }}
.c3 {{ stroke:#16150f; stroke-width:2.6; }}
.ann {{ font:12.5px "Iowan Old Style",Georgia,serif; fill:#16150f; }}
.ann.r {{ fill:#8a1f11; }}

/* ── apparatus ─────────────────────────────────────────────── */
.box {{ column-span:all; border:1.5px solid #16150f; margin:2.6rem 0; background:#fffefa; }}
.box .bh {{ background:#16150f; color:#fdfdfb; padding:.55rem 1.2rem;
  font-family:"SF Mono",Menlo,monospace; font-size:.72rem; letter-spacing:.15em;
  text-transform:uppercase; display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap; }}
.box .bb {{ padding:1.6rem clamp(1rem,3vw,2.2rem) 2rem; }}
.box .lede {{ max-width:60ch; margin:0 0 1.4rem; }}
.tstage {{ display:flex; gap:2.2rem; align-items:flex-start; flex-wrap:wrap; }}
.tboard {{ position:relative; width:min(360px,86vw); flex:0 0 auto; }}
.tboard svg {{ width:100%; height:auto; display:block; border:1px solid #d8d4c6; }}
#tgrid {{ position:absolute; left:5.55%; top:5.55%; width:88.9%; height:88.9%;
  display:grid; grid-template-columns:repeat(8,1fr); grid-template-rows:repeat(8,1fr); }}
#tgrid div {{ cursor:pointer; }}
#tgrid div.sel {{ outline:3px solid #8a1f11; outline-offset:-3px; }}
#tgrid div.dst {{ outline:3px dashed #8a1f11; outline-offset:-3px; }}
.tside {{ flex:1 1 17rem; min-width:15rem; }}
.tside .q {{ font-size:1.05rem; margin:0 0 .5rem; }}
.tside .hint {{ font-size:.88rem; color:#5c584a; margin:0 0 1.2rem; }}
.tctl {{ display:flex; gap:.7rem; align-items:center; flex-wrap:wrap; }}
.pick {{ font-family:"SF Mono",Menlo,monospace; font-size:.9rem; min-width:5.5rem; }}
button {{ font:inherit; font-size:.92rem; padding:.45rem 1.1rem; border:1px solid #16150f;
  background:#fdfdfb; color:#16150f; cursor:pointer; }}
button.p {{ background:#16150f; color:#fdfdfb; }}
button:disabled {{ opacity:.35; cursor:default; }}
.prog {{ font-family:"SF Mono",Menlo,monospace; font-size:.72rem; letter-spacing:.1em;
  color:#8b8778; margin-top:1.4rem; }}
.tally {{ display:flex; gap:.3rem; margin-top:.5rem; }}
.tally i {{ width:1.5rem; height:.3rem; background:#e0dccd; display:block; }}
.tally i.done {{ background:#16150f; }}
#tresult {{ display:none; }}
.score {{ font-size:3.4rem; line-height:1; margin:.2rem 0 .3rem; font-variant-numeric:tabular-nums; }}
.verdict {{ font-size:1.06rem; max-width:56ch; margin:0 0 1.4rem; }}
.bars {{ margin:1.4rem 0; max-width:34rem; }}
.bar {{ display:grid; grid-template-columns:11rem 1fr auto; gap:.7rem; align-items:center;
  margin-bottom:.45rem; font-size:.86rem; }}
.bar .lb {{ color:#5c584a; }}
.bar .tr {{ background:#eae6d8; height:.75rem; position:relative; }}
.bar .fl {{ background:#16150f; height:100%; }}
.bar.you .fl {{ background:#8a1f11; }}
.bar .vl {{ font-family:"SF Mono",Menlo,monospace; font-size:.78rem; }}
.rev {{ margin-top:1.4rem; border-top:1px solid #d8d4c6; padding-top:1rem; }}
.rev table {{ border-collapse:collapse; font-size:.88rem; width:100%; max-width:34rem; }}
.rev th {{ text-align:left; font-family:"SF Mono",Menlo,monospace; font-size:.68rem;
  letter-spacing:.12em; text-transform:uppercase; color:#5c584a; font-weight:400;
  border-bottom:1px solid #d8d4c6; padding:.3rem .8rem .3rem 0; }}
.rev td {{ padding:.3rem .8rem .3rem 0; border-bottom:1px solid #f0ece0;
  font-variant-numeric:tabular-nums; }}
.rev td.hit {{ color:#1d6b2f; }} .rev td.miss {{ color:#8a1f11; }}
.rev .same {{ font-size:.8rem; color:#5c584a; font-style:italic; }}
.exp {{ margin-top:1.2rem; display:flex; gap:.7rem; flex-wrap:wrap; align-items:center; }}
.exp .note {{ font-size:.82rem; color:#5c584a; }}
.mats {{ column-span:all; margin-top:2.4rem; }}
.mats h2 {{ font-family:"SF Mono",Menlo,monospace; font-size:.7rem; letter-spacing:.16em;
  text-transform:uppercase; color:#5c584a; font-weight:400; margin:0 0 .9rem; }}
.mats a {{ display:block; color:#16150f; text-decoration:none; padding:.55rem 0;
  border-bottom:1px dotted #cfcab8; font-size:.95rem; }}
.mats a:hover {{ color:#8a1f11; }} .mats a span {{ color:#5c584a; font-size:.86rem; }}
.mats a::before {{ content:"→ "; color:#8a1f11; }}
.refs {{ column-span:all; margin-top:2.6rem; border-top:1px solid #d8d4c6; padding-top:1.2rem;
  font-size:.86rem; line-height:1.5; color:#43402f; }}
.refs h2 {{ font-family:"SF Mono",Menlo,monospace; font-size:.7rem; letter-spacing:.16em;
  text-transform:uppercase; color:#5c584a; font-weight:400; margin:0 0 .7rem; }}
.refs ol {{ padding-left:1.4rem; margin:0; }} .refs li {{ margin-bottom:.4rem; }}
:focus-visible {{ outline:2px solid #8a1f11; outline-offset:2px; }}
</style>
<div class="sheet">
<div class="stamp"><span>Working paper · unrefereed</span><span>August 2026</span></div>
<h1>Machine-unique knowledge in chess, and whether humans can be taught it</h1>
<p class="authors">A reproduction and extension of Schut et al., <i>PNAS</i> 2025, on open models</p>

<div class="abstract"><h2>Abstract</h2>
<p>Superhuman chess engines hold concepts that human chess vocabulary cannot express. We
reproduce the concept-transfer result of Schut et&nbsp;al. on open models and measure its scope:
across <b>43,603</b> positions from real games, <b>4.0%</b> contain an engine-preferred move that
no simulated human plays at any rating between 1100 and 2600. In <b>1,499</b> of these the player
at the board also failed to find it; in <b>247</b> that player was rated 2500 or above. We
characterise these moves, cluster them into candidate families, and run a transfer experiment.
Readers can attempt eight of the positions below.</p></div>

<p class="jump"><a href="#apparatus">Skip to the test &darr;</a></p>

<div class="cols">
<h2>1 · The gap</h2>
<p>In 2025 a DeepMind group mined AlphaZero's internal representations for concepts absent from
human play, filtered them for teachability and novelty, and taught the survivors to four
grandmasters rated 2600–2800. The teaching used no language: only prototype positions with the
engine's line played out. All four improved; one went from 0/4 to 42% on held-out positions.</p>
<p>The obvious question is scope. Was this a curiosity of four hand-selected concepts, or is
machine-unique knowledge a broad feature of engine play? And does transfer require a
grandmaster's pattern library?</p>

<h2>2 · Measuring invisibility</h2>
<p>A position is <i>machine-unique</i> when the engine's best move is clearly best — at least 100
centipawns better than the human favourite at depth 16 — and no simulated human at any rating
assigns it more than 5% probability. Positions come from public Lichess games; human behaviour is
modelled with Maia-2 and Maia-3, which predict moves by rating band rather than by strength.</p>
<p>The rate is stable at 4.0% across five independent batches and across both club and 2300+
elite populations. These positions are neither rare nor concentrated in weak play.</p>

<figure>{board1}
<figcaption><b>Figure 1.</b> White to play. AlphaZero prepares b4 — an advance toward its own
king. The grandmaster shown this position called it &ldquo;not natural&rdquo;.</figcaption></figure>

<h2>3 · Blindness becomes disbelief</h2>
<p>Simulated humans converge toward engine play as rating rises — on ordinary positions. On
machine-unique positions the top-1 rate stays flat near zero from 1100 to 2600, while the top-5
rate climbs from 29% to 57%. By master level the move is in the candidate set more often than not
and is still almost never played.</p>
<p>Weak players do not see the move. Strong players see it and reject it.</p>

<div class="wide">
<svg viewBox="0 0 {W} {H}" role="img" aria-label="Find-rate by rating">{FIG2}</svg>
<figcaption><b>Figure 2.</b> Rate at which simulated humans select the engine's move, by rating.
Solid dark: machine-unique positions, top-1. Dashed: same positions, move present in top-5.
Red: control positions.</figcaption></div>

<h2>4 · What the moves are</h2>
<p>Across the clustered families, 72–92% of machine-unique moves are quiet — neither capture nor
check. The invisible part of chess is not tactics; tactics are what human training drills. It is
quiet moves whose justification lies outside the vocabulary.</p>
<p>Regressing the machine-unique direction in Leela's latent space onto twelve named motifs yields
R² = 0.46, with positive weight on sacrifice, pin and exposed-king and negative weight on clearance
and fork. Roughly half of what makes these positions machine-only is expressible in known terms.
The other half is not.</p>

<div class="box" id="apparatus">
  <div class="bh"><span>Apparatus · reader test</span><span>{N_TEST} positions · no feedback until the end</span></div>
  <div class="bb">
    <p class="lede">Eight machine-unique positions, held out from every set used in the transfer
    experiment and re-verified at depth 20. In each, one move is decisively best and essentially no
    human plays it. Click the piece, then its destination.</p>

    <div id="tstage" class="tstage">
      <div class="tboard">{"".join(boards)}<div id="tgrid"></div></div>
      <div class="tside">
        <p class="q" id="tq"></p>
        <p class="hint">Find the move the engine considers clearly best.</p>
        <div class="tctl">
          <span class="pick" id="tpick">—</span>
          <button id="tclear">Clear</button>
          <button id="tlock" class="p" disabled>Lock in</button>
        </div>
        <div class="prog" id="tprog"></div>
        <div class="tally" id="ttally"></div>
      </div>
    </div>

    <div id="tresult">
      <p class="score" id="tscore"></p>
      <p class="verdict" id="tverdict"></p>
      <div class="bars" id="tbars"></div>
      <div class="rev"><table><thead><tr><th>#</th><th>Your move</th><th>Engine</th>
        <th>Typical human</th><th>Cost</th></tr></thead><tbody id="trev"></tbody></table>
        <p class="same">Where your move matches the typical-human column, you chose exactly what
        the behaviour model predicts a 2000-rated player would.</p></div>
      <div class="exp">
        <button id="tsave">Download result</button>
        <button id="tcopy">Copy result</button>
        <span class="note" id="tnote"></span>
      </div>
    </div>
  </div>
</div>

<h2>5 · Transfer, n = 1</h2>
<p>A single tournament-level subject attempted ten held-out machine-unique positions cold, scoring
0/10 — while 7 of the 10 chosen moves were exactly the move Maia predicts a typical human plays.
Study and retest phases follow the original protocol: prototype exposure without explanation, then
unseen positions. The retest is pending at the time of writing.</p>
<p>The apparatus above is the same instrument at reader scale. Scores are computed in the browser;
nothing is transmitted.</p>

<div class="mats"><h2>Materials</h2>{mats}</div>

<div class="refs"><h2>References</h2><ol>
<li>Schut, L., Tomašev, N., McGrath, T., Hassabis, D., Paquet, U., Kim, B. Bridging the human–AI
knowledge gap through concept discovery and transfer in AlphaZero. <i>PNAS</i> 122(13), 2025.</li>
<li>McGrath, T. et al. Acquisition of chess knowledge in AlphaZero. <i>PNAS</i> 119(47), 2022.</li>
<li>Tang, Z., Jiang, D., McIlroy-Young, R., Anderson, A. et al. Maia-2: a unified model for human–AI
alignment in chess. <i>NeurIPS</i> 2024.</li>
</ol></div>
</div>
</div>

<script>
const POS = {json.dumps(meta)};
const FILES = "abcdefgh";
let cur = 0, from = null, to = null, t0 = Date.now();
const ans = [];
const grid = document.getElementById("tgrid");
const pick = document.getElementById("tpick");
const lock = document.getElementById("tlock");
const tally = document.getElementById("ttally");

POS.forEach(() => {{ const i = document.createElement("i"); tally.appendChild(i); }});

function sq(cell) {{
  const p = POS[cur], c = cell % 8, r = (cell / 8) | 0;
  return p.o === "w" ? FILES[c] + (8 - r) : FILES[7 - c] + (r + 1);
}}
for (let i = 0; i < 64; i++) {{
  const d = document.createElement("div");
  d.dataset.cell = i;
  d.addEventListener("click", () => {{
    const s = sq(+d.dataset.cell);
    if (from === null || to !== null) {{
      from = s; to = null;
      grid.querySelectorAll(".sel,.dst").forEach(e => e.classList.remove("sel", "dst"));
      d.classList.add("sel");
    }} else {{ to = s; d.classList.add("dst"); }}
    pick.textContent = from + (to ? "–" + to : "–?");
    lock.disabled = !(from && to);
  }});
  grid.appendChild(d);
}}
function reset() {{
  from = to = null; pick.textContent = "—"; lock.disabled = true;
  grid.querySelectorAll(".sel,.dst").forEach(e => e.classList.remove("sel", "dst"));
}}
document.getElementById("tclear").addEventListener("click", reset);
function show(i) {{
  POS.forEach(p => document.getElementById("tp" + p.i).style.display = "none");
  document.getElementById("tp" + POS[i].i).style.display = "block";
  document.getElementById("tq").textContent = POS[i].stm + " to move.";
  document.getElementById("tprog").textContent =
    "Position " + (i + 1) + " of " + POS.length;
  t0 = Date.now();
}}
lock.addEventListener("click", () => {{
  const p = POS[cur], picked = from + to;
  ans.push({{ n: cur + 1, picked, best: atob(p.b64), human: atob(p.h64), cp: p.cp,
             correct: picked === atob(p.b64), seconds: Math.round((Date.now() - t0) / 100) / 10 }});
  tally.children[cur].classList.add("done");
  reset();
  if (cur + 1 < POS.length) {{ cur++; show(cur); }} else finish();
}});

function bar(label, pct, mine) {{
  return '<div class="bar' + (mine ? ' you' : '') + '"><span class="lb">' + label +
    '</span><span class="tr"><span class="fl" style="width:' + Math.max(pct, 1.2) +
    '%"></span></span><span class="vl">' + pct.toFixed(0) + '%</span></div>';
}}
function finish() {{
  document.getElementById("tstage").style.display = "none";
  const n = ans.filter(a => a.correct).length, pctv = (n / ans.length) * 100;
  const matched = ans.filter(a => a.picked === a.human).length;
  document.getElementById("tscore").textContent = n + " / " + ans.length;
  let v;
  if (n === 0) v = "Zero is the expected result, and it is the point: simulated humans score " +
    "under 3% on these positions at every rating from 1100 to 2600. The grandmaster in the " +
    "original study scored 0/4 on his first attempt.";
  else if (pctv < 30) v = "At or near the rate real 2000–2200 players achieve on machine-unique " +
    "positions (13%). Most of these moves are invisible to trained human pattern recognition.";
  else if (pctv < 55) v = "Around the rate real 2400–2600 players achieve. Strong performance: " +
    "these positions defeated the player who was actually at the board.";
  else v = "Above the rate real 2600+ players achieve on these positions (47%). Either strong " +
    "calculation, or you have seen this class of position before.";
  if (matched > 0) v += " " + matched + " of your " + ans.length + " moves matched exactly what " +
    "the behaviour model predicts a typical 2000-rated player would choose.";
  document.getElementById("tverdict").textContent = v;
  document.getElementById("tbars").innerHTML =
    bar("You", pctv, true) +
    bar("Simulated 2000", 1.3, false) +
    bar("Simulated 2600", 2.6, false) +
    bar("Real 2000–2200", 13.2, false) +
    bar("Real 2400–2600", 15.9, false) +
    bar("Real 2600+", 47.3, false);
  document.getElementById("trev").innerHTML = ans.map(a =>
    '<tr><td>' + a.n + '</td><td class="' + (a.correct ? 'hit' : 'miss') + '">' + a.picked +
    '</td><td>' + a.best + '</td><td>' + a.human + '</td><td>−' + a.cp + '</td></tr>').join("");
  document.getElementById("tresult").style.display = "block";
}}

const payload = () => JSON.stringify(
  {{ test: "machine-unique-8", when: new Date().toISOString(),
     score: ans.filter(a => a.correct).length, of: ans.length, answers: ans }}, null, 1);

(async () => {{
  const dl = window.claude && claude.use ? await claude.use("downloads") : null;
  const save = document.getElementById("tsave"), note = document.getElementById("tnote");
  if (!dl) {{ save.style.display = "none"; return; }}
  save.addEventListener("click", async () => {{
    note.textContent = "";
    try {{
      await dl.save({{ filename: "machine-unique-result.json", data: payload() }});
      note.textContent = "Saved.";
    }} catch (e) {{
      note.textContent = e && e.code === "declined" ? "Save cancelled."
        : "Could not save — use Copy instead.";
    }}
  }});
}})();
document.getElementById("tcopy").addEventListener("click", async () => {{
  const note = document.getElementById("tnote");
  try {{ await navigator.clipboard.writeText(payload()); note.textContent = "Copied to clipboard."; }}
  catch {{ note.textContent = "Clipboard blocked — select the page text instead."; }}
}});

show(0);
</script>"""

    out = ROOT / "site" / "paper.html"
    out.write_text(page)
    print(f"wrote {out} ({len(page)//1024} KB, {len(tests)} test positions)")


if __name__ == "__main__":
    main()
