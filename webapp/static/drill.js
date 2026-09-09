import { Board } from './board.js';
import { postJSON, replay, storage, focusHeading } from './training.js';
import { studyReplay } from './study.js';

export function mountDrill({positions, allPositions, pieces, cid, group, mode, owner}) {
  const get = id => document.getElementById(id);
  const flow = get('practice-flow'), empty = get('practice-empty'), boardEl = get('board');
  const lock = get('lock'), undo = get('undo'), feedback = get('feedback');
  const error = get('save-error'), status = get('save-status'), pickEl = get('pick');
  const byIndex = new Map(allPositions.map(position => [position.idx, position]));
  const key = `mu_pending_drill_v2_${owner}_${cid}_${mode}`;
  const tried = new Set(group.tried), found = new Set(group.found);
  let queue = [...positions], current, board, picked = null, draft = null;
  let pending = false, answered = false, retry = 'save', storageFailed = false;
  let started = Date.now(), sessionCount = 0, sessionHits = 0;

  function validDraft(value) {
    const position = value && byIndex.get(value.position);
    return !!position && value.version === 2 && value.owner === owner && value.cid === cid &&
      value.mode === mode && value.fen === position.fen && position.legal.includes(value.picked) &&
      typeof value.requestId === 'string' && /^[a-f0-9-]{32,36}$/.test(value.requestId) &&
      ['chosen', 'submitted', 'feedback'].includes(value.phase) &&
      (value.phase === 'chosen' ? value.seconds === null :
        Number.isInteger(value.seconds) && value.seconds >= 0 && value.seconds <= 86400);
  }

  function persist() { storageFailed = !storage.set(key, draft); }
  function payload() {
    return {owner, concept: cid, idx: draft.position, fen: draft.fen,
      picked: draft.picked, request_id: draft.requestId, seconds: draft.seconds};
  }

  function load(saved = null) {
    if (!queue.length) {
      flow.hidden = true; empty.hidden = false;
      return;
    }
    current = queue[0]; picked = null; answered = false; draft = saved;
    retry = 'save'; started = Date.now();
    boardEl.replaceChildren(); get('replay').replaceChildren();
    flow.hidden = false; empty.hidden = true;
    get('practice').hidden = false; get('session-done').hidden = true;
    board = new Board(boardEl, {pieces, orientation: current.orientation, interactive: true,
      onSelect: ({uci}) => {
        if (pending || answered) return;
        picked = uci;
        draft = {version: 2, owner, cid, mode, position: current.idx, fen: current.fen,
          picked, requestId: crypto.randomUUID(), phase: 'chosen', seconds: null};
        persist();
        pickEl.textContent = `${uci.slice(0, 2)} → ${uci.slice(2, 4)}${uci[4] ? ' · promotion' : ''}`;
        lock.disabled = false; undo.disabled = false;
      }});
    board.setLegal(current.legal); board.setPosition(current.fen);
    if (saved) {
      picked = saved.picked;
      board.move(picked.slice(0, 2), picked.slice(2, 4), picked[4]);
      board.setLegal([]);
    }
    pickEl.textContent = picked ? `Your saved move: ${picked.slice(0, 2)} → ${picked.slice(2, 4)}` : 'Choose your move.';
    get('stm').textContent = current.stm + ' to move.';
    get('counter').textContent = `This session: ${sessionCount + 1} of ${Math.min(5, sessionCount + queue.length)} · ${queue.length} positions remaining`;
    lock.disabled = !picked; undo.disabled = !picked || saved?.phase !== 'chosen';
    lock.textContent = 'Check move'; error.textContent = ''; status.textContent = '';
    feedback.hidden = true; get('answer-controls').hidden = false;
  }

  function showFeedback(result, restored = false) {
    if (answered) return;
    if (!result || typeof result.correct !== 'boolean' || result.line?.frames?.[0]?.fen !== current.fen) {
      throw new Error('The saved feedback could not be read. Try restoring it again.');
    }
    // Render before acknowledging the response so a failed render remains recoverable.
    const explained = !!result.line.note;
    if (explained) studyReplay(get('replay'), result.line, pieces, picked);
    else replay(get('replay'), result.line, pieces, picked);
    get('practice-reflection').hidden = explained;
    const stats = get('model-stats'); stats.replaceChildren();
    const probability = document.createElement('p'); probability.className = 'small';
    probability.textContent = `Maia, a model of human moves, gives the engine's choice a ${(result.p_best * 100).toFixed(1)}% chance of being played by a 1900 Lichess player.`;
    stats.append(probability);
    if (result.predicted != null) {
      const estimate = document.createElement('p'); estimate.className = 'small';
      estimate.textContent = `The difficulty model estimates ${(result.predicted * 100).toFixed(1)}% exact matches at Lichess 1900. This is a prediction from the source games, not a measurement of your strength.`;
      stats.append(estimate);
    }
    answered = true; sessionCount++; sessionHits += Number(result.correct);
    tried.add(current.idx); if (result.correct) found.add(current.idx);
    draft.phase = 'feedback'; persist();
    const mark = document.createElement('i'); mark.className = result.correct ? 'hit' : 'done'; get('tally').append(mark);
    status.textContent = storageFailed
      ? 'Answer saved. This browser could not keep your place for a reload.'
      : restored ? 'Your saved answer is restored.' : 'Answer saved.';
    get('answer-controls').hidden = true;
    const verdict = get('verdict');
    verdict.textContent = result.correct ? 'You found it.' : 'The engine chose a different move.';
    verdict.className = result.correct ? 'verdict good' : 'verdict';
    get('comparison').textContent = `You played ${result.picked_san}. The engine plays ${result.best_san}.`;
    get('next').textContent = sessionCount === 5 || queue.length === 1 ? 'Finish this session' : 'Next position';
    feedback.hidden = false; error.textContent = ''; focusHeading(verdict);
  }

  function failed(errorValue, action) {
    retry = action; error.textContent = errorValue.message; status.textContent = '';
    lock.textContent = action === 'recover' ? 'Retry restoring' : 'Retry saving';
    lock.disabled = false; undo.disabled = true;
  }

  async function restore() {
    if (pending || answered || !draft) return;
    pending = true; lock.disabled = true; undo.disabled = true;
    status.textContent = 'Restoring your saved answer…'; error.textContent = '';
    try {
      const response = await postJSON('/api/answer/recover', payload());
      if (response.status === 'saved') showFeedback(response.result, true);
      else if (response.status === 'missing') {
        retry = 'save'; lock.disabled = false; lock.textContent = 'Retry saving';
        status.textContent = 'No saved answer was found. Retry saving the same move.';
      } else throw new Error('Your saved answer could not be restored. Try again.');
    } catch (e) { failed(e, 'recover'); }
    finally { pending = false; }
  }

  async function submit() {
    if (pending || answered || !picked || !draft) return;
    pending = true; lock.disabled = true; undo.disabled = true;
    if (draft.phase === 'chosen') {
      draft.phase = 'submitted';
      draft.seconds = Math.max(0, Math.min(86400, Math.round((Date.now() - started) / 1000)));
      persist();
    }
    status.textContent = 'Saving your answer…'; error.textContent = '';
    try { showFeedback(await postJSON('/api/answer', payload())); }
    catch (e) { failed(e, 'save'); }
    finally { pending = false; }
  }

  undo.addEventListener('click', () => {
    if (pending || answered || draft?.phase !== 'chosen') return;
    storage.remove(key); draft = null; picked = null;
    board.setPosition(current.fen); board.setLegal(current.legal);
    pickEl.textContent = 'Choose your move.'; lock.disabled = true; undo.disabled = true;
  });
  lock.addEventListener('click', () => retry === 'recover' ? restore() : submit());
  get('next').addEventListener('click', () => {
    if (!answered || pending) return;
    answered = false;
    storage.remove(key); draft = null; queue.shift();
    if (sessionCount === 5 || queue.length === 0) {
      get('practice').hidden = true; get('session-done').hidden = false;
      get('session-score').textContent = `${sessionHits} / ${sessionCount}`;
      get('session-copy').textContent = 'engine moves found in this session. Your progress is saved.';
      const complete = tried.size === group.total;
      get('session-title').textContent = !queue.length && complete ? 'Group complete'
        : !queue.length && mode === 'missed' ? 'Review complete' : 'Session complete';
      get('group-progress').textContent = `This group: ${tried.size} of ${group.total} positions tried, ${found.size} engine moves found. Each position counts once.`;
      get('continue').hidden = queue.length === 0;
      get('next-group').hidden = queue.length !== 0 || !complete;
      focusHeading(get('session-title'));
    } else { load(); focusHeading(get('counter')); }
  });
  get('continue').addEventListener('click', () => {
    sessionCount = 0; sessionHits = 0; get('tally').replaceChildren();
    load(); focusHeading(get('practice-title'));
  });

  const saved = storage.get(key);
  const usable = validDraft(saved) && (saved.phase !== 'chosen' || positions.some(p => p.idx === saved.position));
  if (saved && !usable) storage.remove(key);
  // Every drill mode follows curriculum order. Earlier entries may still be
  // present in restart or missed mode, but were already visited this session.
  if (usable) queue = [byIndex.get(saved.position), ...queue.filter(p => p.idx > saved.position)];
  load(usable ? saved : null);
  if (usable && saved.phase !== 'chosen') void restore();
}
