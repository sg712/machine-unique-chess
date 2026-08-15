"""Exp 11 — study phase: silent prototype exposure (Schut protocol phase 2).

For the 16 held-out study positions (8 per family), extract a short principal
variation with Stockfish, then render a page of steppable boards: position ->
engine move -> continuation. NO verbal explanations anywhere — teaching is by
example only, exactly as in the GM experiment.
"""
import json
import pathlib

import chess
import chess.engine
import chess.svg
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE = ROOT / "models" / "stockfish-build" / "src" / "stockfish"
PV_PLIES = 6


def main() -> None:
    sets = json.load(open(ROOT / "results" / "experiment" / "manifest.json"))
    study = pd.DataFrame(sets["study"])

    pv_cache_f = ROOT / "results" / "experiment" / "study_pvs.json"
    if pv_cache_f.exists():
        pvs = json.load(open(pv_cache_f))
    else:
        engine = chess.engine.SimpleEngine.popen_uci(str(ENGINE))
        engine.configure({"Threads": 6, "Hash": 512})
        pvs = {}
        for r in study.itertuples():
            info = engine.analyse(chess.Board(r.fen), chess.engine.Limit(depth=20))
            pvs[r.fen] = [m.uci() for m in info["pv"][:PV_PLIES]]
            print(f"pv {r.Index+1}/{len(study)}")
        engine.quit()
        json.dump(pvs, open(pv_cache_f, "w"))

    blocks = {5: [], 3: []}
    sid = 0
    for r in study.itertuples():
        sid += 1
        b = chess.Board(r.fen)
        orient = b.turn
        pv = pvs[r.fen]
        if pv[0] != r.best:
            # depth-20 disagrees with the depth-16 mining move: eval not stable
            # enough to teach from — drop the prototype
            print(f"skip unstable: {r.fen} (d16 {r.best} vs d20 {pv[0]})")
            sid -= 1
            continue
        frames, sans = [chess.svg.board(b, size=340, orientation=orient)], []
        for uci in pv:
            mv = chess.Move.from_uci(uci)
            num, white = b.fullmove_number, b.turn
            sans.append((f"{num}." if white else f"{num}...") + " " + b.san(mv))
            b.push(mv)
            frames.append(chess.svg.board(b, size=340, orientation=orient, lastmove=mv))
        fhtml = "".join(f'<div class="frame{" on" if i == 0 else ""}">{s}</div>' for i, s in enumerate(frames))
        mhtml = " ".join(f'<button class="mv" data-goto="{i+1}">{s}</button>' for i, s in enumerate(sans))
        stm = "White" if orient else "Black"
        blocks[r.family].append(
            f'<div class="proto stepper" data-n="{len(frames)}">'
            f'<p class="head">{stm} to move</p>'
            f'<div class="slboard">{fhtml}</div>'
            f'<div class="ctrl"><button class="nav" data-d="-1">&#9664;</button>'
            f'<span class="pos">start</span>'
            f'<button class="nav" data-d="1">&#9654;</button></div>'
            f'<p class="moves">{mhtml}</p></div>'
        )

    page = f"""<title>Study — prototype positions</title>
<style>
:root {{ --paper:#faf6ee; --ink:#2a2118; --muted:#6f6252; --accent:#8c5a2b; --rule:#e4d9c6; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --paper:#221c15; --ink:#e8ddcc; --muted:#a3937d; --accent:#d3a05f; --rule:#3a3128; }} }}
:root[data-theme="dark"] {{ --paper:#221c15; --ink:#e8ddcc; --muted:#a3937d; --accent:#d3a05f; --rule:#3a3128; }}
body {{ background:var(--paper); color:var(--ink); font-family:Charter,Georgia,serif; margin:0 auto;
       max-width:46rem; padding:2rem 1rem 4rem; }}
h1 {{ font-size:1.4rem; }} h2 {{ font-size:1.15rem; border-top:2px solid var(--accent); padding-top:1rem; margin-top:2.5rem; }}
.sub {{ color:var(--muted); font-size:.9rem; max-width:34rem; }}
.grid {{ display:flex; flex-wrap:wrap; gap:1.5rem; }}
.proto {{ width:min(90vw,340px); }}
.head {{ font-family:ui-sans-serif,sans-serif; font-size:.78rem; color:var(--muted); margin:.2rem 0; }}
.slboard svg {{ width:100%; height:auto; border:1px solid var(--rule); border-radius:3px; }}
.frame {{ display:none; }} .frame.on {{ display:block; }}
.ctrl {{ display:flex; justify-content:center; gap:1rem; align-items:center; margin:.4rem 0;
        font-family:ui-sans-serif,sans-serif; }}
.ctrl .pos {{ font-size:.75rem; color:var(--muted); min-width:6rem; text-align:center; }}
button {{ font:inherit; border:1px solid var(--rule); background:var(--paper); color:var(--accent);
         border-radius:3px; padding:.2rem .6rem; cursor:pointer; }}
button.mv {{ border:none; font-weight:600; color:var(--ink); padding:.05rem .25rem; }}
button.mv.cur {{ background:var(--accent); color:var(--paper); }}
.moves {{ line-height:1.9; }}
</style>
<h1>Study: how the machine plays these</h1>
<p class="sub">Sixteen positions, two families. Step through each line slowly — first move, then the
continuation. No explanations are given, deliberately: absorb what the moves have in common.
Go through all sixteen at least twice. When a line surprises you, sit with it before moving on.</p>
<h2>Set A</h2><div class="grid">{"".join(blocks[5])}</div>
<h2>Set B</h2><div class="grid">{"".join(blocks[3])}</div>
<script>
document.querySelectorAll('.stepper').forEach(function (st) {{
  var n = parseInt(st.dataset.n, 10), cur = 0;
  var frames = st.querySelectorAll('.frame');
  var moves = st.querySelectorAll('button.mv');
  var pos = st.querySelector('.pos');
  function show(i) {{
    cur = Math.max(0, Math.min(n - 1, i));
    frames.forEach(function (f, k) {{ f.classList.toggle('on', k === cur); }});
    moves.forEach(function (m, k) {{ m.classList.toggle('cur', k === cur - 1); }});
    pos.textContent = cur === 0 ? 'start' : moves[cur - 1].textContent;
  }}
  st.querySelectorAll('button.nav').forEach(function (b) {{
    b.addEventListener('click', function () {{ show(cur + parseInt(b.dataset.d, 10)); }});
  }});
  moves.forEach(function (m) {{
    m.addEventListener('click', function () {{ show(parseInt(m.dataset.goto, 10)); }});
  }});
}});
</script>"""
    out = ROOT / "site" / "study.html"
    out.write_text(page)
    print(f"wrote {out} ({len(page)//1024} KB)")


if __name__ == "__main__":
    main()
