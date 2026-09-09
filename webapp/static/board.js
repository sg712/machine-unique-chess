/* Interactive chessboard: real piece elements that translate between squares.
   Pieces are absolutely positioned and animated with transforms, so a move
   slides rather than redrawing. Legality comes from the server. */

const FILES = "abcdefgh";
const PIECE_NAMES = { k: 'king', q: 'queen', r: 'rook', b: 'bishop', n: 'knight', p: 'pawn' };

/* Move sounds: real wood-impact recordings (Kenney impact pack, CC0),
   fetched and decoded once at page load so playback is instant. The
   context starts suspended until the browser sees a user gesture, so a
   capture-phase pointerdown listener resumes it before the first move
   completes. */
let muted = false;
try { muted = localStorage.getItem('mu_sound_muted') === '1'; } catch {}
const soundButton = document.getElementById('sound-toggle');
function updateSoundButton() {
  if (!soundButton) return;
  soundButton.textContent = muted ? 'Sound off' : 'Sound on';
  soundButton.setAttribute('aria-pressed', String(!muted));
}
soundButton?.addEventListener('click', () => {
  muted = !muted;
  try { localStorage.setItem('mu_sound_muted', muted ? '1' : '0'); } catch {}
  updateSoundButton();
});
updateSoundButton();
let actx = null;
const sndBufs = {};
try {
  actx = new (window.AudioContext || window.webkitAudioContext)();
  for (const kind of ["move", "capture"]) {
    fetch(`/static/sound/${kind}.mp3?v=2`)
      .then(r => r.arrayBuffer())
      .then(b => actx.decodeAudioData(b))
      .then(buf => { sndBufs[kind] = buf; })
      .catch(() => {});
  }
  document.addEventListener("pointerdown", () => {
    if (actx.state === "suspended") actx.resume();
  }, { capture: true });
} catch (e) { /* no audio available: stay silent */ }

function sound(kind) {
  try {
    if (muted || !actx || !sndBufs[kind]) return;
    if (actx.state === "suspended") actx.resume();
    const src = actx.createBufferSource();
    src.buffer = sndBufs[kind];
    src.connect(actx.destination);
    src.start();
  } catch (e) { /* stay silent */ }
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
    this.el.setAttribute('role', this.interactive ? 'group' : 'img');
    this.el.setAttribute('aria-label', this.interactive
      ? 'Chessboard. Use arrow keys to explore, Home and End for row edges, Control plus Home or End for board corners. Enter or Space selects a piece and destination; Escape cancels.'
      : 'Chess position');
    this.squares = document.createElement("div");
    this.squares.className = "squares";
    this.layer = document.createElement("div");
    this.layer.className = "pieces";
    this.layer.setAttribute("aria-hidden", "true");
    this.el.append(this.squares, this.layer);
    this.#buildSquares();
    this.announcement = document.createElement('span');
    this.announcement.className = 'sr-only';
    this.announcement.setAttribute('aria-live', 'polite');
    this.announcement.setAttribute('aria-atomic', 'true');
    this.el.append(this.announcement);
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
      const d = document.createElement(this.interactive ? "button" : "div");
      if (this.interactive) {
        d.type = 'button'; d.tabIndex = i === 0 ? 0 : -1;
        d.addEventListener('keydown', e => {
          if (e.altKey || e.metaKey) return;
          const navigation = {
            ArrowLeft: row * 8 + Math.max(0, col - 1),
            ArrowRight: row * 8 + Math.min(7, col + 1),
            ArrowUp: Math.max(0, row - 1) * 8 + col,
            ArrowDown: Math.min(7, row + 1) * 8 + col,
            Home: e.ctrlKey ? 0 : row * 8,
            End: e.ctrlKey ? 63 : row * 8 + 7,
          };
          const target = navigation[e.key];
          const activate = e.key === 'Enter' || e.key === ' ';
          if (this.promotion && (target !== undefined || activate || e.key === 'Escape')) {
            e.preventDefault();
            if (e.key === 'Escape') this.promotion.cancel();
            else this.promotion.picker.querySelector('button').focus();
          } else if (target !== undefined) {
            e.preventDefault();
            this.squares.querySelectorAll('.sq').forEach((sq, j) => sq.tabIndex = j === target ? 0 : -1);
            this.squares.children[target].focus();
          } else if (activate) {
            // Native activation is suppressed so one key press makes one choice.
            e.preventDefault();
            if (!e.repeat) d.click();
          } else if (e.key === 'Escape') {
            e.preventDefault();
            this.clearSelection(); this.announcement.textContent = 'Selection cleared. Choose a piece.';
          }
        });
        d.addEventListener('focus', () => {
          this.squares.querySelectorAll('.sq').forEach(sq => sq.tabIndex = sq === d ? 0 : -1);
        });
      } else { d.setAttribute('aria-hidden', 'true'); }
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
    this.promotion?.picker.remove();
    this.promotion = null;
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
    this.#labels();
    if (this.interactive) this.announcement.textContent = `${fen.split(' ')[1] === 'w' ? 'White' : 'Black'} to move. Select a piece to hear its legal destinations.`;
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

  setLegal(list) {
    this.legal = list || [];
    const lostSelection = this.sel && !this.#destsFrom(this.sel).length;
    if (lostSelection) this.sel = null;
    this.#paint();
    if (lostSelection) this.announcement.textContent = 'Selection cleared. Move selection is unavailable.';
  }

  #labels() {
    const description = [];
    const destinations = new Set(this.sel ? this.#destsFrom(this.sel) : []);
    const sources = new Set(this.legal.map(move => move.slice(0, 2)));
    this.squares.querySelectorAll('.sq').forEach(sq => {
      const name = sq.dataset.sq, piece = this.map?.[name];
      const label = piece ? `${piece === piece.toUpperCase() ? 'White' : 'Black'} ${PIECE_NAMES[piece.toLowerCase()]}` : 'empty';
      let state = '';
      if (this.interactive) {
        sq.setAttribute('aria-pressed', String(name === this.sel));
        if (name === this.sel) state = ', selected';
        else if (destinations.has(name)) {
          state = `, legal destination from ${this.sel}`;
          const promotions = this.legal.filter(move => move.startsWith(this.sel + name) && move.length === 5);
          if (promotions.length) state += `, promotion choices: ${promotions.map(move => PIECE_NAMES[move[4]]).join(', ')}`;
        } else if (sources.has(name)) state = ', available to move';
      }
      sq.setAttribute('aria-label', `${name}, ${label}${state}`);
      if (piece) description.push(`${label} on ${sq.dataset.sq}`);
    });
    if (!this.interactive) this.el.setAttribute('aria-label', description.join(', '));
  }

  #choose(from, to) {
    const options = this.legal.filter(m => m.startsWith(from + to));
    if (options.some(m => m.length === 5)) {
      const [col, row] = this.#coords(from);
      this.els.get(from).style.transform = `translate(${col * 100}%, ${row * 100}%)`;
      const picker = document.createElement('div');
      picker.className = 'promotion-picker';
      picker.setAttribute('role', 'group'); picker.setAttribute('aria-label', `Choose a promotion piece for ${to}. Use arrow keys or Tab, Enter or Space to choose, Escape to cancel.`);
      const cancelPromotion = () => {
        picker.remove(); this.promotion = null; this.clearSelection();
        this.announcement.textContent = 'Promotion cancelled. Choose a move.';
        this.squares.querySelector(`[data-sq="${from}"]`).focus();
      };
      for (const uci of options) {
        const b = document.createElement('button'); b.type = 'button'; b.className = 'btn';
        b.textContent = { q: 'Queen', r: 'Rook', b: 'Bishop', n: 'Knight' }[uci[4]];
        b.addEventListener('click', () => {
          picker.remove(); this.promotion = null;
          this.move(from, to, uci[4]); this.onSelect({ from, to, uci });
          this.squares.querySelector(`[data-sq="${to}"]`).focus();
        }); picker.append(b);
      }
      const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'btn ghost'; cancel.textContent = 'Cancel';
      cancel.addEventListener('click', cancelPromotion);
      picker.addEventListener('keydown', e => {
        if (e.altKey || e.metaKey) return;
        const buttons = [...picker.querySelectorAll('button')], index = buttons.indexOf(e.target);
        if (index < 0) return;
        if (e.key === 'Escape') { e.preventDefault(); cancelPromotion(); }
        else if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault(); if (!e.repeat) e.target.click();
        } else if (['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown', 'Home', 'End'].includes(e.key)) {
          e.preventDefault();
          const next = e.key === 'Home' ? 0 : e.key === 'End' ? buttons.length - 1
            : Math.max(0, Math.min(buttons.length - 1, index + (['ArrowLeft', 'ArrowUp'].includes(e.key) ? -1 : 1)));
          buttons[next].focus();
        }
      });
      picker.append(cancel); this.el.append(picker);
      this.promotion = { picker, cancel: cancelPromotion };
      this.announcement.textContent = `${from} to ${to}. Choose a promotion piece.`;
      picker.querySelector('button').focus();
      return;
    }
    this.move(from, to); this.onSelect({ from, to, uci: from + to });
  }

  #destsFrom(sq) {
    return [...new Set(this.legal.filter(m => m.startsWith(sq)).map(m => m.slice(2, 4)))];
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
      window.removeEventListener("pointercancel", cancel);
      if (!dragging) return;                       // plain tap: the click handler takes it
      this.suppressClick = true;                   // eat the ghost click, if one follows:
      setTimeout(() => { this.suppressClick = false; }, 0);   // but never a real one later
      p.classList.remove("drag");
      const dest = document.elementFromPoint(ev.clientX, ev.clientY)
        ?.closest?.(".sq")?.dataset.sq;
      if (dest && this.#destsFrom(sq).includes(dest)) {
        this.#choose(sq, dest);
      } else {
        const [c, r] = this.#coords(sq);
        p.style.transform = `translate(${c * 100}%, ${r * 100}%)`;
      }
      this.sel = null;
      this.#paint();
    };
    const cancel = () => {
      window.removeEventListener("pointermove", mv);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      p.classList.remove("drag");
      const [col, row] = this.#coords(sq);
      p.style.transform = `translate(${col * 100}%, ${row * 100}%)`;
      this.clearSelection();
    };
    window.addEventListener("pointermove", mv);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
  }

  #click(sq) {
    if (!this.interactive) return;
    if (this.suppressClick) { this.suppressClick = false; return; }
    if (this.sel && this.#destsFrom(this.sel).includes(sq)) {
      this.#choose(this.sel, sq);
      this.sel = null;
      this.#paint();
      return;
    }
    const previousSelection = this.sel;
    this.sel = this.map[sq] && this.#destsFrom(sq).length ? sq : null;
    this.#paint();
    if (!this.sel) {
      this.announcement.textContent = !this.legal.length ? 'Move selection is unavailable.'
        : previousSelection ? `${sq} is not a legal destination. Selection cleared. Choose a piece.`
          : this.map[sq] ? `${sq} has no legal move for this turn. Choose another piece.`
            : `${sq} is empty. Choose a piece with a legal move.`;
    }
  }

  #paint() {
    this.squares.querySelectorAll(".sq").forEach(s => s.classList.remove("sel", "dot"));
    this.#labels();
    if (!this.sel) return;
    this.announcement.textContent = `${this.sel} selected. Legal destinations: ${this.#destsFrom(this.sel).join(', ')}. Press Enter or Space on a destination, or Escape to cancel.`;
    this.squares.querySelector(`[data-sq="${this.sel}"]`)?.classList.add("sel");
    for (const d of this.#destsFrom(this.sel)) {
      this.squares.querySelector(`[data-sq="${d}"]`)?.classList.add("dot");
    }
  }

  clearSelection() { this.sel = null; this.#paint(); this.announcement.textContent = ''; }

  /** Slide the piece on `from` to `to`, fading any captured piece.
      One move per position: the board locks afterwards until setLegal
      re-arms it (the Take back handlers do exactly that). */
  move(from, to, promotion = null) {
    const p = this.els.get(from);
    if (!p) return;
    this.legal = [];
    this.sel = null;
    const taken = this.els.get(to);
    sound(taken ? "capture" : "move");
    if (taken) { taken.classList.add("gone"); setTimeout(() => taken.remove(), 220); }
    const [c, r] = this.#coords(to);
    p.style.transform = `translate(${c * 100}%, ${r * 100}%)`;
    p.dataset.sq = to;
    this.els.delete(from);
    this.els.set(to, p);
    const symbol = this.map[from];
    // Castling and en passant must also be reflected in the preview board.
    if (symbol?.toLowerCase() === 'k' && Math.abs(FILES.indexOf(to[0]) - FILES.indexOf(from[0])) === 2) {
      const rookFrom = (to[0] === 'g' ? 'h' : 'a') + from[1];
      const rookTo = (to[0] === 'g' ? 'f' : 'd') + from[1];
      const rook = this.els.get(rookFrom);
      if (rook) {
        const [rc, rr] = this.#coords(rookTo); rook.style.transform = `translate(${rc * 100}%, ${rr * 100}%)`;
        rook.dataset.sq = rookTo; this.els.delete(rookFrom); this.els.set(rookTo, rook);
        this.map[rookTo] = this.map[rookFrom]; delete this.map[rookFrom];
      }
    }
    if (symbol?.toLowerCase() === 'p' && from[0] !== to[0] && !taken) {
      const captured = to[0] + from[1]; this.els.get(captured)?.remove();
      this.els.delete(captured); delete this.map[captured];
    }
    this.map[to] = promotion ? (symbol === symbol.toUpperCase() ? promotion.toUpperCase() : promotion) : symbol;
    if (promotion) p.innerHTML = `<svg viewBox="0 0 45 45">${this.pieces[this.map[to]] || ''}</svg>`;
    delete this.map[from];
    this.#labels();
    this.announcement.textContent = `${from} to ${to}${promotion ? ', promoted to ' + PIECE_NAMES[promotion] : ''}. Move selected.`;
    this.squares.querySelectorAll(".sq").forEach(s => s.classList.remove("last"));
    this.squares.querySelector(`[data-sq="${from}"]`)?.classList.add("last");
    this.squares.querySelector(`[data-sq="${to}"]`)?.classList.add("last");
  }
}
