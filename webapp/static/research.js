import { replay } from './training.js';

const pieces = JSON.parse(document.getElementById('research-pieces').textContent);
document.querySelectorAll('.research-position').forEach(position => {
  const board = position.querySelector('.research-board');
  const original = board.innerHTML;
  const detail = position.querySelector('.research-reveal');
  const controls = position.querySelector('.research-line-controls');
  const lines = JSON.parse(position.querySelector('.research-lines').textContent);
  function show(which) {
    replay(board, lines[which], pieces);
    board.querySelector('.replay-controls button').click();
    controls.querySelectorAll('button').forEach(button =>
      button.setAttribute('aria-pressed', String(button.dataset.line === which)));
  }
  detail.addEventListener('toggle', () => {
    controls.hidden = !detail.open;
    if (detail.open) show('engine');
    else board.innerHTML = original;
  });
  controls.querySelectorAll('button').forEach(button =>
    button.addEventListener('click', () => show(button.dataset.line)));
});
