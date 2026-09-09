import { JSDOM } from 'jsdom';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixtureCode = `
import json, sys, uuid
sys.path.insert(0, ${JSON.stringify(path.join(root, 'tests'))})
from test_app import site
client = site.app.test_client()
fixtures = []
for note in site.PRACTICE_NOTES.values():
    cid, idx = note['concept_id'], note['drill_index']
    page = client.get(f'/pattern/{cid}/drill?mode=restart').get_data(as_text=True)
    key = str(uuid.uuid4())
    response = client.post('/api/answer', json={'concept':cid,'idx':idx,'picked':note['best'],'seconds':1,'request_id':key})
    assert response.status_code == 200
    fixtures.append({'page':page,'cid':cid,'idx':idx,'fen':note['fen'],'best':note['best'],'key':key,'response':response.json})
print(json.dumps(fixtures))
`;
const fixtures = JSON.parse(execFileSync(process.env.TEST_PYTHON || 'python3', ['-c', fixtureCode],
  {encoding:'utf8', maxBuffer:20 * 1024 * 1024}));
const flush = () => new Promise(resolve => setImmediate(resolve));

async function setup(fixture) {
  const dom = new JSDOM(fixture.page, {url:'https://practice-test.invalid', runScripts:'outside-only', pretendToBeVisual:true});
  const w = dom.window;
  w.HTMLElement.prototype.scrollIntoView = function() {};
  w.localStorage.setItem(`mu_pending_drill_${fixture.cid}_restart`, JSON.stringify({
    position:fixture.idx, fen:fixture.fen, picked:fixture.best, requestId:fixture.key,
  }));
  let submitted = 0;
  w.fetch = async (_url, options) => {
    const answer = JSON.parse(options.body);
    assert.equal(answer.concept, fixture.cid);
    assert.equal(answer.idx, fixture.idx);
    assert.equal(answer.picked, fixture.best);
    submitted++;
    return {ok:true, json:async () => fixture.response};
  };
  const context = dom.getInternalVMContext(), modules = new Map();
  async function moduleFor(file) {
    if (modules.has(file)) return modules.get(file);
    const module = new vm.SourceTextModule(readFileSync(path.join(root, 'webapp/static', file), 'utf8'), {context});
    modules.set(file, module);
    await module.link(spec => moduleFor(path.basename(spec)));
    return module;
  }
  const script = [...w.document.querySelectorAll('script[type="module"]')].find(s => s.textContent.trim());
  const module = new vm.SourceTextModule(script.textContent, {context});
  await module.link(spec => moduleFor(path.basename(spec)));
  await module.evaluate();
  return {dom, w, document:w.document, submitted:() => submitted};
}

test('reviewed practice notes appear only after checking, with only supported replay choices', async () => {
  assert.equal(fixtures.length, 8);
  for (const fixture of fixtures) {
    const s = await setup(fixture);
    assert.equal(s.document.querySelector('.study-explanation'), null);
    assert.equal(s.document.getElementById('feedback').hidden, true);
    assert.equal(s.submitted(), 0);
    s.document.getElementById('lock').click(); await flush();
    assert.equal(s.submitted(), 1);
    const text = s.document.querySelector('.study-explanation').textContent;
    for (const field of ['constraint','purpose','continuation']) {
      assert.ok(text.includes(fixture.response.line.note[field]));
    }
    assert.equal(s.document.getElementById('practice-reflection').hidden, true);
    const select = s.document.querySelector('.study-line-choice select');
    if (fixture.response.line.comparison) {
      assert.equal(select.options.length, 2);
      select.value = '1'; select.dispatchEvent(new s.w.Event('change'));
      assert.match(s.document.querySelector('.replay-status').textContent, /Comparison line/);
      assert.ok(s.document.querySelector('.replay-status').textContent.includes(fixture.response.line.comparison.san));
    } else {
      assert.equal(select, null);
      assert.match(s.document.querySelector('.replay-status').textContent, /Engine line/);
    }
    s.document.getElementById('next').click();
    assert.equal(s.document.getElementById('feedback').hidden, true);
    s.dom.window.close();
  }
});
