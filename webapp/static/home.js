import { Board } from './board.js';
import { focusHeading, replay } from './training.js';

function validDemo(demo) {
  if (!demo || typeof demo.fen !== 'string' || !['w', 'b'].includes(demo.orientation)
      || !Array.isArray(demo.legal) || !demo.legal.includes(demo.best)
      || typeof demo.best_san !== 'string' || typeof demo.explanation !== 'string'
      || typeof demo.human_san !== 'string') return false;
  return [demo.line, demo.human_line].every(line => line
    && line.orientation === demo.orientation
    && Array.isArray(line.frames) && Array.isArray(line.sans)
    && line.frames.length > 1 && line.frames.length === line.sans.length + 1
    && line.frames[0].fen === demo.fen
    && line.frames.every(frame => typeof frame.fen === 'string')
    && line.sans.every(san => typeof san === 'string'))
    && demo.line.frames[1].last === demo.best;
}

export function mountHomeDemo(root, demo, pieces) {
  if (!root || root.dataset.demoReady || !validDemo(demo)) return false;
  const get = id => root.querySelector(`#${id}`);
  const boardEl = get('home-board'), fallback = get('home-fallback');
  const controls = get('home-controls'), answer = get('home-answer');
  const pickedEl = get('home-picked'), check = get('home-check'), undo = get('home-undo');
  const feedback = get('home-feedback'), verdict = get('home-verdict');
  const replayEl = get('home-replay'), retry = get('home-retry');
  const reveal = get('home-reveal');
  const engineChoice = get('home-engine-line'), humanChoice = get('home-human-line');
  const explanation = get('home-explanation'), comparison = get('home-comparison-note');
  if (![boardEl, fallback, controls, answer, pickedEl, check, undo, feedback, verdict,
        replayEl, retry, reveal, engineChoice, humanChoice, explanation, comparison].every(Boolean)) return false;

  let picked = null, checked = false;
  const san = uci => demo.move_sans?.[uci] || `${uci.slice(0, 2)} to ${uci.slice(2, 4)}`;
  const board = new Board(boardEl, {
    pieces, orientation: demo.orientation, interactive: true,
    onSelect: ({ uci }) => {
      if (checked || !demo.legal.includes(uci)) return;
      picked = uci;
      pickedEl.textContent = san(uci);
      check.disabled = false;
      undo.disabled = false;
    },
  });

  function reset(focusBoard = false) {
    const from = picked?.slice(0, 2);
    picked = null;
    checked = false;
    board.setPosition(demo.fen);
    board.setLegal(demo.legal);
    pickedEl.textContent = 'Choose a move';
    check.disabled = true;
    undo.disabled = true;
    feedback.hidden = true;
    verdict.textContent = '';
    verdict.removeAttribute('data-match');
    replayEl.replaceChildren();
    replayEl.hidden = true;
    boardEl.hidden = false;
    controls.hidden = false;
    if (focusBoard) {
      const square = from && boardEl.querySelector(`[data-sq="${from}"]`);
      (square || boardEl.querySelector('.sq[tabindex="0"]'))?.focus({ preventScroll: true });
    }
  }

  function showLine(which) {
    if (!checked) return;
    const engine = which === 'engine';
    // These are the two saved research continuations, never a fabricated line
    // beginning with an arbitrary visitor choice.
    replay(replayEl, engine ? demo.line : demo.human_line, pieces, null,
      engine ? 'Stockfish’s line' : 'Maia’s choice');
    engineChoice.setAttribute('aria-pressed', String(engine));
    humanChoice.setAttribute('aria-pressed', String(!engine));
  }

  undo.addEventListener('click', () => { if (picked && !checked) reset(true); });
  retry.addEventListener('click', () => reset(true));
  engineChoice.addEventListener('click', () => showLine('engine'));
  humanChoice.addEventListener('click', () => showLine('human'));
  function showAnswer(checkMove) {
    if (checked || (checkMove && !picked)) return;
    checked = true;
    const exact = picked === demo.best;
    verdict.textContent = !checkMove ? `Stockfish chooses ${demo.best_san}.`
      : exact ? `You chose Stockfish’s move: ${demo.best_san}.`
        : `You chose ${san(picked)}. Stockfish chooses ${demo.best_san}.`;
    if (checkMove) verdict.dataset.match = String(exact);
    else verdict.removeAttribute('data-match');
    explanation.textContent = demo.explanation;
    humanChoice.textContent = `Maia’s choice: ${demo.human_san}`;
    comparison.textContent = `The comparison follows Maia’s saved choice, ${demo.human_san},`
      + (demo.maia_rating ? ` for a ${demo.maia_rating}-rated player.` : '.');
    board.setLegal([]);
    check.disabled = true;
    undo.disabled = true;
    controls.hidden = true;
    boardEl.hidden = true;
    replayEl.hidden = false;
    feedback.hidden = false;
    showLine('engine');
    focusHeading(verdict);
  }
  check.addEventListener('click', () => showAnswer(true));
  reveal.addEventListener('click', () => showAnswer(false));

  reset();
  fallback.hidden = true;
  answer.hidden = true;
  root.dataset.demoReady = 'true';
  return true;
}

export function initHomepage({ demo, pieces = {}, previews = {} } = {}) {
  mountHomeDemo(document.getElementById('home-demo'), demo, pieces);
  document.querySelectorAll('.mini').forEach(element => {
    const position = previews[element.dataset.cid];
    if (!position) return;
    const board = new Board(element, { pieces, orientation: position.orientation });
    board.setPosition(position.fen);
  });
}
