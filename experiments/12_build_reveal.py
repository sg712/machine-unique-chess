"""Exp 12 — phase 2 proper (Schut-faithful): reveal the baseline answers.

For each of the 10 attempted baseline positions: show the position, the move the
subject played (dim arrow), then the machine's move and continuation as steppable
frames. Depth-20 stability check; unstable positions are shown but flagged so they
can be excluded from analysis. No verbal explanations (protocol).
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
    quiz = pd.DataFrame(sets["baseline"]).sample(frac=1, random_state=7).to_dict("records")[:10]
    res = json.load(open(ROOT / "results" / "experiment" / "baseline_result.json"))["answers"]

    cache_f = ROOT / "results" / "experiment" / "reveal_pvs.json"
    if cache_f.exists():
        pvs = json.load(open(cache_f))
    else:
        engine = chess.engine.SimpleEngine.popen_uci(str(ENGINE))
        engine.configure({"Threads": 6, "Hash": 512})
        pvs = {}
        for q in quiz:
            info = engine.analyse(chess.Board(q["fen"]), chess.engine.Limit(depth=20))
            pvs[q["fen"]] = [m.uci() for m in info["pv"][:PV_PLIES]]
        engine.quit()
        json.dump(pvs, open(cache_f, "w"))

    cards = []
    n_unstable = 0
    for q, a in zip(quiz, res):
        b = chess.Board(q["fen"])
        orient = b.turn
        stm = "White" if orient else "Black"
        pv = pvs[q["fen"]]
        stable = pv[0] == q["best"]
        if not stable:
            n_unstable += 1
        picked = chess.Move.from_uci(a["picked"])
        # frame 0: position with the subject's move as a dim arrow
        f0 = chess.svg.board(b, size=340, orientation=orient,
                             arrows=[chess.svg.Arrow(picked.from_square, picked.to_square, color="#b3402acc")])
        frames, sans = [f0], []
        bb = b.copy()
        for uci in pv:
            mv = chess.Move.from_uci(uci)
            num, white = bb.fullmove_number, bb.turn
            sans.append((f"{num}." if white else f"{num}...") + " " + bb.san(mv))
            bb.push(mv)
            frames.append(chess.svg.board(bb, size=340, orientation=orient, lastmove=mv))
        fhtml = "".join(f'<div class="frame{" on" if i == 0 else ""}">{s}</div>' for i, s in enumerate(frames))
        mhtml = " ".join(f'<button class="mv" data-goto="{i+1}">{s}</button>' for i, s in enumerate(sans))
        your_san = b.san(picked) if picked in b.legal_moves else a["picked"]
        flag = ' <span class="warn">(eval unstable at depth 20 — excluded from analysis)</span>' if not stable else ""
        cards.append(
            f'<div class="proto stepper" data-n="{len(frames)}">'
            f'<p class="head">Set {"A" if a["family"] == 5 else "B"} &middot; {stm} to move &middot; '
            f'you played <b class="yours">{your_san}</b>{flag}</p>'
            f'<div class="slboard">{fhtml}</div>'
            f'<div class="ctrl"><button class="nav" data-d="-1">&#9664;</button>'
            f'<span class="pos">your move</span>'
            f'<button class="nav" data-d="1">&#9654;</button></div>'
            f'<p class="moves">{mhtml}</p></div>'
        )

    style = """
:root { --paper:#faf6ee; --ink:#2a2118; --muted:#6f6252; --accent:#8c5a2b; --rule:#e4d9c6; --bad:#b3402a; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --paper:#221c15; --ink:#e8ddcc; --muted:#a3937d; --accent:#d3a05f; --rule:#3a3128; --bad:#e07a5f; } }
:root[data-theme="dark"] { --paper:#221c15; --ink:#e8ddcc; --muted:#a3937d; --accent:#d3a05f; --rule:#3a3128; --bad:#e07a5f; }
body { background:var(--paper); color:var(--ink); font-family:Charter,Georgia,serif; margin:0 auto;
       max-width:46rem; padding:2rem 1rem 4rem; }
h1 { font-size:1.4rem; } .sub { color:var(--muted); font-size:.9rem; max-width:34rem; }
.grid { display:flex; flex-wrap:wrap; gap:1.5rem; }
.proto { width:min(90vw,340px); }
.head { font-family:ui-sans-serif,sans-serif; font-size:.78rem; color:var(--muted); margin:.2rem 0; }
.yours { color:var(--bad); }
.warn { color:var(--bad); font-size:.7rem; }
.slboard svg { width:100%; height:auto; border:1px solid var(--rule); border-radius:3px; }
.frame { display:none; } .frame.on { display:block; }
.ctrl { display:flex; justify-content:center; gap:1rem; align-items:center; margin:.4rem 0;
        font-family:ui-sans-serif,sans-serif; }
.ctrl .pos { font-size:.75rem; color:var(--muted); min-width:6rem; text-align:center; }
button { font:inherit; border:1px solid var(--rule); background:var(--paper); color:var(--accent);
         border-radius:3px; padding:.2rem .6rem; cursor:pointer; }
button.mv { border:none; font-weight:600; color:var(--ink); padding:.05rem .25rem; }
button.mv.cur { background:var(--accent); color:var(--paper); }
.moves { line-height:1.9; }
"""
    script = """
document.querySelectorAll('.stepper').forEach(function (st) {
  var n = parseInt(st.dataset.n, 10), cur = 0;
  var frames = st.querySelectorAll('.frame');
  var moves = st.querySelectorAll('button.mv');
  var pos = st.querySelector('.pos');
  function show(i) {
    cur = Math.max(0, Math.min(n - 1, i));
    frames.forEach(function (f, k) { f.classList.toggle('on', k === cur); });
    moves.forEach(function (m, k) { m.classList.toggle('cur', k === cur - 1); });
    pos.textContent = cur === 0 ? 'your move' : moves[cur - 1].textContent;
  }
  st.querySelectorAll('button.nav').forEach(function (b) {
    b.addEventListener('click', function () { show(cur + parseInt(b.dataset.d, 10)); });
  });
  moves.forEach(function (m) {
    m.addEventListener('click', function () { show(parseInt(m.dataset.goto, 10)); });
  });
});
"""
    page = (f"<title>Reveal — your ten, answered</title>\n<style>{style}</style>\n"
            f"<h1>Phase 2: your ten positions, answered</h1>\n"
            f'<p class="sub">Red arrow: the move you played. Step forward: the machine\'s move and its '
            f'continuation. Two families, labeled A and B. No explanations — watch what the machine '
            f'does instead of what you did, and ask what each set\'s moves have in common.</p>\n'
            f'<div class="grid">{"".join(cards)}</div>\n<script>{script}</script>')
    out = ROOT / "site" / "reveal.html"
    out.write_text(page)
    print(f"wrote {out} ({len(page)//1024} KB), unstable flagged: {n_unstable}/10")


if __name__ == "__main__":
    main()
