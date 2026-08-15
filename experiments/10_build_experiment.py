"""Exp 10 — the self-transfer experiment (Schut protocol, n=1).

Builds three disjoint position sets from the two clustered families:
  * family 5 (exposedKing/defensive flavor — most human-learnable, 20.5% real-found)
  * family 3 (sacrifice/attraction flavor — hardest, 7.7% real-found)

Sets: baseline quiz (10+10), study prototypes (8+8), retest quiz (10+10).
Writes results/experiment/manifest.json + site/quiz-baseline.html (self-contained,
click-two-squares input, answers hidden until the end, per-position timing).
"""
import base64
import json
import pathlib

import chess
import chess.svg
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXP = ROOT / "results" / "experiment"
FAMILIES = [5, 3]
SEED = 42


def eligible(df: pd.DataFrame) -> pd.DataFrame:
    keep = []
    for r in df.itertuples():
        if len(str(r.engine_best)) != 4:          # skip promotions
            continue
        b = chess.Board(r.fen)
        if b.is_check():                           # skip forced-ish check evasions
            continue
        keep.append(r.Index)
    return df.loc[keep]


def main() -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    mu = pd.read_csv(ROOT / "results" / "08_mu_with_families.csv")

    sets = {"baseline": [], "study": [], "retest": []}
    for fam in FAMILIES:
        pool = eligible(mu[mu.family == fam]).sample(frac=1, random_state=SEED)
        n = len(pool)
        assert n >= 28, f"family {fam}: only {n} eligible"
        chunks = {"baseline": pool.iloc[:10], "study": pool.iloc[10:18], "retest": pool.iloc[18:28]}
        for k, chunk in chunks.items():
            for r in chunk.itertuples():
                sets[k].append({
                    "family": fam, "fen": r.fen, "best": r.engine_best,
                    "human_top": r.human_top_2000, "cost_cp": float(r.human_cost_cp),
                    "source": getattr(r, "source", "club"),
                })

    json.dump(sets, open(EXP / "manifest.json", "w"), indent=1)
    print({k: len(v) for k, v in sets.items()})

    # interleave families, stable shuffle
    quiz = pd.DataFrame(sets["baseline"]).sample(frac=1, random_state=7).to_dict("records")
    quiz = quiz[:10]  # baseline shortened to the 10 actually attempted; 11-20 stay unseen for the retest pool
    positions = []
    for i, p in enumerate(quiz):
        b = chess.Board(p["fen"])
        orient = b.turn  # side to move at bottom
        svg = chess.svg.board(b, size=340, orientation=orient)
        positions.append({
            "id": i, "svg": svg, "orient": "w" if orient else "b",
            "stm": "White" if orient else "Black",
            "b64": base64.b64encode(p["best"].encode()).decode(),
            "family": p["family"],
        })

    pos_json = json.dumps([{k: p[k] for k in ("id", "orient", "stm", "b64", "family")} for p in positions])
    boards_html = "".join(
        f'<div class="pos" id="pos{p["id"]}" style="display:none">{p["svg"]}</div>' for p in positions
    )

    page = """<title>Baseline — machine-move quiz</title>
<style>
:root { --paper:#faf6ee; --ink:#2a2118; --muted:#6f6252; --accent:#8c5a2b; --rule:#e4d9c6;
        --good:#2e7d32; --bad:#b3402a; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --paper:#221c15; --ink:#e8ddcc; --muted:#a3937d; --accent:#d3a05f; --rule:#3a3128; } }
:root[data-theme="dark"] { --paper:#221c15; --ink:#e8ddcc; --muted:#a3937d; --accent:#d3a05f; --rule:#3a3128; }
body { background:var(--paper); color:var(--ink); font-family:Charter,Georgia,serif;
       margin:0; display:flex; flex-direction:column; align-items:center; padding:2rem 1rem 4rem; }
h1 { font-size:1.4rem; margin:.2rem 0; } .sub { color:var(--muted); font-size:.9rem; margin-bottom:1rem;
     max-width:26rem; text-align:center; }
#hud { font-family:ui-sans-serif,sans-serif; font-size:.85rem; color:var(--muted); margin-bottom:.6rem; }
#boardwrap { position:relative; width:min(90vw,380px); }
#boardwrap svg { width:100%; height:auto; display:block; border:1px solid var(--rule); border-radius:4px; }
#grid { position:absolute; left:3.846%; top:3.846%; width:92.308%; height:92.308%;
        display:grid; grid-template-columns:repeat(8,1fr); grid-template-rows:repeat(8,1fr); }
#grid div { cursor:pointer; }
#grid div.sel { outline:3px solid var(--accent); outline-offset:-3px; }
#grid div.dst { outline:3px dashed var(--accent); outline-offset:-3px; }
#controls { margin-top:.8rem; display:flex; gap:.8rem; align-items:center; font-family:ui-sans-serif,sans-serif; }
button { font:inherit; padding:.45rem 1.1rem; border-radius:4px; border:1px solid var(--rule);
         background:var(--paper); color:var(--ink); cursor:pointer; }
button.primary { background:var(--accent); color:var(--paper); border-color:var(--accent); }
button:disabled { opacity:.4; cursor:default; }
#movelabel { min-width:6rem; font-weight:600; }
#done { display:none; max-width:30rem; text-align:center; }
#done textarea { width:100%; height:9rem; font-family:monospace; font-size:.72rem; margin-top:.8rem;
                 background:var(--paper); color:var(--ink); border:1px solid var(--rule); }
.score { font-size:2.2rem; font-weight:700; margin:.5rem 0; }
</style>
<h1>Baseline: find the machine's move</h1>
<p class="sub">Real positions, real games — the engine's choice was invisible to simulated humans
and missed by the player at the board. Click the from-square, then the to-square, then Lock in.
No feedback until the end. Take your time.</p>
<div id="hud"></div>
<div id="boardwrap">__BOARDS__<div id="grid"></div></div>
<div id="controls">
  <span id="movelabel">—</span>
  <button id="clear">Clear</button>
  <button id="lock" class="primary" disabled>Lock in</button>
</div>
<div id="done">
  <h1>Baseline complete</h1>
  <div class="score" id="scoreline"></div>
  <p class="sub">Copy the block below and paste it back to Claude — it's your phase-1 record.</p>
  <textarea id="dump" readonly></textarea>
</div>
<script>
const POS = __POSJSON__;
const FILES = "abcdefgh";
let cur = 0, from = null, to = null, t0 = Date.now();
const answers = [];
const grid = document.getElementById("grid");
const label = document.getElementById("movelabel");
const lock = document.getElementById("lock");

function sq(cell) {
  const p = POS[cur], c = cell % 8, r = Math.floor(cell / 8);
  return p.orient === "w" ? FILES[c] + (8 - r) : FILES[7 - c] + (r + 1);
}
for (let i = 0; i < 64; i++) {
  const d = document.createElement("div");
  d.dataset.cell = i;
  d.onclick = () => {
    const s = sq(+d.dataset.cell);
    if (from === null || (from !== null && to !== null)) {
      from = s; to = null;
      grid.querySelectorAll(".sel,.dst").forEach(e => e.classList.remove("sel", "dst"));
      d.classList.add("sel");
    } else {
      to = s; d.classList.add("dst");
    }
    label.textContent = from + (to ? " → " + to : " → ?");
    lock.disabled = !(from && to);
  };
  grid.appendChild(d);
}
document.getElementById("clear").onclick = () => reset();
function reset() {
  from = to = null; label.textContent = "—"; lock.disabled = true;
  grid.querySelectorAll(".sel,.dst").forEach(e => e.classList.remove("sel", "dst"));
}
function show(i) {
  POS.forEach(p => document.getElementById("pos" + p.id).style.display = "none");
  document.getElementById("pos" + POS[i].id).style.display = "block";
  document.getElementById("hud").textContent =
    "Position " + (i + 1) + " of " + POS.length + " — " + POS[i].stm + " to move";
  t0 = Date.now();
}
lock.onclick = () => {
  const p = POS[cur], picked = from + to, best = atob(p.b64);
  answers.push({ id: p.id, family: p.family, picked, best, correct: picked === best,
                 seconds: Math.round((Date.now() - t0) / 10) / 100 });
  reset();
  if (cur + 1 < POS.length) { cur++; show(cur); }
  else finish();
};
function finish() {
  document.getElementById("boardwrap").style.display = "none";
  document.getElementById("controls").style.display = "none";
  document.getElementById("hud").style.display = "none";
  const n = answers.filter(a => a.correct).length;
  document.getElementById("scoreline").textContent = n + " / " + answers.length;
  document.getElementById("dump").value = JSON.stringify({ phase: "baseline", when: new Date().toISOString(), answers }, null, 0);
  document.getElementById("done").style.display = "block";
}
show(0);
</script>"""
    page = page.replace("__BOARDS__", boards_html).replace("__POSJSON__", pos_json)
    out = ROOT / "site" / "quiz-baseline.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page)
    print(f"wrote {out} ({len(page)//1024} KB, {len(positions)} positions)")


if __name__ == "__main__":
    main()
