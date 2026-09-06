import { JSDOM } from 'jsdom';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = process.env.TEST_PYTHON || 'python3';
const pages = JSON.parse(execFileSync(python, [path.join(root, 'tests/render_pages.py')], { encoding: 'utf8' }));

async function setup(html = '<main><div id="board"></div></main>', options = {}) {
  const dom = new JSDOM(html, { url: 'https://local-test.invalid' + (options.url || '/'), runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  w.HTMLElement.prototype.scrollIntoView = function() {};
  let fetches = [];
  w.fetch = async (url, init) => {
    fetches.push({ url, payload: init ? JSON.parse(init.body) : null });
    if (options.fetch) return options.fetch(url, init);
    throw new w.TypeError('offline');
  };
  if (options.storage) for (const [key, value] of Object.entries(options.storage)) w.localStorage.setItem(key, JSON.stringify(value));
  const context = dom.getInternalVMContext(), modules = new Map();
  async function getModule(file) {
    if (modules.has(file)) return modules.get(file);
    const source = readFileSync(path.join(root, 'webapp/static', file), 'utf8');
    const mod = new vm.SourceTextModule(source, { context, identifier: file }); modules.set(file, mod);
    await mod.link(spec => getModule(path.basename(spec)));
    return mod;
  }
  const board = await getModule('board.js'); await board.evaluate();
  if (options.page) {
    const script = [...w.document.querySelectorAll('script[type="module"]')].find(s => s.textContent.trim());
    if (script) {
      const mod = new vm.SourceTextModule(script.textContent, { context });
      await mod.link(spec => getModule(path.basename(spec)));
      await mod.evaluate();
    }
  }
  return { dom, w, document: w.document, Board: board.namespace.Board, fetches };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function play(document) {
  for (const square of document.querySelectorAll('.board.live .sq')) {
    square.click();
    const dest = document.querySelector('.board.live .sq.dot');
    if (dest) { dest.click(); return; }
  }
  throw new Error('No selectable legal move');
}
const selected = (s, name) => s.document.querySelector(`[data-sq="${name}"]`);

test('keyboard board selects a legal move and locks after selection', async () => {
  const s = await setup(); let move;
  const board = new s.Board(s.document.getElementById('board'), { interactive:true, onSelect:m => move=m });
  board.setPosition('4k3/8/8/8/8/8/4P3/4K3 w - - 0 1'); board.setLegal(['e2e3','e2e4','e1d1']);
  assert.equal(s.document.querySelectorAll('.sq[tabindex="0"]').length, 1);
  assert.match(selected(s,'e2').getAttribute('aria-label'), /White pawn/);
  selected(s,'e2').focus(); selected(s,'e2').click();
  selected(s,'e2').dispatchEvent(new s.w.KeyboardEvent('keydown', {key:'ArrowUp',bubbles:true}));
  assert.equal(s.document.activeElement.dataset.sq, 'e3');
  s.document.activeElement.click();
  assert.equal(move.uci, 'e2e3'); assert.equal(board.map.e3, 'P'); assert.deepEqual(Array.from(board.legal), []);
  assert.match(s.document.querySelector('[aria-live]').textContent, /Move selected/);
  s.dom.window.close();
});

test('promotion, castling and en passant previews reflect the actual pieces', async () => {
  const s = await setup(); let result;
  const board = new s.Board(s.document.getElementById('board'), {interactive:true,onSelect:m=>result=m});
  board.setPosition('4k3/P7/8/8/8/8/8/4K3 w - - 0 1'); board.setLegal(['a7a8q','a7a8n']);
  selected(s,'a7').click(); selected(s,'a8').click();
  [...s.document.querySelectorAll('.promotion-picker button')].find(b=>b.textContent==='Knight').click();
  assert.equal(result.uci,'a7a8n'); assert.equal(board.map.a8,'N');
  board.setPosition('4k3/8/8/8/8/8/8/4K2R w K - 0 1'); board.move('e1','g1');
  assert.equal(board.map.f1,'R'); assert.equal(board.map.h1,undefined);
  board.setPosition('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1'); board.move('e5','d6');
  assert.equal(board.map.d5,undefined); assert.equal(board.map.d6,'P');
  s.dom.window.close();
});

test('homepage and study modules initialize without errors', async () => {
  for (const route of ['/', '/learn','/pattern/0']) {
    const s = await setup(pages[route], {page:true});
    assert.ok(s.document.querySelectorAll('.sq').length || route==='/pattern/0');
    if (route==='/pattern/0') {
      s.document.getElementById('tutgo').click(); play(s.document);
      s.document.getElementById('trylock').click();
      assert.match(s.document.getElementById('tryline').textContent, /engine plays/);
      assert.ok(s.document.querySelector('#try-replay .replay-controls'));
    }
    s.dom.window.close();
  }
});

test('failed drill request preserves the choice and retries using the same id', async () => {
  const s = await setup(pages['/pattern/0/drill'], {page:true});
  play(s.document);
  const lock=s.document.getElementById('lock');lock.click(); await flush();
  assert.match(s.document.getElementById('save-error').textContent,/Connection interrupted/);
  assert.equal(lock.disabled,false); assert.equal(s.document.getElementById('undo').disabled,true);
  lock.click(); await flush();
  assert.equal(s.fetches.length,2);
  assert.equal(s.fetches[0].payload.request_id,s.fetches[1].payload.request_id);
  assert.equal(s.fetches[0].payload.picked,s.fetches[1].payload.picked);
  s.dom.window.close();
});

test('five answers produce a session boundary and allow continuing', async () => {
  const s=await setup(pages['/pattern/0/drill'],{page:true,fetch:async(url,init)=>({ok:true,json:async()=>({
    correct:true,picked_san:'test',best_san:'test',p_best:.01,predicted:.1,
    line:{orientation:'w',frames:[{fen:'4k3/8/8/8/8/8/4P3/4K3 w - - 0 1',last:null}],sans:[]}
  })})});
  for(let i=0;i<5;i++){play(s.document);s.document.getElementById('lock').click();await flush();s.document.getElementById('next').click();}
  assert.equal(s.document.getElementById('session-done').hidden,false);
  assert.equal(s.document.getElementById('session-score').textContent,'5 / 5');
  s.document.getElementById('continue').click();
  assert.equal(s.document.getElementById('practice').hidden,false);
  assert.match(s.document.getElementById('counter').textContent,/session: 1 of 5/);
  s.dom.window.close();
});

test('quiz saves drafts, resumes on reload, and guards final duplicate submission', async () => {
  const s = await setup(pages.quiz,{page:true,url:pages.quiz_url});
  for(let i=0;i<3;i++){play(s.document);s.document.getElementById('bslock').click();}
  const persisted={};for(let i=0;i<s.w.localStorage.length;i++){const k=s.w.localStorage.key(i);persisted[k]=JSON.parse(s.w.localStorage.getItem(k));}
  s.dom.window.close();
  const t=await setup(pages.quiz,{page:true,url:pages.quiz_url,storage:persisted});
  assert.equal(t.document.getElementById('bscounter').textContent,'Position 4 of 12');
  for(let i=3;i<12;i++){play(t.document);t.document.getElementById('bslock').click();}
  t.document.getElementById('bslock').click();await flush();
  assert.equal(t.fetches.length,1);assert.equal(t.fetches[0].payload.picks.length,12);
  assert.equal(t.document.getElementById('retry-test').hidden,false);
  t.document.getElementById('retry-test').click();await flush();
  assert.equal(t.fetches.length,2);assert.deepEqual(t.fetches[0].payload,t.fetches[1].payload);
  t.dom.window.close();
});
