import { JSDOM } from 'jsdom';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const pages = JSON.parse(execFileSync(process.env.TEST_PYTHON || 'python3',
  [path.join(root, 'tests/render_pages.py')], { encoding: 'utf8' }));

async function setup({ run = true, demoOverride } = {}) {
  const dom = new JSDOM(pages['/'], {
    url: 'https://fixture.invalid/', runScripts: 'outside-only', pretendToBeVisual: true,
  });
  const window = dom.window, document = window.document;
  window.HTMLElement.prototype.scrollIntoView = function() {};
  const payload = document.getElementById('home-demo-data');
  const demo = JSON.parse(payload.textContent);
  if (demoOverride !== undefined) payload.textContent = JSON.stringify(demoOverride);
  const fetches = [];
  window.fetch = async (...args) => { fetches.push(args); throw new Error('Demo must work without requests'); };
  const context = dom.getInternalVMContext(), modules = new Map();
  async function module(file) {
    if (modules.has(file)) return modules.get(file);
    const result = new vm.SourceTextModule(readFileSync(path.join(root, 'webapp/static', file), 'utf8'),
      { context, identifier: file });
    modules.set(file, result);
    await result.link(specifier => module(path.basename(specifier)));
    return result;
  }
  if (run) {
    const source = [...document.querySelectorAll('script[type="module"]')].find(script => script.textContent.trim());
    const main = new vm.SourceTextModule(source.textContent, { context });
    await main.link(specifier => module(path.basename(specifier)));
    await main.evaluate();
  }
  return { dom, window, document, demo, fetches,
    get: id => document.getElementById(id), close: () => dom.window.close() };
}

function play(s, uci) {
  const board = s.get('home-board');
  board.querySelector(`[data-sq="${uci.slice(0, 2)}"]`).click();
  board.querySelector(`[data-sq="${uci.slice(2, 4)}"]`).click();
}

test('homepage keeps a readable diagram, answer and immediate practice link without JavaScript', async () => {
  const s = await setup({ run: false });
  assert.ok(s.get('home-fallback').querySelector('svg'));
  assert.equal(s.get('home-fallback').hidden, false);
  assert.equal(s.get('home-answer').hidden, false);
  assert.match(s.get('home-answer').textContent, /Nxd6/);
  assert.match(s.get('home-answer').textContent, /Nb7/);
  for (const id of ['home-board', 'home-controls', 'home-replay', 'home-feedback']) assert.equal(s.get(id).hidden, true);
  assert.match(s.get('home-practice').textContent, /Start with four examples/);
  assert.match(s.get('home-practice').getAttribute('href'), /^\/pattern\/\d+$/);
  assert.equal(s.get('home-practice').closest('[hidden]'), null);
  assert.match(s.document.querySelector('.project-intro').textContent, /original collection contained 123,405 Black-to-move/);
  assert.ok(s.document.querySelector('a[href="/research#full-expansion"]'));
  s.close();
});

test('legal selection and takeback work on the actual featured position', async () => {
  const s = await setup();
  assert.equal(s.get('home-demo').dataset.demoReady, 'true');
  assert.equal(s.get('home-fallback').hidden, true);
  assert.equal(s.get('home-answer').hidden, true);
  assert.equal(s.get('home-board').getAttribute('role'), 'group');
  assert.equal(s.get('home-board').querySelectorAll('.sq').length, 64);
  assert.equal(s.get('home-board').querySelectorAll('.sq[tabindex="0"]').length, 1);
  assert.equal(s.get('home-check').disabled, true);
  // White's knight cannot be selected for Black's turn.
  s.get('home-board').querySelector('[data-sq="b5"]').click();
  s.get('home-board').querySelector('[data-sq="d6"]').click();
  assert.equal(s.get('home-check').disabled, true);
  play(s, s.demo.best);
  assert.equal(s.get('home-picked').textContent, s.demo.best_san);
  assert.equal(s.get('home-check').disabled, false);
  assert.equal(s.get('home-undo').disabled, false);
  assert.ok(s.get('home-board').querySelector(`.pc[data-sq="${s.demo.best.slice(2, 4)}"]`));
  s.get('home-undo').click();
  assert.equal(s.get('home-picked').textContent, 'Choose a move');
  assert.equal(s.get('home-check').disabled, true);
  assert.equal(s.get('home-undo').disabled, true);
  assert.ok(s.get('home-board').querySelector(`.pc[data-sq="${s.demo.best.slice(0, 2)}"]`));
  assert.equal(s.document.activeElement.dataset.sq, s.demo.best.slice(0, 2));
  assert.equal(s.fetches.length, 0);
  s.close();
});

test('exact match reveals the saved explanation and shared Stockfish replay without saving an answer', async () => {
  const s = await setup();
  const href = s.get('home-practice').getAttribute('href');
  play(s, s.demo.best);
  s.get('home-check').click();
  assert.equal(s.get('home-verdict').dataset.match, 'true');
  assert.equal(s.get('home-verdict').textContent, `You chose Stockfish’s move: ${s.demo.best_san}.`);
  assert.equal(s.get('home-explanation').textContent, s.demo.explanation);
  assert.equal(s.get('home-feedback').hidden, false);
  assert.equal(s.get('home-board').hidden, true);
  assert.equal(s.get('home-controls').hidden, true);
  assert.equal(s.get('home-replay').hidden, false);
  assert.equal(s.get('home-replay').querySelector('.replay-moves button').textContent, s.demo.best_san);
  assert.match(s.get('home-replay').querySelector('.replay-status').textContent, /Stockfish’s line, move 1/);
  assert.equal(s.get('home-engine-line').getAttribute('aria-pressed'), 'true');
  assert.equal(s.get('home-practice').getAttribute('href'), href);
  assert.equal(s.get('home-practice').closest('[hidden]'), null);
  assert.equal(s.document.activeElement, s.get('home-verdict'));
  assert.equal(s.window.localStorage.length, 0);
  assert.equal(s.fetches.length, 0);
  s.close();
});

test('an arbitrary alternative stays neutral and Maia comparison follows only its saved line', async () => {
  const s = await setup();
  const human = s.demo.human_line.frames[1].last;
  const alternative = s.demo.legal.find(move => move !== s.demo.best && move !== human);
  assert.ok(alternative);
  play(s, alternative);
  s.get('home-check').click();
  assert.equal(s.get('home-verdict').dataset.match, 'false');
  assert.equal(s.get('home-verdict').textContent,
    `You chose ${s.demo.move_sans[alternative]}. Stockfish chooses ${s.demo.best_san}.`);
  assert.doesNotMatch(s.get('home-verdict').textContent, /wrong|bad|blunder|mistake|losing/i);
  assert.equal(s.get('home-verdict').classList.contains('bad'), false);
  s.get('home-human-line').click();
  assert.equal(s.get('home-human-line').getAttribute('aria-pressed'), 'true');
  assert.equal(s.get('home-engine-line').getAttribute('aria-pressed'), 'false');
  assert.equal(s.get('home-replay').querySelector('.replay-moves button').textContent, s.demo.human_san);
  assert.match(s.get('home-comparison-note').textContent, /Maia’s saved choice/);
  assert.ok(s.get('home-comparison-note').textContent.includes(String(s.demo.maia_rating)));
  assert.equal([...s.get('home-replay').querySelectorAll('button')].some(button => button.textContent === 'Your move'), false);
  const next = [...s.get('home-replay').querySelectorAll('.replay-controls button')].find(button => button.textContent === 'Next move');
  for (let i = 0; i < s.demo.human_line.sans.length; i++) next.click();
  assert.equal(next.disabled, true);
  assert.ok(s.get('home-replay').querySelector('.replay-status').textContent.endsWith(s.demo.human_line.sans.at(-1)));
  s.get('home-engine-line').click();
  assert.equal(s.get('home-replay').querySelector('.replay-moves button').textContent, s.demo.best_san);
  assert.equal(s.fetches.length, 0);
  s.close();
});

test('retry restores the initial board and allows another independent choice', async () => {
  const s = await setup();
  play(s, s.demo.human_line.frames[1].last);
  s.get('home-check').click();
  s.get('home-human-line').click();
  s.get('home-retry').click();
  assert.equal(s.get('home-feedback').hidden, true);
  assert.equal(s.get('home-verdict').textContent, '');
  assert.equal(s.get('home-verdict').hasAttribute('data-match'), false);
  assert.equal(s.get('home-replay').childElementCount, 0);
  assert.equal(s.get('home-board').hidden, false);
  assert.equal(s.get('home-check').disabled, true);
  assert.equal(s.get('home-undo').disabled, true);
  play(s, s.demo.best);
  s.get('home-check').click();
  assert.equal(s.get('home-verdict').dataset.match, 'true');
  assert.equal(s.get('home-replay').querySelectorAll('.board').length, 1);
  assert.equal(s.fetches.length, 0);
  assert.equal(s.window.localStorage.length, 0);
  s.close();
});

test('missing demo data leaves the fallback usable while group previews still initialize', async () => {
  const s = await setup({ demoOverride: null });
  assert.equal(s.get('home-fallback').hidden, false);
  assert.equal(s.get('home-answer').hidden, false);
  assert.equal(s.get('home-controls').hidden, true);
  assert.equal(s.get('home-board').hidden, true);
  assert.equal(s.get('home-demo').dataset.demoReady, undefined);
  assert.ok(s.document.querySelector('.mini.board'));
  assert.equal(s.fetches.length, 0);
  s.close();
});

test('show answer works without inventing an attempted move and can be retried', async () => {
  const s = await setup();
  assert.equal(s.get('home-check').disabled, true);
  s.get('home-reveal').click();
  assert.equal(s.get('home-verdict').textContent, `Stockfish chooses ${s.demo.best_san}.`);
  assert.equal(s.get('home-verdict').hasAttribute('data-match'), false);
  assert.equal(s.get('home-feedback').hidden, false);
  assert.equal(s.document.activeElement, s.get('home-verdict'));
  assert.equal(s.get('home-replay').querySelector('.replay-moves button').textContent, s.demo.best_san);
  s.get('home-retry').click();
  assert.equal(s.get('home-check').disabled, true);
  assert.equal(s.get('home-feedback').hidden, true);
  play(s, s.demo.best);
  s.get('home-check').click();
  assert.equal(s.get('home-verdict').dataset.match, 'true');
  assert.equal(s.fetches.length, 0);
  s.close();
});
