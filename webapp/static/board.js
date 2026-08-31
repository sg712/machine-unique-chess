/* Interactive chessboard: real piece elements that translate between squares.
   Pieces are absolutely positioned and animated with transforms, so a move
   slides rather than redrawing. Legality comes from the server. */

const FILES = "abcdefgh";

/* Move sounds, synthesized on the fly so there is nothing to load.
   A short pitch-dropping sine reads as a wooden knock; captures get a
   second, lower knock right behind the first. */
let actx = null;
function sound(kind) {
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    if (actx.state === "suspended") actx.resume();
    const t = actx.currentTime;
    const knock = (at, f0, f1, vol, dur) => {
      const o = actx.createOscillator(), g = actx.createGain();
      o.type = "sine";
      o.frequency.setValueAtTime(f0, at);
      o.frequency.exponentialRampToValueAtTime(f1, at + dur);
      g.gain.setValueAtTime(vol, at);
      g.gain.exponentialRampToValueAtTime(0.001, at + dur);
      o.connect(g); g.connect(actx.destination);
      o.start(at); o.stop(at + dur + 0.02);
    };
    if (kind === "capture") { knock(t, 190, 70, 0.5, 0.1); knock(t + 0.05, 150, 60, 0.35, 0.09); }
    else knock(t, 240, 95, 0.4, 0.08);
  } catch (e) { /* no audio available: stay silent */ }
}

function parseFen(fen) {
  const map = {};
  const rows = fen.split(" ")[0].split("/");
  rows.forEach((row, r) => {
    let f = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) { f += +ch; continue; }
      map[FILES[f] + (8 - r)] = ch;
      f++;
    }
  });
  return map;
}

export class Board {
  constructor(el, opts = {}) {
    this.el = el;
    this.pieces = opts.pieces || {};
    this.orientation = opts.orientation || "w";
    this.interactive = !!opts.interactive;
    this.onSelect = opts.onSelect || (() => {});
    this.legal = [];
    this.sel = null;
    this.els = new Map();
    this.el.classList.add("board");
    if (this.interactive) this.el.classList.add("live");
    this.el.innerHTML = "";
    this.squares = document.createElement("div");
    this.squares.className = "squares";
    this.layer = document.createElement("div");
    this.layer.className = "pieces";
    this.el.append(this.squares, this.layer);
    this.#buildSquares();
  }

  #coords(sq) {
    const f = FILES.indexOf(sq[0]), r = +sq[1] - 1;
    return this.orientation === "w" ? [f, 7 - r] : [7 - f, r];
  }

  #buildSquares() {
    for (let i = 0; i < 64; i++) {
      const col = i % 8, row = (i / 8) | 0;
      const f = this.orientation === "w" ? col : 7 - col;
      const r = this.orientation === "w" ? 7 - row : row;
      const name = FILES[f] + (r + 1);
      const d = document.createElement("div");
      d.className = "sq " + ((f + r) % 2 ? "light" : "dark");
      d.dataset.sq = name;
      if (col === 0) d.insertAdjacentHTML("beforeend", `<span class="rk">${r + 1}</span>`);
      if (row === 7) d.insertAdjacentHTML("beforeend", `<span class="fl">${FILES[f]}</span>`);
      d.addEventListener("click", () => this.#click(name));
      d.addEventListener("pointerdown", (e) => this.#dragStart(name, e));
      this.squares.appendChild(d);
    }
  }

  setPosition(fen, lastMove = null) {
    const prevCount = this.map ? Object.keys(this.map).length : null;
    this.fen = fen;
    this.map = parseFen(fen);
    if (lastMove && prevCount !== null) {
      sound(Object.keys(this.map).length < prevCount ? "capture" : "move");
    }
    this.layer.innerHTML = "";
    this.els.clear();
    for (const [sq, sym] of Object.entries(this.map)) this.#place(sq, sym);
    this.squares.querySelectorAll(".sq").forEach(s => s.classList.remove("last"));
    if (lastMove) {
      for (const sq of [lastMove.slice(0, 2), lastMove.slice(2, 4)]) {
        this.squares.querySelector(`[data-sq="${sq}"]`)?.classList.add("last");
      }
    }
    this.clearSelection();
  }

  #place(sq, sym) {
    const p = document.createElement("div");
    p.className = "pc";
    p.innerHTML = `<svg viewBox="0 0 45 45">${this.pieces[sym] || ""}</svg>`;
    const [c, r] = this.#coords(sq);
    p.style.transform = `translate(${c * 100}%, ${r * 100}%)`;
    p.dataset.sq = sq;
    this.layer.appendChild(p);
    this.els.set(sq, p);
  }

  setLegal(list) { this.legal = list || []; }

  #destsFrom(sq) {
    return this.legal.filter(m => m.startsWith(sq)).map(m => m.slice(2, 4));
  }

  /** Drag a piece with the pointer; a small movement still counts as a tap. */
  #dragStart(sq, e) {
    if (!this.interactive || e.button > 0) return;
    if (!(this.map[sq] && this.#destsFrom(sq).length)) return;
    e.preventDefault();
    const p = this.els.get(sq);
    const rect = this.layer.getBoundingClientRect();
    const sz = rect.width / 8;
    const start = { x: e.clientX, y: e.clientY };
    let dragging = false;
    const mv = (ev) => {
      if (!dragging && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 5) return;
      if (!dragging) {
        dragging = true;
        this.sel = sq;
        this.#paint();
        p.classList.add("drag");
      }
      p.style.transform =
        `translate(${ev.clientX - rect.left - sz / 2}px, ${ev.clientY - rect.top - sz / 2}px)`;
    };
    const up = (ev) => {
      window.removeEventListener("pointermove", mv);
      window.removeEventListener("pointerup", up);
      if (!dragging) return;                       // plain tap: the click handler takes it
      this.suppressClick = true;                   // eat the ghost click, if one follows:
      setTimeout(() => { this.suppressClick = false; }, 0);   // but never a real one later
      p.classList.remove("drag");
      const dest = document.elementFromPoint(ev.clientX, ev.clientY)
        ?.closest?.(".sq")?.dataset.sq;
      if (dest && this.#destsFrom(sq).includes(dest)) {
        this.move(sq, dest);
        this.onSelect({ from: sq, to: dest });
      } else {
        const [c, r] = this.#coords(sq);
        p.style.transform = `translate(${c * 100}%, ${r * 100}%)`;
      }
      this.sel = null;
      this.#paint();
    };
    window.addEventListener("pointermove", mv);
    window.addEventListener("pointerup", up);
  }

  #click(sq) {
    if (!this.interactive) return;
    if (this.suppressClick) { this.suppressClick = false; return; }
    if (this.sel && this.#destsFrom(this.sel).includes(sq)) {
      this.move(this.sel, sq);
      this.onSelect({ from: this.sel, to: sq });
      this.sel = null;
      this.#paint();
      return;
    }
    this.sel = this.map[sq] && this.#destsFrom(sq).length ? sq : null;
    this.#paint();
  }

  #paint() {
    this.squares.querySelectorAll(".sq").forEach(s => s.classList.remove("sel", "dot"));
    if (!this.sel) return;
    this.squares.querySelector(`[data-sq="${this.sel}"]`)?.classList.add("sel");
    for (const d of this.#destsFrom(this.sel)) {
      this.squares.querySelector(`[data-sq="${d}"]`)?.classList.add("dot");
    }
  }

  clearSelection() { this.sel = null; this.#paint(); }

  /** Slide the piece on `from` to `to`, fading any captured piece. */
  move(from, to) {
    const p = this.els.get(from);
    if (!p) return;
    const taken = this.els.get(to);
    sound(taken ? "capture" : "move");
    if (taken) { taken.classList.add("gone"); setTimeout(() => taken.remove(), 220); }
    const [c, r] = this.#coords(to);
    p.style.transform = `translate(${c * 100}%, ${r * 100}%)`;
    p.dataset.sq = to;
    this.els.delete(from);
    this.els.set(to, p);
    this.map[to] = this.map[from];
    delete this.map[from];
    this.squares.querySelectorAll(".sq").forEach(s => s.classList.remove("last"));
    this.squares.querySelector(`[data-sq="${from}"]`)?.classList.add("last");
    this.squares.querySelector(`[data-sq="${to}"]`)?.classList.add("last");
  }
}
