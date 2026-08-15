"""Exp 13 — five landing-page directions, structurally distinct.

Each page is a complete, self-contained landing page in its own visual world.
No shared layout skeleton: preprint (two-column academic), treatise (1890s chess
book), broadside (oversized editorial poster), plot (chart-as-page), notebook
(lab log). Written to site/dir/*.html.
"""
import pathlib

import chess
import chess.svg

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "dir"

FEN = "1k1r3r/1p1n1p2/p1p1pnp1/q1Pp4/3P1PPP/1PN5/P1Q1B3/1K1R3R w - - 0 21"
BOARD = chess.Board(FEN)
MOVE = chess.Move.from_uci("b3b4")


def board(light, dark, size=340, arrow="#00000045", coords=False):
    return chess.svg.board(
        BOARD, size=size, coordinates=coords,
        colors={"square light": light, "square dark": dark},
        arrows=[chess.svg.Arrow(MOVE.from_square, MOVE.to_square, color=arrow)],
    )


# ── shared numbers ────────────────────────────────────────────────────────────
XS = {1100: 0.0, 1500: 0.25, 2000: 0.5, 2300: 0.75, 2600: 1.0}
CTRL = [(1100, 46.4), (1500, 55.4), (2000, 55.4), (2300, 64.3), (2600, 67.9)]
TOP5 = [(1100, 28.6), (1500, 32.5), (2000, 45.5), (2300, 51.9), (2600, 57.1)]
TOP1 = [(1100, 0.0), (1500, 0.0), (2000, 1.3), (2300, 2.6), (2600, 2.6)]


def chart(w=700, h=300, pad_l=64, pad_r=150, pad_t=18, pad_b=42,
          grid_cls="grid", ax_cls="ax", series=(("c1", CTRL), ("c2", TOP5), ("c3", TOP1))):
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b

    def pt(elo, v):
        return f"{pad_l + XS[elo] * iw:.1f},{pad_t + ih - (v / 70) * ih:.1f}"

    out = []
    for y in (0, 20, 40, 60):
        yy = pad_t + ih - (y / 70) * ih
        out.append(f'<line x1="{pad_l}" x2="{pad_l+iw}" y1="{yy:.1f}" y2="{yy:.1f}" class="{grid_cls}"/>')
        out.append(f'<text x="{pad_l-10}" y="{yy+4:.1f}" class="{ax_cls}" text-anchor="end">{y}%</text>')
    for elo, f in XS.items():
        out.append(f'<text x="{pad_l+f*iw:.1f}" y="{h-pad_b+24}" class="{ax_cls}" text-anchor="middle">{elo}</text>')
    for cls, s in series:
        out.append(f'<polyline points="{" ".join(pt(e, v) for e, v in s)}" class="l {cls}"/>')
    return "".join(out), pad_l + iw, pad_t + ih


LINKS = [
    ("The four positions that started it",
     "The DeepMind grandmaster experiment, reconstructed board by board.",
     "https://claude.ai/code/artifact/444cbb5f-35f0-4d0d-9aee-0c9bdfedd165"),
    ("Twelve machine-unique positions",
     "The starkest examples from real games — engine move, human move, the gap.",
     "https://claude.ai/code/artifact/6597c319-24bd-4c8b-aaa8-a26de2cfc2ed"),
    ("Eight pattern families",
     "Cluster analysis of 646 positions: motif fingerprints and human find-rates.",
     "https://claude.ai/code/artifact/dcc6d34c-0f56-49fb-b346-d0a0e80c6b8e"),
    ("The transfer experiment, live",
     "One tournament player, the DeepMind protocol, baseline 0/10. Retest pending.",
     "https://claude.ai/code/artifact/626eec47-4059-478f-a035-ffc1583f5e78"),
]

# ══════════════════════════════════════════════════════════════════════════════
# 1 · PREPRINT — two-column academic paper
# ══════════════════════════════════════════════════════════════════════════════
g, gx, gy = chart(pad_r=140)
preprint = f"""<title>Unnamed Concepts — preprint</title>
<style>
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#fdfdfb; color:#16150f;
  font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  font-size:16.5px; line-height:1.55; }}
.sheet {{ max-width:53rem; margin:0 auto; padding:4.5rem 2rem 6rem; }}
.stamp {{ font-family:"SF Mono",Menlo,monospace; font-size:.72rem; letter-spacing:.14em;
  text-transform:uppercase; color:#8a1f11; border-bottom:1px solid #d8d4c6;
  padding-bottom:.6rem; margin-bottom:2.4rem; display:flex; justify-content:space-between; }}
h1 {{ font-size:2.45rem; line-height:1.14; font-weight:400; margin:0 0 .9rem;
  letter-spacing:-.012em; max-width:30ch; text-wrap:balance; }}
.authors {{ font-size:.95rem; color:#5c584a; margin:0 0 2.2rem; font-style:italic; }}
.abstract {{ border-left:2px solid #16150f; padding:0 0 0 1.4rem; margin:0 0 2.8rem;
  max-width:44rem; }}
.abstract h2 {{ font-family:"SF Mono",Menlo,monospace; font-size:.7rem; letter-spacing:.16em;
  text-transform:uppercase; margin:0 0 .5rem; color:#5c584a; font-weight:400; }}
.abstract p {{ margin:0; font-size:1.02rem; line-height:1.62; }}
.cols {{ column-count:2; column-gap:2.6rem; column-rule:1px solid #eae6d8; text-align:justify;
  hyphens:auto; }}
@media (max-width:720px) {{ .cols {{ column-count:1; }} }}
.cols h2 {{ font-size:.82rem; font-family:"SF Mono",Menlo,monospace; letter-spacing:.13em;
  text-transform:uppercase; font-weight:400; color:#8a1f11; margin:1.6rem 0 .5rem;
  break-after:avoid; }}
.cols h2:first-child {{ margin-top:0; }}
.cols p {{ margin:0 0 .85rem; }}
.cols p + p {{ text-indent:1.3em; }}
b {{ font-weight:600; font-variant-numeric:tabular-nums; }}
figure {{ break-inside:avoid; margin:1.4rem 0 1.6rem; }}
figure svg {{ display:block; width:100%; height:auto; }}
figcaption {{ font-size:.82rem; line-height:1.45; color:#5c584a; margin-top:.5rem; text-align:left; }}
figcaption b {{ font-weight:600; color:#16150f; }}
.wide {{ column-span:all; margin:2.2rem 0; border-top:1px solid #d8d4c6;
  border-bottom:1px solid #d8d4c6; padding:1.6rem 0; }}
.wide svg {{ width:100%; height:auto; }}
.grid {{ stroke:#e8e4d6; stroke-width:1; }}
.ax {{ font:11px "SF Mono",Menlo,monospace; fill:#8b8778; }}
.l {{ fill:none; stroke-linejoin:round; }}
.c1 {{ stroke:#8a1f11; stroke-width:1.8; }}
.c2 {{ stroke:#16150f; stroke-width:1.2; stroke-dasharray:4 4; opacity:.55; }}
.c3 {{ stroke:#16150f; stroke-width:2.6; }}
.ann {{ font:12.5px "Iowan Old Style",Georgia,serif; fill:#16150f; }}
.ann.r {{ fill:#8a1f11; }}
.refs {{ column-span:all; margin-top:2.6rem; border-top:1px solid #d8d4c6; padding-top:1.2rem;
  font-size:.86rem; line-height:1.5; color:#43402f; }}
.refs h2 {{ font-family:"SF Mono",Menlo,monospace; font-size:.7rem; letter-spacing:.16em;
  text-transform:uppercase; color:#5c584a; font-weight:400; margin:0 0 .7rem; }}
.refs li {{ margin-bottom:.4rem; }} .refs ol {{ padding-left:1.4rem; margin:0; }}
.mats {{ column-span:all; margin-top:2.4rem; }}
.mats h2 {{ font-family:"SF Mono",Menlo,monospace; font-size:.7rem; letter-spacing:.16em;
  text-transform:uppercase; color:#5c584a; font-weight:400; margin:0 0 .9rem; }}
.mats a {{ display:block; color:#16150f; text-decoration:none; padding:.55rem 0;
  border-bottom:1px dotted #cfcab8; font-size:.95rem; }}
.mats a:hover {{ color:#8a1f11; }}
.mats a span {{ color:#5c584a; font-size:.86rem; }}
.mats a::before {{ content:"→ "; color:#8a1f11; }}
:focus-visible {{ outline:2px solid #8a1f11; outline-offset:2px; }}
</style>
<div class="sheet">
<div class="stamp"><span>Working paper · unrefereed</span><span>August 2026</span></div>
<h1>Machine-unique knowledge in chess, and whether humans can be taught it</h1>
<p class="authors">A reproduction and extension of Schut et al., <i>PNAS</i> 2025, on open models</p>

<div class="abstract"><h2>Abstract</h2>
<p>Superhuman chess engines hold concepts that human chess vocabulary cannot express.
We reproduce the concept-transfer result of Schut et&nbsp;al. on open models, and measure
its scope: across <b>43,603</b> positions from real games, <b>4.0%</b> contain an
engine-preferred move that no simulated human plays at any rating between 1100 and 2600.
In <b>1,499</b> of these the player at the board also failed to find it; in <b>247</b>
that player was rated 2500 or above. We characterise these moves, cluster them into
candidate families, and run a single-subject transfer experiment.</p></div>

<div class="cols">
<h2>1 · The gap</h2>
<p>In 2025 a DeepMind group mined AlphaZero's internal representations for concepts absent
from human play, filtered them for teachability and novelty, and taught the survivors to
four grandmasters rated 2600–2800. The teaching used no language: only prototype positions
with the engine's line played out. All four improved; one went from 0/4 to 42% on held-out
positions of the same concept.</p>
<p>The obvious question is scope. Was this a curiosity of four hand-selected concepts, or
is machine-unique knowledge a broad feature of engine play? And does transfer require a
grandmaster's pattern library, or can an ordinary strong player absorb it?</p>

<h2>2 · Measuring invisibility</h2>
<p>We define a position as <i>machine-unique</i> when an engine's best move is clearly best —
at least 100 centipawns better than the human favourite at depth 16 — and yet no simulated
human at any rating assigns it more than 5% probability. Positions are drawn from public
Lichess games; human behaviour is modelled with Maia-2 and Maia-3, which predict moves by
rating band rather than by strength.</p>
<p>The rate is remarkably stable: 4.0% across five independent batches and across both club
and 2300+ elite populations. Machine-unique positions are not rare curiosities, and they are
not concentrated in weak play.</p>

<figure>{board("#f2ece0", "#b9906b", 300)}
<figcaption><b>Figure 1.</b> White to play. AlphaZero prepares b4 — an advance toward its own
king. The grandmaster shown this position called it &ldquo;not natural&rdquo;.</figcaption></figure>

<h2>3 · Blindness becomes disbelief</h2>
<p>Simulated humans do converge toward engine play as rating rises — on ordinary positions.
On machine-unique positions the top-1 rate stays flat near zero from 1100 to 2600. But the
top-5 rate climbs steeply: by 2600 the machine's move is in the candidate set 57% of the
time and is still almost never played.</p>
<p>The character of the failure changes with strength. Weak players do not see the move at
all; strong players see it and reject it.</p>

<div class="wide">
<svg viewBox="0 0 700 300" role="img" aria-label="Find-rate by rating">{g}
<text x="{gx+12}" y="{300-42-(67.9/70)*(300-18-42)+22}" class="ann r">normal positions</text>
<text x="{gx+12}" y="{300-42-(57.1/70)*(300-18-42)+22}" class="ann">considered (top-5)</text>
<text x="{gx+12}" y="{300-42-(2.6/70)*(300-18-42)+4}" class="ann">played (top-1)</text>
</svg>
<figcaption><b>Figure 2.</b> Rate at which simulated humans select the engine's move, by rating.
Solid dark: machine-unique positions, top-1. Dashed: same positions, move present in top-5.
Red: control positions.</figcaption></div>

<h2>4 · What the moves are</h2>
<p>Across the clustered families, 72–92% of machine-unique moves are quiet — neither capture
nor check. The invisible part of chess is not tactics; tactics are what human training
drills. It is quiet moves whose justification lies outside the vocabulary.</p>
<p>Regressing the machine-unique direction in Leela's latent space onto twelve named motifs
yields R² = 0.46, with positive weight on sacrifice, pin and exposed-king and negative
weight on clearance and fork. Roughly half of what makes these positions machine-only is
expressible in known terms — sacrifice-flavoured play with no combinational payoff. The
other half is not.</p>

<h2>5 · Transfer, n = 1</h2>
<p>A single tournament-level subject attempted ten held-out machine-unique positions cold,
scoring 0/10 — while 7 of the 10 chosen moves were exactly the move Maia predicts a typical
human plays. The subject is, statistically, a textbook human. Study and retest phases follow
the original protocol: prototype exposure without explanation, then unseen positions.</p>

<div class="mats"><h2>Materials</h2>
{"".join(f'<a href="{u}">{t}<br><span>{d}</span></a>' for t, d, u in LINKS)}
</div>

<div class="refs"><h2>References</h2><ol>
<li>Schut, L., Tomašev, N., McGrath, T., Hassabis, D., Paquet, U., Kim, B. Bridging the human–AI
knowledge gap through concept discovery and transfer in AlphaZero. <i>PNAS</i> 122(13), 2025.</li>
<li>McGrath, T. et al. Acquisition of chess knowledge in AlphaZero. <i>PNAS</i> 119(47), 2022.</li>
<li>Tang, Z., Jiang, D., McIlroy-Young, R., Anderson, A. et al. Maia-2: a unified model for
human–AI alignment in chess. <i>NeurIPS</i> 2024.</li>
</ol></div>
</div>
</div>"""

# ══════════════════════════════════════════════════════════════════════════════
# 2 · TREATISE — 1890s chess book
# ══════════════════════════════════════════════════════════════════════════════
treatise = f"""<title>Unnamed Concepts — a treatise</title>
<style>
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#f6efdd; color:#2b1f14;
  font-family:"Hoefler Text",Baskerville,"Times New Roman",Georgia,serif;
  font-size:19px; line-height:1.72; }}
.page {{ max-width:40rem; margin:0 auto; padding:5rem 1.8rem 7rem; }}
.title {{ text-align:center; border-top:4px double #2b1f14; border-bottom:4px double #2b1f14;
  padding:2.8rem 0 2.4rem; margin-bottom:3.2rem; }}
.title h1 {{ font-size:3rem; font-weight:400; margin:0 0 .5rem; letter-spacing:.005em; line-height:1.06; }}
.title .sub {{ font-variant:small-caps; letter-spacing:.2em; font-size:.9rem; color:#7d2b1b; margin:0 0 1.6rem; }}
.title .arg {{ font-style:italic; font-size:1.12rem; line-height:1.6; max-width:26rem;
  margin:0 auto; }}
.orn {{ text-align:center; color:#7d2b1b; letter-spacing:1.2em; font-size:.85rem; margin:2.6rem 0; }}
h2 {{ font-variant:small-caps; letter-spacing:.13em; font-size:1.08rem; font-weight:400;
  margin:2.6rem 0 .7rem; color:#7d2b1b; }}
p {{ margin:0 0 1rem; }}
p.lead::first-letter {{ float:left; font-size:4.1rem; line-height:.82; padding:.08em .1em 0 0;
  color:#7d2b1b; font-weight:400; }}
b {{ font-weight:600; font-variant-numeric:tabular-nums; }}
i.q {{ color:#7d2b1b; }}
figure {{ margin:2.4rem 0; text-align:center; }}
figure svg {{ display:block; margin:0 auto; max-width:min(320px,88vw); height:auto;
  border:1px solid #c3ae82; }}
figcaption {{ font-size:.88rem; font-style:italic; color:#5d4a33; margin-top:.8rem;
  max-width:24rem; margin-left:auto; margin-right:auto; }}
.chart {{ margin:2.4rem 0; }}
.chart svg {{ width:100%; height:auto; }}
.grid {{ stroke:#ddceac; stroke-width:1; }}
.ax {{ font:11px "Hoefler Text",Georgia,serif; fill:#8a7454; }}
.l {{ fill:none; stroke-linejoin:round; }}
.c1 {{ stroke:#7d2b1b; stroke-width:1.7; }}
.c2 {{ stroke:#2b1f14; stroke-width:1.1; stroke-dasharray:3 4; opacity:.6; }}
.c3 {{ stroke:#2b1f14; stroke-width:2.6; }}
.ann {{ font:12.5px "Hoefler Text",Georgia,serif; fill:#2b1f14; font-style:italic; }}
.ann.r {{ fill:#7d2b1b; }}
.contents {{ margin-top:1rem; }}
.contents a {{ display:block; color:#2b1f14; text-decoration:none; padding:.7rem 0;
  border-bottom:1px solid #ddceac; }}
.contents a:first-child {{ border-top:1px solid #ddceac; }}
.contents a:hover .t {{ color:#7d2b1b; }}
.contents .t {{ font-variant:small-caps; letter-spacing:.08em; font-size:1.02rem; }}
.contents .d {{ font-size:.9rem; font-style:italic; color:#5d4a33; }}
.colophon {{ margin-top:3.4rem; padding-top:1.2rem; border-top:1px solid #ddceac;
  font-size:.85rem; font-style:italic; color:#5d4a33; text-align:center; }}
:focus-visible {{ outline:2px solid #7d2b1b; outline-offset:3px; }}
</style>
<div class="page">
<div class="title">
  <h1>Unnamed Concepts</h1>
  <p class="sub">Being an inquiry into machine knowledge</p>
  <p class="arg">Wherein it is shown that the engines possess ideas for which our
  language has no word, and asked whether a man may yet be taught them.</p>
</div>

<p class="lead">In the year 2025 a company of researchers opened the mind of a chess engine
and found within it concepts belonging to no human tradition. They filtered these for what
could be taught, and taught them to four grandmasters of the first rank — using not a
single word of explanation, for no words exist. Every one of the four improved.</p>

<p>This treatise concerns the reproduction of that finding upon open engines, and the
question it leaves standing: whether such knowledge is the property of grandmasters alone,
or may be conveyed to any player of sufficient strength.</p>

<div class="orn">✦ ✦ ✦</div>

<h2>Of the extent of the matter</h2>
<p>Forty-three thousand six hundred and three positions were drawn from games actually
played, and each submitted to the engine and to a model of human choice. In <b>4.0%</b> of
them the engine's preference was plain and strong, and yet no human of any rating — from the
novice at 1100 to the master at 2600 — would play it with better than one chance in twenty.</p>

<p>In <b>1,499</b> of these positions the player then at the board likewise failed to find
the move. In <b>247</b>, that player held a rating of 2500 or better.</p>

<figure>{board("#efe0bd", "#a97f4e", 320)}
<figcaption>White to play. The engine prepares b4 — an advance toward its own king. A
grandmaster shown this position remarked that it was <i class="q">&ldquo;not natural.&rdquo;</i></figcaption></figure>

<h2>That blindness becomes disbelief</h2>
<p>Upon ordinary positions the human draws nearer to the engine as he grows stronger. Upon
these positions he does not. The rate at which he plays the machine's move remains near zero
across the whole span of skill.</p>
<p>Yet something does change. The rate at which the move appears anywhere among his candidates
climbs from 29 in the hundred to 57. The strong player sees the move. He simply does not
believe it.</p>

<div class="chart"><svg viewBox="0 0 700 300" role="img" aria-label="Find-rate by rating">{g}
<text x="{gx+12}" y="{300-42-(67.9/70)*(300-18-42)+22}" class="ann r">ordinary positions</text>
<text x="{gx+12}" y="{300-42-(57.1/70)*(300-18-42)+22}" class="ann">considered</text>
<text x="{gx+12}" y="{300-42-(2.6/70)*(300-18-42)+4}" class="ann">played</text>
</svg></div>

<h2>Of the character of these moves</h2>
<p>They are quiet. Between seventy-two and ninety-two in the hundred are neither captures nor
checks. That which is invisible to us is not tactics — tactics are precisely what our training
drills — but the still move whose reason lies elsewhere.</p>
<p>And they are but half-nameable. Measured against twelve named motifs, less than half of
what distinguishes them can be so expressed: a flavour of sacrifice without its combination.
The remainder has no name in our language at all.</p>

<div class="orn">✦ ✦ ✦</div>

<h2>Contents of the volume</h2>
<div class="contents">
{"".join(f'<a href="{u}"><div class="t">{t}</div><div class="d">{d}</div></a>' for t, d, u in LINKS)}
</div>

<p class="colophon">Composed at a laptop, August 2026. After Schut and others,
<i>Proceedings of the National Academy of Sciences</i>, 2025.</p>
</div>"""

# ══════════════════════════════════════════════════════════════════════════════
# 3 · BROADSIDE — oversized editorial
# ══════════════════════════════════════════════════════════════════════════════
broadside = f"""<title>Unnamed Concepts</title>
<style>
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#e8e4dc; color:#111; overflow-x:hidden;
  font-family:"Avenir Next","Helvetica Neue",Helvetica,sans-serif; font-size:17px; line-height:1.6; }}
.hero {{ min-height:96vh; padding:3.4rem clamp(1.2rem,5vw,5rem) 3rem; display:flex;
  flex-direction:column; justify-content:space-between; position:relative; overflow:hidden; }}
.rule {{ border-top:1.5px solid #111; display:flex; justify-content:space-between;
  padding-top:.7rem; font-size:.78rem; letter-spacing:.18em; text-transform:uppercase; }}
.big {{ font-family:Didot,"Bodoni 72","Playfair Display",Georgia,serif; font-weight:400;
  font-size:clamp(3.4rem,12.5vw,11rem); line-height:.86; letter-spacing:-.025em; margin:2.4rem 0 0;
  max-width:14ch; }}
.big em {{ font-style:italic; color:#c1350f; }}
.hero .board {{ position:absolute; right:clamp(-5rem,-6vw,-2rem); top:38%;
  width:clamp(17rem,34vw,29rem); transform:rotate(-4deg); opacity:.97;
  filter:drop-shadow(0 18px 40px rgba(0,0,0,.22)); pointer-events:none; }}
.hero .board svg {{ width:100%; height:auto; display:block; }}
.hero .foot {{ display:flex; gap:3rem; align-items:flex-end; flex-wrap:wrap;
  position:relative; z-index:2; }}
.hero .dek {{ font-size:clamp(1.05rem,1.8vw,1.5rem); line-height:1.4; max-width:26ch;
  font-weight:500; }}
.hero .scroll {{ font-size:.78rem; letter-spacing:.18em; text-transform:uppercase;
  color:#111; text-decoration:none; border-bottom:1.5px solid #c1350f; padding-bottom:.2rem; }}
section {{ padding:5rem clamp(1.2rem,5vw,5rem); border-top:1.5px solid #111; }}
.band {{ background:#111; color:#f4f1ea; }}
.band .stat {{ font-family:Didot,"Bodoni 72",Georgia,serif; font-size:clamp(4rem,14vw,12rem);
  line-height:.85; letter-spacing:-.03em; margin:0; }}
.band .stat em {{ font-style:normal; color:#ff7a4d; }}
.band p {{ font-size:clamp(1rem,1.6vw,1.35rem); max-width:34ch; margin:1.6rem 0 0; line-height:1.45; }}
h2 {{ font-family:Didot,"Bodoni 72",Georgia,serif; font-weight:400; font-size:clamp(2rem,4.5vw,3.4rem);
  line-height:1.02; margin:0 0 1.6rem; letter-spacing:-.02em; max-width:18ch; }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:clamp(1.6rem,4vw,4rem); align-items:start; }}
@media (max-width:820px) {{ .two {{ grid-template-columns:1fr; }} }}
p.body {{ font-size:1.06rem; line-height:1.62; max-width:44ch; }}
b {{ color:#c1350f; font-weight:600; font-variant-numeric:tabular-nums; }}
.chart svg {{ width:100%; height:auto; }}
.grid {{ stroke:#cfcabf; stroke-width:1; }}
.ax {{ font:11px "Avenir Next",sans-serif; fill:#6d675c; letter-spacing:.05em; }}
.l {{ fill:none; stroke-linejoin:round; }}
.c1 {{ stroke:#c1350f; stroke-width:2; }}
.c2 {{ stroke:#111; stroke-width:1.2; stroke-dasharray:4 4; opacity:.5; }}
.c3 {{ stroke:#111; stroke-width:3.4; }}
.ann {{ font:12px "Avenir Next",sans-serif; fill:#111; letter-spacing:.04em; }}
.ann.r {{ fill:#c1350f; }}
.idx a {{ display:grid; grid-template-columns:auto 1fr; gap:1.4rem; align-items:baseline;
  padding:1.5rem 0; border-bottom:1px solid #c8c3b8; text-decoration:none; color:#111; }}
.idx a:first-child {{ border-top:1px solid #c8c3b8; }}
.idx a:hover .t {{ color:#c1350f; }}
.idx .n {{ font-family:Didot,Georgia,serif; font-size:1.6rem; color:#c1350f; line-height:1; }}
.idx .t {{ font-size:clamp(1.3rem,2.6vw,2rem); font-weight:500; letter-spacing:-.015em; line-height:1.15; }}
.idx .d {{ font-size:.98rem; color:#5d5850; margin-top:.3rem; max-width:52ch; }}
footer {{ padding:2.4rem clamp(1.2rem,5vw,5rem) 4rem; font-size:.85rem; color:#5d5850;
  border-top:1.5px solid #111; }}
:focus-visible {{ outline:2px solid #c1350f; outline-offset:3px; }}
</style>

<div class="hero">
  <div class="rule"><span>Unnamed Concepts</span><span>Research in progress · 2026</span></div>
  <div class="board">{board("#efe9dc", "#8f8577", 420, arrow="#c1350fcc")}</div>
  <h1 class="big">Engines know things we never <em>named</em>.</h1>
  <div class="foot">
    <p class="dek">This project mines those things out of open models — and tests whether a
    person can learn them.</p>
    <a class="scroll" href="#idx">The library ↓</a>
  </div>
</div>

<section class="band">
  <p class="stat"><em>4.0%</em></p>
  <p>of 43,603 real positions contain a move the engine calls clearly best — and that no
  simulated human plays at any rating from 1100 to 2600.</p>
</section>

<section>
  <div class="two">
    <div><h2>Blindness becomes disbelief.</h2></div>
    <div>
      <p class="body">On ordinary positions, stronger players agree with the engine more often.
      On machine-unique positions the agreement never comes: top-1 stays flat near zero all the
      way to 2600.</p>
      <p class="body">But the move does enter the candidate list — <b>29%</b> at 1100, <b>57%</b>
      at 2600. Weak players don't see it. Strong players see it and refuse it.</p>
    </div>
  </div>
  <div class="chart" style="margin-top:2.6rem">
    <svg viewBox="0 0 700 300" role="img" aria-label="Find-rate by rating">{g}
    <text x="{gx+12}" y="{300-42-(67.9/70)*(300-18-42)+22}" class="ann r">normal</text>
    <text x="{gx+12}" y="{300-42-(57.1/70)*(300-18-42)+22}" class="ann">considered</text>
    <text x="{gx+12}" y="{300-42-(2.6/70)*(300-18-42)+4}" class="ann">played</text>
    </svg>
  </div>
</section>

<section>
  <div class="two">
    <div><h2>The invisible part isn't tactics.</h2></div>
    <div>
      <p class="body"><b>72–92%</b> of these moves are quiet — no capture, no check. Tactics are
      what human training drills; what we miss are still moves whose reason lies somewhere else.</p>
      <p class="body">And they're only half-nameable. Twelve named motifs explain <b>R² = 0.46</b>
      of what makes them machine-only. The rest has no word in chess.</p>
    </div>
  </div>
</section>

<section id="idx">
  <h2>The library.</h2>
  <div class="idx">
  {"".join(f'<a href="{u}"><div class="n">{i+1}</div><div><div class="t">{t}</div><div class="d">{d}</div></div></a>' for i, (t, d, u) in enumerate(LINKS))}
  </div>
</section>

<footer>August 2026 · after Schut et al., PNAS 2025 · Maia (CSSLab Toronto) · Leela Chess Zero ·
Stockfish 17.1 · everything runs on one laptop</footer>"""

# ══════════════════════════════════════════════════════════════════════════════
# 4 · PLOT — chart is the page
# ══════════════════════════════════════════════════════════════════════════════
gp, gpx, gpy = chart(w=1000, h=520, pad_l=90, pad_r=250, pad_t=50, pad_b=70)
plot = f"""<title>Unnamed Concepts</title>
<style>
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#f7f6f2; color:#17171a;
  font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; font-size:16.5px; line-height:1.6; }}
.wrap {{ max-width:66rem; margin:0 auto; padding:3.6rem 1.6rem 6rem; }}
.top {{ display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:1rem;
  font-size:.78rem; letter-spacing:.16em; text-transform:uppercase; color:#6b6b73;
  border-bottom:1px solid #17171a; padding-bottom:.7rem; }}
h1 {{ font-size:clamp(1.9rem,3.8vw,2.9rem); font-weight:600; letter-spacing:-.028em;
  line-height:1.1; margin:2.4rem 0 .8rem; max-width:22ch; }}
.dek {{ font-size:1.15rem; line-height:1.55; max-width:46ch; color:#3d3d45; margin:0 0 2.8rem; }}
.figwrap {{ margin:0 0 1rem; }}
.figwrap svg {{ width:100%; height:auto; overflow:visible; }}
.grid {{ stroke:#e3e2dc; stroke-width:1; }}
.ax {{ font:12px "Helvetica Neue",sans-serif; fill:#8a8a92; }}
.l {{ fill:none; stroke-linejoin:round; }}
.c1 {{ stroke:#b8b6ae; stroke-width:2; }}
.c2 {{ stroke:#17171a; stroke-width:1.4; stroke-dasharray:5 5; opacity:.45; }}
.c3 {{ stroke:#e0431f; stroke-width:4; }}
.ann {{ font:14px "Helvetica Neue",sans-serif; fill:#17171a; }}
.ann.big {{ font-size:16px; font-weight:600; fill:#e0431f; }}
.ann.mute {{ fill:#8a8a92; }}
.lead {{ stroke:#c9c7c0; stroke-width:1; stroke-dasharray:2 3; }}
.axttl {{ font:11px "Helvetica Neue",sans-serif; fill:#8a8a92; letter-spacing:.14em;
  text-transform:uppercase; }}
figcaption {{ font-size:.92rem; color:#6b6b73; max-width:60ch; margin-bottom:3.4rem;
  padding-top:.8rem; border-top:1px solid #e3e2dc; }}
.pair {{ display:grid; grid-template-columns:1fr 1fr; gap:3.2rem; margin:0 0 3rem; }}
@media (max-width:760px) {{ .pair {{ grid-template-columns:1fr; gap:2rem; }} }}
.pair h2 {{ font-size:1.02rem; font-weight:600; letter-spacing:-.01em; margin:0 0 .5rem; }}
.pair p {{ margin:0; color:#3d3d45; font-size:1rem; max-width:44ch; }}
b {{ color:#e0431f; font-weight:600; font-variant-numeric:tabular-nums; }}
.brd {{ display:flex; gap:2.4rem; align-items:center; flex-wrap:wrap; margin:0 0 3.4rem;
  padding-top:2.4rem; border-top:1px solid #e3e2dc; }}
.brd svg {{ display:block; max-width:min(260px,80vw); height:auto; }}
.brd .cap {{ max-width:34ch; }}
.brd .cap p {{ margin:.4rem 0 0; color:#3d3d45; }}
.brd .cap .q {{ font-size:1.24rem; font-weight:600; letter-spacing:-.015em; line-height:1.3;
  margin:0; }}
.idx {{ border-top:1px solid #17171a; padding-top:.4rem; }}
.idx a {{ display:flex; justify-content:space-between; gap:2rem; align-items:baseline;
  padding:1.15rem 0; border-bottom:1px solid #e3e2dc; text-decoration:none; color:#17171a; }}
.idx a:hover {{ color:#e0431f; }}
.idx .t {{ font-weight:600; font-size:1.06rem; letter-spacing:-.01em; }}
.idx .d {{ color:#6b6b73; font-size:.94rem; text-align:right; max-width:38ch; }}
footer {{ margin-top:3rem; font-size:.85rem; color:#8a8a92; }}
:focus-visible {{ outline:2px solid #e0431f; outline-offset:3px; }}
</style>
<div class="wrap">
<div class="top"><span>Unnamed Concepts</span><span>chess × interpretability · 2026</span></div>

<h1>There are chess moves no human plays — at any strength.</h1>
<p class="dek">43,603 positions from real games, judged by Stockfish and scored against models of
human choice at every rating. This is the gap that survives.</p>

<figure class="figwrap">
<svg viewBox="0 0 1000 520" role="img" aria-label="Rate at which humans select the engine's move, by rating">
<text x="90" y="30" class="axttl">Share of positions where the engine's move is chosen</text>
{gp}
<text x="{gpx+16}" y="{gpy-(67.9/70)*(gpy-50)+5}" class="ann mute">normal positions</text>
<text x="{gpx+16}" y="{gpy-(57.1/70)*(gpy-50)+5}" class="ann mute">in top 5 candidates</text>
<text x="{gpx+16}" y="{gpy-(2.6/70)*(gpy-50)+5}" class="ann big">actually played</text>
<line x1="{gpx}" y1="{gpy-(2.6/70)*(gpy-50)}" x2="{gpx+10}" y2="{gpy-(2.6/70)*(gpy-50)}" class="lead"/>
<line x1="620" y1="{gpy-(57.1/70)*(gpy-50)}" x2="620" y2="{gpy-(2.6/70)*(gpy-50)}" class="lead"/>
<text x="632" y="{gpy-(30/70)*(gpy-50)}" class="ann">seen, then rejected</text>
</svg>
<figcaption>Simulated humans, Maia-3. On machine-unique positions the move enters the candidate
list more and more often as rating climbs — and is played essentially never. Blindness at the
bottom; disbelief at the top.</figcaption>
</figure>

<div class="pair">
  <div><h2>4.0%</h2><p>of all analysed positions are machine-unique: the engine's move is clearly
  best and no simulated human at any rating gives it more than a 5% chance.</p></div>
  <div><h2>1,499</h2><p>of those also defeated the real player at the board. In <b>247</b> of them,
  that player was rated 2500 or above.</p></div>
  <div><h2>72–92%</h2><p>of the moves are quiet — no capture, no check. What we can't see isn't
  tactics; tactics are what training drills.</p></div>
  <div><h2>R² = 0.46</h2><p>of the machine-unique direction is explained by twelve named motifs.
  The other half has no name in chess.</p></div>
</div>

<div class="brd">{board("#eeeae0", "#a7a297", 260, arrow="#e0431fcc")}
<div class="cap"><p class="q">&ldquo;Not natural.&rdquo;</p>
<p>A 2700-rated grandmaster, shown this position. White prepares b4 — advancing toward its
own king. It is the strongest move on the board.</p></div></div>

<div class="idx">
{"".join(f'<a href="{u}"><span class="t">{t}</span><span class="d">{d}</span></a>' for t, d, u in LINKS)}
</div>

<footer>Stockfish 17.1 · Maia-2 / Maia-3 · Leela Chess Zero · after Schut et al., PNAS 2025.
Everything runs on one laptop.</footer>
</div>"""

# ══════════════════════════════════════════════════════════════════════════════
# 5 · NOTEBOOK — lab log
# ══════════════════════════════════════════════════════════════════════════════
notebook = f"""<title>Unnamed Concepts — lab notebook</title>
<style>
* {{ box-sizing:border-box; }}
body {{ margin:0; color:#1c2433; font-size:17px; line-height:1.68;
  font-family:"American Typewriter","Courier New",Courier,monospace;
  background:#eef0e8;
  background-image:linear-gradient(#dce0d4 1px,transparent 1px),
                   linear-gradient(90deg,#dce0d4 1px,transparent 1px);
  background-size:26px 26px; }}
.pad {{ max-width:46rem; margin:0 auto; padding:3.2rem 1.4rem 6rem; }}
.head {{ display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap;
  gap:.6rem; border-bottom:2.5px solid #1c2433; padding-bottom:.7rem; margin-bottom:2.6rem; }}
.head .n {{ font-size:1.35rem; font-weight:700; letter-spacing:-.01em; }}
.head .m {{ font-size:.82rem; color:#5d6675; }}
h1 {{ font-family:"Bradley Hand","Segoe Script","Comic Sans MS",cursive; font-size:clamp(2.1rem,5.4vw,3.1rem);
  line-height:1.1; margin:0 0 1.2rem; color:#16305c; font-weight:700; max-width:20ch;
  transform:rotate(-.7deg); }}
.dek {{ font-size:1.06rem; max-width:46ch; margin:0 0 2.8rem; }}
.entry {{ margin:0 0 2.8rem; position:relative; padding-left:1.6rem;
  border-left:2.5px solid #b8c0ad; }}
.entry .date {{ font-family:"Bradley Hand","Segoe Script",cursive; font-size:1.05rem; color:#a3341f;
  margin:0 0 .3rem; transform:rotate(-.5deg); }}
.entry h2 {{ font-size:1.06rem; font-weight:700; margin:0 0 .6rem; letter-spacing:-.01em; }}
.entry p {{ margin:0 0 .8rem; max-width:52ch; }}
b {{ background:#ffe98a; padding:0 .18em; font-weight:700; }}
s {{ color:#8b93a1; }}
.marg {{ font-family:"Bradley Hand","Segoe Script",cursive; color:#a3341f; font-size:1.02rem;
  line-height:1.4; margin:.8rem 0 0; transform:rotate(-.6deg); max-width:34ch; }}
.marg::before {{ content:"↳ "; }}
.tape {{ display:inline-block; padding:.9rem; background:#fdfcf6; transform:rotate(-1.6deg);
  box-shadow:0 3px 14px rgba(28,36,51,.16); margin:1.2rem 0; position:relative; }}
.tape::before, .tape::after {{ content:""; position:absolute; width:66px; height:22px;
  background:rgba(216,208,168,.72); top:-11px; }}
.tape::before {{ left:12%; transform:rotate(-4deg); }}
.tape::after {{ right:12%; transform:rotate(3deg); }}
.tape svg {{ display:block; max-width:min(280px,78vw); height:auto; }}
.tape .cap {{ font-family:"Bradley Hand","Segoe Script",cursive; font-size:.98rem; color:#16305c;
  margin-top:.6rem; max-width:280px; }}
.chart {{ background:#fdfcf6; border:2.5px solid #1c2433; padding:1.2rem 1rem .6rem; margin:1.4rem 0; }}
.chart svg {{ width:100%; height:auto; }}
.chart .ttl {{ font-size:.82rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
  margin:0 0 .4rem; }}
.grid {{ stroke:#dfe2d6; stroke-width:1; }}
.ax {{ font:11px "American Typewriter",Courier,monospace; fill:#6f7787; }}
.l {{ fill:none; stroke-linejoin:round; }}
.c1 {{ stroke:#6f7787; stroke-width:1.8; }}
.c2 {{ stroke:#16305c; stroke-width:1.2; stroke-dasharray:4 4; opacity:.6; }}
.c3 {{ stroke:#a3341f; stroke-width:3.4; }}
.ann {{ font:12px "American Typewriter",Courier,monospace; fill:#1c2433; }}
.ann.r {{ fill:#a3341f; }}
.todo {{ background:#fdfcf6; border:2.5px dashed #1c2433; padding:1.4rem 1.6rem; margin:2.4rem 0; }}
.todo .t {{ font-weight:700; font-size:.86rem; letter-spacing:.1em; text-transform:uppercase;
  margin:0 0 .8rem; }}
.todo a {{ display:block; color:#1c2433; text-decoration:none; padding:.5rem 0;
  border-bottom:1px dotted #b8c0ad; }}
.todo a:last-child {{ border-bottom:none; }}
.todo a::before {{ content:"☐ "; color:#a3341f; }}
.todo a:hover {{ color:#a3341f; }}
.todo .d {{ display:block; color:#5d6675; font-size:.88rem; padding-left:1.5em; }}
footer {{ font-size:.84rem; color:#5d6675; border-top:2.5px solid #1c2433; padding-top:.9rem; }}
:focus-visible {{ outline:2px solid #a3341f; outline-offset:3px; }}
</style>
<div class="pad">
<div class="head"><span class="n">Notebook — unnamed concepts</span><span class="m">vol. 1 · Aug 2026</span></div>

<h1>Engines know things we never named.</h1>
<p class="dek">Working log of an attempt to mine those things out of open models — and to find
out whether a person can be taught them.</p>

<div class="entry">
<p class="date">Aug 12 — the premise</p>
<h2>Schut et al. taught four grandmasters a concept with no name</h2>
<p>DeepMind mined AlphaZero's internals for knowledge absent from human play, filtered it for
teachability, showed it to four 2600–2800 players using prototype positions and <s>explanations</s>
no words at all. All four improved. One went 0/4 → 42%.</p>
<p class="marg">so: is it four cherry-picked concepts, or is this everywhere?</p>
</div>

<div class="entry">
<p class="date">Aug 13 — mining</p>
<h2>4.0%, and the number won't move</h2>
<p>Ran <b>43,603</b> real positions through Stockfish + Maia. A position counts as machine-unique
when the engine's move is clearly best and no simulated human at <s>2000</s> any rating gives it
over 5%. Rate came out <b>4.0%</b> — identical across five batches, club and elite alike.</p>
<p>In <b>1,499</b> of them the actual player missed it too. <b>247</b> of those were rated 2500+.</p>
<div class="tape">{board("#f0ecdd", "#9aa38f", 280, arrow="#a3341fcc")}
<p class="cap">the b4 position — GM said "not natural"</p></div>
</div>

<div class="entry">
<p class="date">Aug 14 — the curve</p>
<h2>They start seeing it. They still won't play it.</h2>
<p>Top-1 rate on machine-unique positions: flat near zero, 1100 through 2600. But top-5 climbs
<b>29% → 57%</b>. The move enters the candidate list and gets thrown out.</p>
<div class="chart"><p class="ttl">engine move selected, by rating</p>
<svg viewBox="0 0 700 300" role="img" aria-label="Find-rate by rating">{g}
<text x="{gx+12}" y="{300-42-(67.9/70)*(300-18-42)+22}" class="ann">normal</text>
<text x="{gx+12}" y="{300-42-(57.1/70)*(300-18-42)+22}" class="ann">considered</text>
<text x="{gx+12}" y="{300-42-(2.6/70)*(300-18-42)+4}" class="ann r">played</text>
</svg></div>
<p class="marg">blindness at the bottom, disbelief at the top — that's the finding</p>
</div>

<div class="entry">
<p class="date">Aug 14 — character</p>
<h2>Quiet moves, half-nameable</h2>
<p><b>72–92%</b> of them are neither capture nor check. Not tactics — tactics are exactly what
we drill. Regression onto twelve named motifs: <b>R² = 0.46</b>. Sacrifice-flavoured, minus the
combination. The rest has no name.</p>
</div>

<div class="entry">
<p class="date">Aug 15 — n = 1</p>
<h2>Baseline: 0/10</h2>
<p>Subject (tournament player) attempted ten held-out positions cold. Scored zero — and <b>7 of
10</b> picks were exactly the move Maia predicts a typical human plays. A textbook human.
Study phase running; retest pending.</p>
<p class="marg">if the retest moves at all, that's the whole thesis</p>
</div>

<div class="todo"><p class="t">Open in the lab</p>
{"".join(f'<a href="{u}">{t}<span class="d">{d}</span></a>' for t, d, u in LINKS)}
</div>

<footer>Stockfish 17.1 · Maia-2/3 · Leela Chess Zero · after Schut et al. PNAS 2025.
All of it on one laptop.</footer>
</div>"""

OUT.mkdir(parents=True, exist_ok=True)
for name, page in [("preprint", preprint), ("treatise", treatise), ("broadside", broadside),
                   ("plot", plot), ("notebook", notebook)]:
    (OUT / f"{name}.html").write_text(page)
    print(f"{name:10s} {len(page)//1024:>4} KB")
