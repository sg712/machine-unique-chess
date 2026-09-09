import { replay } from './training.js';

// Shared by feedback and the four-example review; never mounted before an attempt.
export function studyReplay(holder, line, pieces, picked = null, prefix = '') {
  holder.replaceChildren();
  const heading = document.createElement('h3');
  heading.textContent = `${prefix ? prefix + ': ' : ''}${line.note.title}`;
  const layout = document.createElement('div');
  layout.className = 'study-layout';
  const viewer = document.createElement('div');
  const label = document.createElement('label');
  label.className = 'study-line-choice';
  label.append('Replay a line');
  const select = document.createElement('select');
  const choices = [
    { label: `Engine: ${line.best_san}`, line, status: 'Engine line' },
    ...(line.comparison ? [{ label: `Compare: ${line.comparison.san} (Maia)`, line: line.comparison, status: 'Comparison line' }] : []),
    ...(line.variations || []).map(v => ({ label: v.label, line: v, status: 'Side variation' })),
  ];
  choices.forEach((choice, i) => {
    const option = document.createElement('option');
    option.value = String(i); option.textContent = choice.label; select.append(option);
  });
  label.append(select);
  const board = document.createElement('div');
  board.className = 'replay';
  if (choices.length > 1) viewer.append(label);
  viewer.append(board);
  const notes = document.createElement('div');
  notes.className = 'study-explanation';
  const paragraphs = line.note.why ? [line.note.why]
    : [line.note.constraint, line.note.purpose, line.note.continuation];
  for (const text of paragraphs.filter(Boolean)) {
    const paragraph = document.createElement('p'); paragraph.textContent = text; notes.append(paragraph);
  }
  if (line.comparison && line.note.alternative) {
    const alternativeHeading = document.createElement('h4');
    alternativeHeading.textContent = `What changes after ${line.comparison.san}?`;
    const alternative = document.createElement('p'); alternative.textContent = line.note.alternative;
    notes.append(alternativeHeading, alternative);
  }
  if (line.note.notice) {
    const notice = document.createElement('p'); notice.className = 'study-notice';
    notice.textContent = line.note.notice; notes.append(notice);
  }
  layout.append(viewer, notes); holder.append(heading, layout);
  function show() {
    const choice = choices[Number(select.value)];
    replay(board, choice.line, pieces, picked, choice.status);
  }
  select.addEventListener('change', show);
  show();
}
