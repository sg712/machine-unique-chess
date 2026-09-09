import { JSDOM } from 'jsdom';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const pages = JSON.parse(execFileSync(process.env.TEST_PYTHON || 'python3',
  [path.join(root, 'tests/render_pages.py')], { encoding: 'utf8' }));

async function setup({ orientation = 'w', interactive = true, html } = {}) {
  const dom = new JSDOM(html || '<main><div id="board"></div><button id="after">After board</button></main>',
    { url: 'https://keyboard-fixture.invalid/', runScripts: 'outside-only', pretendToBeVisual: true });
  const window = dom.window, document = window.document;
  window.HTMLElement.prototype.scrollIntoView = function() {};
  window.fetch = async () => { throw new Error('No request expected in this keyboard test'); };
  const context = dom.getInternalVMContext(), modules = new Map();
  async function module(file) {
    if (modules.has(file)) return modules.get(file);
    const result = new vm.SourceTextModule(readFileSync(path.join(root, 'webapp/static', file), 'utf8'),
      { context, identifier: file });
    modules.set(file, result);
    await result.link(specifier => module(path.basename(specifier)));
    return result;
  }
  const boardModule = await module('board.js'); await boardModule.evaluate();
  const selected = [];
  let board;
  if (html) {
    const script = [...document.querySelectorAll('script[type="module"]')].find(item => item.textContent.trim());
    const page = new vm.SourceTextModule(script.textContent, { context });
    await page.link(specifier => module(path.basename(specifier))); await page.evaluate();
  } else {
    board = new boardModule.namespace.Board(document.getElementById('board'),
      { interactive, orientation, onSelect: move => selected.push(move) });
  }
  return { window, document, board, selected,
    boardEl: document.getElementById(html ? 'bsboard' : 'board'),
    close: () => dom.window.close() };
}

function key(s, name, options = {}) {
  const target = s.document.activeElement;
  const event = new s.window.KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true, ...options });
  target.dispatchEvent(event);
  target.dispatchEvent(new s.window.KeyboardEvent('keyup', { key: name, bubbles: true, cancelable: true, ...options }));
  // JSDOM lacks native button keyboard defaults. Board and promotion handlers
  // prevent the default; only ordinary page buttons need this browser behavior.
  if (!event.defaultPrevented && !options.repeat && ['Enter', ' '].includes(name)
      && target.tagName === 'BUTTON' && !target.disabled) target.click();
  return event;
}

function enterBoard(s) { s.boardEl.querySelector('.sq[tabindex="0"]').focus(); }

function navigateTo(s, square) {
  const squares = [...s.boardEl.querySelectorAll('.sq')];
  let current = squares.indexOf(s.document.activeElement);
  if (current < 0) { enterBoard(s); current = squares.indexOf(s.document.activeElement); }
  const target = squares.findIndex(item => item.dataset.sq === square);
  assert.ok(target >= 0);
  while (Math.floor(current / 8) !== Math.floor(target / 8)) {
    key(s, current < target ? 'ArrowDown' : 'ArrowUp');
    current = squares.indexOf(s.document.activeElement);
  }
  while (current !== target) {
    key(s, current < target ? 'ArrowRight' : 'ArrowLeft');
    current = squares.indexOf(s.document.activeElement);
  }
}

function tab(s) {
  const elements = [...s.document.querySelectorAll('a[href], button, [tabindex]')]
    .filter(item => item.tabIndex >= 0 && !item.disabled && !item.closest('[hidden]'));
  elements[(elements.indexOf(s.document.activeElement) + 1) % elements.length].focus();
}

const square = (s, name) => s.boardEl.querySelector(`[data-sq="${name}"]`);
const announcement = s => s.boardEl.querySelector('[aria-live]').textContent;
const WHITE_PAWN = '4k3/8/8/8/8/8/4P3/4K3 w - - 0 1';

for (const orientation of ['w', 'b']) {
  test(`spatial arrows and Home/End stay on their edges (${orientation} orientation)`, async () => {
    const s = await setup({ orientation }); s.board.setPosition(WHITE_PAWN);
    enterBoard(s);
    const first = orientation === 'w' ? 'a8' : 'h1';
    const right = orientation === 'w' ? 'h8' : 'a1';
    assert.equal(s.document.activeElement.dataset.sq, first);
    key(s, 'ArrowLeft'); key(s, 'ArrowUp');
    assert.equal(s.document.activeElement.dataset.sq, first);
    key(s, 'End'); assert.equal(s.document.activeElement.dataset.sq, right);
    key(s, 'ArrowRight'); assert.equal(s.document.activeElement.dataset.sq, right);
    key(s, 'ArrowDown');
    assert.equal(s.document.activeElement.dataset.sq, orientation === 'w' ? 'h7' : 'a2');
    key(s, 'Home'); key(s, 'ArrowLeft');
    assert.equal(s.document.activeElement.dataset.sq, orientation === 'w' ? 'a7' : 'h2');
    key(s, 'End', { ctrlKey: true }); key(s, 'ArrowDown'); key(s, 'ArrowRight');
    assert.equal(s.document.activeElement.dataset.sq, orientation === 'w' ? 'h1' : 'a8');
    key(s, 'Home', { ctrlKey: true }); assert.equal(s.document.activeElement.dataset.sq, first);
    assert.equal(s.boardEl.querySelectorAll('.sq[tabindex="0"]').length, 1);
    s.close();
  });

  test(`Enter and Space choose one legal move with accessible destinations (${orientation} orientation)`, async () => {
    const s = await setup({ orientation });
    s.board.setPosition(WHITE_PAWN); s.board.setLegal(['e2e3', 'e2e4', 'e1d1']);
    assert.match(square(s, 'e2').getAttribute('aria-label'), /White pawn, available to move/);
    navigateTo(s, 'e2');
    assert.equal(key(s, ' ').defaultPrevented, true);
    assert.equal(square(s, 'e2').getAttribute('aria-pressed'), 'true');
    assert.match(square(s, 'e2').getAttribute('aria-label'), /selected/);
    assert.match(square(s, 'e3').getAttribute('aria-label'), /empty, legal destination from e2/);
    assert.match(square(s, 'e4').getAttribute('aria-label'), /legal destination from e2/);
    assert.match(announcement(s), /Legal destinations: e3, e4/);
    navigateTo(s, 'e4');
    assert.equal(key(s, 'Enter').defaultPrevented, true);
    key(s, 'Enter', { repeat: true });
    assert.equal(s.selected.length, 1); assert.equal(s.selected[0].uci, 'e2e4');
    assert.equal(s.document.activeElement.dataset.sq, 'e4');
    assert.equal(s.board.map.e4, 'P');
    assert.equal(square(s, 'e2').getAttribute('aria-label'), 'e2, empty');
    assert.equal(square(s, 'e4').getAttribute('aria-label'), 'e4, White pawn');
    assert.equal(s.boardEl.querySelectorAll('[aria-pressed="true"]').length, 0);
    assert.match(announcement(s), /Move selected/);
    tab(s); assert.equal(s.document.activeElement.id, 'after');
    s.close();
  });
}

test('empty squares, illegal destinations, Escape and withdrawn legal moves clear stale state', async () => {
  const s = await setup(); s.board.setPosition(WHITE_PAWN); s.board.setLegal(['e2e3', 'e2e4']);
  navigateTo(s, 'f3'); key(s, 'Enter'); assert.match(announcement(s), /f3 is empty/);
  navigateTo(s, 'e8'); key(s, ' '); assert.match(announcement(s), /no legal move for this turn/);
  navigateTo(s, 'e2'); key(s, 'Enter');
  navigateTo(s, 'f3'); key(s, ' ');
  assert.match(announcement(s), /not a legal destination. Selection cleared/);
  assert.doesNotMatch(square(s, 'e3').getAttribute('aria-label'), /legal destination/);
  navigateTo(s, 'e2'); key(s, ' '); key(s, 'Escape');
  assert.match(announcement(s), /Selection cleared/);
  assert.equal(square(s, 'e2').getAttribute('aria-pressed'), 'false');
  key(s, 'Enter'); s.board.setLegal([]);
  assert.match(announcement(s), /Move selection is unavailable/);
  assert.equal(s.boardEl.querySelector('.dot'), null);
  assert.doesNotMatch(square(s, 'e2').getAttribute('aria-label'), /available to move|selected/);
  s.board.setPosition(WHITE_PAWN);
  assert.match(announcement(s), /^White to move/);
  assert.equal(s.selected.length, 0); s.close();
});

for (const [orientation, color, fen, from, to] of [
  ['w', 'White', '4k3/P7/8/8/8/8/8/4K3 w - - 0 1', 'a7', 'a8'],
  ['b', 'White', '4k3/P7/8/8/8/8/8/4K3 w - - 0 1', 'a7', 'a8'],
  ['b', 'Black', '4k3/8/8/8/8/8/7p/4K3 b - - 0 1', 'h2', 'h1'],
]) {
  test(`keyboard promotion offers each destination once and returns focus (${color}, ${orientation})`, async () => {
    const s = await setup({ orientation }); s.board.setPosition(fen);
    s.board.setLegal([from + to + 'q', from + to + 'n']);
    navigateTo(s, from); key(s, 'Enter');
    assert.equal(announcement(s).match(new RegExp(to, 'g')).length, 1);
    assert.match(square(s, to).getAttribute('aria-label'), /promotion choices: queen, knight/);
    navigateTo(s, to); key(s, ' ');
    assert.equal(s.document.activeElement.textContent, 'Queen');
    assert.equal(s.selected.length, 0);
    assert.match(announcement(s), /Choose a promotion piece/);
    key(s, 'ArrowRight'); assert.equal(s.document.activeElement.textContent, 'Knight');
    key(s, ' ');
    assert.equal(s.selected.length, 1); assert.equal(s.selected[0].uci, from + to + 'n');
    assert.equal(s.board.map[to], color === 'White' ? 'N' : 'n');
    assert.equal(s.document.activeElement.dataset.sq, to);
    assert.equal(s.boardEl.querySelector('.promotion-picker'), null);
    assert.match(square(s, to).getAttribute('aria-label'), new RegExp(`${color} knight`));
    assert.match(announcement(s), /promoted to knight. Move selected/);
    s.close();
  });
}

test('promotion Escape and keyboard Cancel keep the pawn and restore source focus', async () => {
  const s = await setup({ orientation: 'b' });
  s.board.setPosition('4k3/8/8/8/8/8/7p/4K3 b - - 0 1'); s.board.setLegal(['h2h1q', 'h2h1n']);
  for (const cancel of ['Escape', 'Cancel']) {
    navigateTo(s, 'h2'); key(s, ' '); navigateTo(s, 'h1'); key(s, 'Enter');
    if (cancel === 'Escape') key(s, 'Escape');
    else { key(s, 'End'); assert.equal(s.document.activeElement.textContent, 'Cancel'); key(s, 'Enter'); }
    assert.equal(s.document.activeElement.dataset.sq, 'h2');
    assert.equal(s.board.map.h2, 'p'); assert.equal(s.board.map.h1, undefined);
    assert.equal(s.selected.length, 0);
    assert.equal(s.boardEl.querySelector('.promotion-picker'), null);
    assert.match(announcement(s), /Promotion cancelled/);
  }
  s.close();
});

test('capture destinations describe the opponent piece and update after a keyboard move', async () => {
  const s = await setup(); s.board.setPosition('4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1');
  s.board.setLegal(['e4d5']); navigateTo(s, 'e4'); key(s, 'Enter');
  assert.match(square(s, 'd5').getAttribute('aria-label'), /Black pawn, legal destination from e4/);
  navigateTo(s, 'd5'); key(s, ' ');
  assert.equal(square(s, 'd5').getAttribute('aria-label'), 'd5, White pawn');
  assert.equal(square(s, 'e4').getAttribute('aria-label'), 'e4, empty');
  s.close();
});

test('static and flipped previews remain images without selectable square state', async () => {
  const s = await setup({ orientation: 'b', interactive: false });
  s.board.setPosition(WHITE_PAWN); s.board.setLegal(['e2e4']);
  assert.equal(s.boardEl.getAttribute('role'), 'img');
  assert.match(s.boardEl.getAttribute('aria-label'), /White pawn on e2/);
  assert.equal(s.boardEl.querySelector('button'), null);
  assert.equal(s.boardEl.querySelector('[aria-pressed]'), null);
  assert.equal(square(s, 'e2').getAttribute('aria-label'), 'e2, White pawn');
  s.close();
});

test('saving a test move focuses the new position counter instead of a disabled button', async () => {
  const s = await setup({ html: pages.quiz });
  const source = s.boardEl.querySelector('.sq[aria-label$="available to move"]').dataset.sq;
  navigateTo(s, source); key(s, 'Enter');
  const destination = [...s.boardEl.querySelectorAll('.sq')].find(item => item.getAttribute('aria-label').includes('legal destination')).dataset.sq;
  navigateTo(s, destination); key(s, ' ');
  if (s.boardEl.querySelector('.promotion-picker')) key(s, 'Enter');
  tab(s); assert.equal(s.document.activeElement.id, 'bsundo');
  tab(s); assert.equal(s.document.activeElement.id, 'bslock'); key(s, 'Enter');
  assert.equal(s.document.activeElement.id, 'bscounter');
  assert.equal(s.document.activeElement.textContent, 'Position 2 of 12');
  assert.equal(s.document.getElementById('bslock').disabled, true);
  assert.equal(s.boardEl.querySelectorAll('.sq[tabindex="0"]').length, 1);
  s.close();
});
