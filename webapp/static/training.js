import { Board } from './board.js';

export const storage = {
  get(key) { try { return JSON.parse(localStorage.getItem(key)); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; } },
  remove(key) { try { localStorage.removeItem(key); } catch {} },
};

export async function postJSON(url, payload) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: controller.signal,
    });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data) throw new Error(data?.error || 'Your answer could not be saved. Try again.');
    return data;
  } catch (error) {
    if (error.name === 'AbortError' || error instanceof TypeError) {
      throw new Error('Connection interrupted. Your answer is still here. Try again.');
    }
    throw error;
  } finally { clearTimeout(timeout); }
}

export function focusHeading(element) {
  element.tabIndex = -1;
  element.focus({ preventScroll: true });
  element.scrollIntoView({ block: 'nearest', behavior: 'instant' });
}

// One viewer for study feedback, drill feedback, and test review.
export function replay(holder, line, pieces, picked = null, label = 'Engine line') {
  holder.replaceChildren();
  const boardEl = document.createElement('div');
  const controls = document.createElement('div');
  controls.className = 'replay-controls';
  const status = document.createElement('span');
  status.className = 'replay-status';
  status.setAttribute('aria-live', 'polite');
  const moves = document.createElement('div');
  moves.className = 'replay-moves';
  let current = 0;
  const board = new Board(boardEl, { pieces, orientation: line.orientation });
  const button = (label, action) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'btn ghost'; b.textContent = label;
    b.addEventListener('click', action); controls.append(b); return b;
  };
  button('Start position', () => show(0));
  if (picked) button('Your move', () => {
    board.setPosition(line.frames[0].fen);
    board.move(picked.slice(0, 2), picked.slice(2, 4), picked[4]);
    status.textContent = 'Your move';
    moves.querySelectorAll('button').forEach(b => b.removeAttribute('aria-current'));
    previous.disabled = true; next.disabled = false; current = 0;
  });
  const previous = button('Previous move', () => show(current - 1));
  const next = button('Next move', () => show(current + 1));
  line.sans.forEach((san, i) => {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = san;
    b.setAttribute('aria-label', `Move ${i + 1}: ${san}`);
    b.addEventListener('click', () => show(i + 1)); moves.append(b);
  });
  holder.append(boardEl, controls, status, moves);
  function show(n) {
    current = Math.max(0, Math.min(line.frames.length - 1, n));
    const frame = line.frames[current]; board.setPosition(frame.fen, frame.last);
    status.textContent = current ? `${label}, move ${current}: ${line.sans[current - 1]}` : 'Starting position';
    previous.disabled = current === 0; next.disabled = current === line.frames.length - 1;
    moves.querySelectorAll('button').forEach((b, i) => {
      if (i === current - 1) b.setAttribute('aria-current', 'step');
      else b.removeAttribute('aria-current');
    });
  }
  show(1);
}
