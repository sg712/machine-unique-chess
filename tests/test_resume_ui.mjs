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
  [path.join(root, 'tests/render_pages.py')], {encoding: 'utf8'}));
const DRAFT_KEY = 'mu_study_draft_0';

async function setup(html = pages['/pattern/0'], saved = {mu_tut_seen: 1}, fetch) {
  const dom = new JSDOM(html, {url: 'https://resume-test.invalid', runScripts: 'outside-only', pretendToBeVisual: true});
  const w = dom.window;
  w.HTMLElement.prototype.scrollIntoView = function() {};
  w.fetch = fetch || (async () => { throw new w.TypeError('offline'); });
  Object.entries(saved).forEach(([key, value]) => w.localStorage.setItem(key, JSON.stringify(value)));
  const context = dom.getInternalVMContext(), modules = new Map();
  async function getModule(file) {
    if (modules.has(file)) return modules.get(file);
    const module = new vm.SourceTextModule(readFileSync(path.join(root, 'webapp/static', file), 'utf8'), {context});
    modules.set(file, module);
    await module.link(spec => getModule(path.basename(spec)));
    return module;
  }
  const script = [...w.document.querySelectorAll('script[type="module"]')].find(s => s.textContent.trim());
  const module = new vm.SourceTextModule(script.textContent, {context});
  await module.link(spec => getModule(path.basename(spec)));
  await module.evaluate();
  return {dom, document: w.document, storage: w.localStorage};
}

function play(document) {
  for (const square of document.querySelectorAll('.board.live .sq')) {
    square.click();
    const destination = document.querySelector('.board.live .sq.dot');
    if (destination) { destination.click(); return; }
  }
  throw new Error('No legal move found');
}
function snapshot(s) {
  return Object.fromEntries(Array.from({length: s.storage.length}, (_, i) => {
    const key = s.storage.key(i); return [key, JSON.parse(s.storage.getItem(key))];
  }));
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('study restores the chosen move, checked feedback, and next example after reload', async () => {
  const first = await setup();
  play(first.document);
  const chosen = first.document.getElementById('trypick').textContent;
  let saved = snapshot(first); first.dom.window.close();
  const second = await setup(undefined, saved);
  assert.equal(second.document.getElementById('trypick').textContent, chosen);
  assert.equal(second.document.getElementById('trylock').disabled, false);
  assert.equal(second.document.querySelector('#try-replay .study-explanation'), null);
  second.document.getElementById('trylock').click();
  saved = snapshot(second); second.dom.window.close();
  const third = await setup(undefined, saved);
  assert.ok(third.document.querySelector('#try-replay .study-explanation'));
  assert.equal(third.document.getElementById('try-next-controls').hidden, false);
  third.document.getElementById('trynext').click();
  assert.equal(third.document.activeElement.id, 'trycounter');
  saved = snapshot(third); third.dom.window.close();
  const fourth = await setup(undefined, saved);
  assert.equal(fourth.document.getElementById('trycounter').textContent, 'Position 2 of 4');
  assert.equal(fourth.document.querySelector('#try-replay .study-explanation'), null);
  assert.match(fourth.document.querySelector('#trytally i').className, /hit|done/);
  fourth.dom.window.close();
});

test('study keeps completed comparison and a deliberately restarted lesson', async () => {
  const first = await setup();
  for (let i = 0; i < 4; i++) {
    play(first.document); first.document.getElementById('trylock').click(); first.document.getElementById('trynext').click();
  }
  assert.equal(first.document.activeElement.id, 'study-title');
  let saved = snapshot(first); first.dom.window.close();
  const second = await setup(undefined, saved);
  assert.equal(second.document.getElementById('studyStage').style.display, '');
  assert.equal(second.document.querySelectorAll('#protos .study-explanation').length, 4);
  second.document.getElementById('redo').click();
  play(second.document); second.document.getElementById('tryundo').click();
  saved = snapshot(second); second.dom.window.close();
  const third = await setup(pages['/pattern/0'].replace('const SERVER_STUDIED = false;', 'const SERVER_STUDIED = true;'), saved);
  assert.equal(third.document.getElementById('trycounter').textContent, 'Position 1 of 4');
  assert.equal(third.document.getElementById('trylock').disabled, true);
  assert.equal(third.document.getElementById('studyStage').style.display, 'none');
  third.dom.window.close();
});

test('server study progress opens comparison on a browser with no lesson draft', async () => {
  const s = await setup(pages['/pattern/0'].replace('const SERVER_STUDIED = false;', 'const SERVER_STUDIED = true;'), {});
  assert.equal(s.document.getElementById('studyStage').style.display, '');
  assert.equal(s.document.getElementById('tryStage').style.display, 'none');
  assert.equal(s.document.getElementById('tutorial').style.display, 'none');
  s.dom.window.close();
});

test('invalid, stale, illegal and skipped lesson drafts reset without exposing answers', async () => {
  const first = await setup(); play(first.document);
  const original = snapshot(first)[DRAFT_KEY]; first.dom.window.close();
  const invalid = [null, {index: 99}, {...original, index: -1}, {...original, fingerprint: 'old positions'},
    {...original, answers: [{picked: 'a1a8', checked: true}, null, null, null]},
    {...original, index: 2}, {...original, answers: [...original.answers.slice(0, 1), original.answers[0], null, null]}];
  for (const draft of invalid) {
    const s = await setup(undefined, {mu_tut_seen: 1, [DRAFT_KEY]: draft});
    assert.equal(s.document.getElementById('trycounter').textContent, 'Position 1 of 4');
    assert.equal(s.document.querySelector('#try-replay .study-explanation'), null);
    assert.equal(s.document.getElementById('trylock').disabled, true);
    s.dom.window.close();
  }
});

test('last unseen drill position completes the group and shows the next group action', async () => {
  const html = pages['/pattern/0/drill'];
  const positions = JSON.parse(html.match(/const POS = (.*?), PIECES = /)[1]);
  const last = positions.at(-1);
  const finalPage = html.replace(/const POS = .*?, PIECES = /, `const POS = ${JSON.stringify([last])}, PIECES = `)
    .replace(/const GROUP = .*?, MODE = /, `const GROUP = ${JSON.stringify({tried: positions.slice(0, -1).map(p => p.idx), found: [0], total: 36})}, MODE = `);
  const s = await setup(finalPage, {}, async () => ({ok: true, json: async () => ({
    correct: true, picked_san: 'test', best_san: 'test', p_best: .01,
    line: {orientation: 'w', frames: [{fen: last.fen, last: null}], sans: []}
  })}));
  play(s.document); s.document.getElementById('lock').click(); await flush();
  s.document.getElementById('next').click();
  assert.equal(s.document.getElementById('session-title').textContent, 'Group complete');
  assert.equal(s.document.getElementById('next-group').hidden, false);
  assert.equal(s.document.getElementById('continue').hidden, true);
  assert.match(s.document.getElementById('group-progress').textContent, /36 of 36 positions tried, 2 engine moves found/);
  assert.equal(s.document.activeElement.id, 'session-title');
  s.dom.window.close();
});
