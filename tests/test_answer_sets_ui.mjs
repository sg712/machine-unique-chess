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
import copy, json, sys, uuid
sys.path.insert(0, ${JSON.stringify(path.join(root, 'tests'))})
from test_answer_sets import site, synthetic_position
site.CONCEPTS = copy.deepcopy(site.CONCEPTS)
site.BY_ID = {c['id']: c for c in site.CONCEPTS}
p = synthetic_position()
site.BY_ID[0]['drill'][0] = p
client = site.app.test_client()
page = client.get('/pattern/0/drill?mode=restart').get_data(as_text=True)
with client.session_transaction() as session: owner = session['code']
payload = dict(owner=owner, concept=0, idx=0, fen=p['fen'], picked='d2d4',
               grading_id=site.question_version(p), request_id=str(uuid.uuid4()), seconds=3)
result = client.post('/api/answer', json=payload).json
keys = [f'0:{i}' for i in range(12)]
token = site.test_signer().dumps(dict(id=uuid.uuid4().hex, owner=owner, items=keys, bank_id=site.test_bank_id()))
quiz = client.get('/test?attempt=' + token).get_data(as_text=True)
picks = ['d2d4'] + [site.BY_ID[0]['drill'][i]['best'] for i in range(1, 12)]
test_result = client.post('/api/blindspot', json=dict(attempt=token, picks=picks)).json
p['answer']['version'] = 'synthetic-fixture-2'
changed = client.get('/pattern/0/drill?mode=restart').get_data(as_text=True)
print(json.dumps(dict(page=page, owner=owner, payload=payload, result=result,
                     changed=changed, quiz=quiz, picks=picks, test_result=test_result)))
`;
const fixture = JSON.parse(execFileSync(process.env.TEST_PYTHON || 'python3', ['-c', fixtureCode],
  {encoding:'utf8', maxBuffer:20 * 1024 * 1024}));
const flush = () => new Promise(resolve => setImmediate(resolve));

async function mount(page, prepare) {
  const dom = new JSDOM(page, {url:'https://answer-set-test.invalid', runScripts:'outside-only', pretendToBeVisual:true});
  const w = dom.window;
  w.HTMLElement.prototype.scrollIntoView = function() {};
  prepare(w);
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
  await module.link(spec => moduleFor(path.basename(spec))); await module.evaluate();
  await flush();
  return {dom, w, document:w.document};
}

function draft(phase = 'chosen') {
  return {version:2, owner:fixture.owner, cid:0, mode:'restart', phase,
    seconds:phase === 'chosen' ? null : 3, position:0, fen:fixture.payload.fen,
    picked:'d2d4', requestId:fixture.payload.request_id, grading_id:fixture.payload.grading_id};
}
const drillKey = `mu_pending_drill_v2_${fixture.owner}_0_restart`;

test('verified alternative earns credit and defaults to its own continuation, with every accepted branch replayable', async () => {
  const s = await mount(fixture.page, w => {
    w.localStorage.setItem(drillKey, JSON.stringify(draft()));
    w.fetch = async (url, options) => {
      assert.equal(url, '/api/answer');
      assert.equal(JSON.parse(options.body).grading_id, fixture.payload.grading_id);
      return {ok:true, json:async () => fixture.result};
    };
  });
  assert.equal(s.document.querySelector('.study-line-choice'), null);
  s.document.getElementById('lock').click(); await flush();
  assert.equal(s.document.getElementById('verdict').textContent, 'Your move is accepted.');
  assert.match(s.document.getElementById('comparison').textContent, /Accepted moves: d4, e4/);
  assert.match(s.document.querySelector('.replay-status').textContent, /Your accepted move, move 1: d4/);
  assert.equal(s.document.getElementById('model-stats').textContent, '');
  const select = s.document.querySelector('.study-line-choice select');
  assert.equal(select.options.length, 2); assert.equal(select.value, 'd2d4');
  select.value = 'e2e4'; select.dispatchEvent(new s.w.Event('change'));
  assert.match(s.document.querySelector('.replay-status').textContent, /Accepted move, move 1: e4/);
  assert.equal(s.document.querySelector('.study-explanation'), null);
  s.dom.window.close();
});

test('unchosen stale-bank draft is dropped without submitting or revealing feedback', async () => {
  let requests = 0;
  const s = await mount(fixture.changed, w => {
    w.localStorage.setItem(drillKey, JSON.stringify(draft()));
    w.fetch = async () => { requests++; throw new Error('Unexpected request'); };
  });
  assert.equal(requests, 0); assert.equal(s.w.localStorage.getItem(drillKey), null);
  assert.equal(s.document.getElementById('feedback').hidden, true);
  assert.equal(s.document.getElementById('lock').disabled, true);
  s.dom.window.close();
});

test('older receipt remains readable but does not score the new bank or skip its unanswered position', async () => {
  const s = await mount(fixture.changed, w => {
    w.localStorage.setItem(drillKey, JSON.stringify(draft('submitted')));
    w.fetch = async (url, options) => {
      assert.equal(url, '/api/answer/recover');
      assert.equal(JSON.parse(options.body).grading_id, fixture.payload.grading_id);
      return {ok:true, json:async () => ({status:'saved', result:fixture.result})};
    };
  });
  assert.match(s.document.getElementById('save-status').textContent, /previous answers/);
  assert.equal(s.document.getElementById('tally').childElementCount, 0);
  s.document.getElementById('next').click(); await flush();
  assert.equal(s.document.getElementById('feedback').hidden, true);
  assert.match(s.document.getElementById('counter').textContent, /This session: 1 of 5/);
  assert.equal(s.document.getElementById('session-done').hidden, true);
  assert.equal(s.document.getElementById('lock').disabled, true);
  s.dom.window.close();
});

test('missing stale receipts restart the current question and allow a fresh versioned submission', async () => {
  for (const phase of ['submitted', 'feedback', 'unversioned']) {
    const prior = draft(phase === 'unversioned' ? 'submitted' : phase);
    if (phase === 'unversioned') delete prior.grading_id;
    const requests = [];
    const s = await mount(fixture.changed, w => {
      w.localStorage.setItem(drillKey, JSON.stringify(prior));
      w.fetch = async (url, options) => {
        const payload = JSON.parse(options.body); requests.push({url, payload});
        if (url === '/api/answer/recover') return {ok:true, json:async () => ({status:'missing'})};
        assert.equal(url, '/api/answer');
        assert.notEqual(payload.request_id, fixture.payload.request_id);
        assert.notEqual(payload.grading_id, fixture.payload.grading_id);
        return {ok:true, json:async () => ({...fixture.result, grading_id:payload.grading_id})};
      };
    });
    assert.deepEqual(requests.map(request => request.url), ['/api/answer/recover']);
    assert.equal(s.w.localStorage.getItem(drillKey), null);
    assert.match(s.document.getElementById('save-status').textContent, /answers have changed.*Choose your move again/);
    assert.equal(s.document.getElementById('feedback').hidden, true);
    assert.equal(s.document.getElementById('lock').disabled, true);
    assert.equal(s.document.getElementById('tally').childElementCount, 0);
    s.document.querySelector('#board [data-sq="d2"]').click();
    s.document.querySelector('#board [data-sq="d4"]').click();
    assert.equal(s.document.getElementById('lock').disabled, false);
    s.document.getElementById('lock').click(); await flush();
    assert.equal(requests.length, 2);
    assert.equal(s.document.getElementById('feedback').hidden, false);
    assert.equal(s.document.getElementById('tally').childElementCount, 1);
    s.dom.window.close();
  }
});

test('test results count alternative moves and omit incompatible rating comparison', async () => {
  const s = await mount(fixture.quiz, w => {
    const key = 'mu_test_' + JSON.parse(fixture.quiz.match(/const TOKEN = .*?, KEY = 'mu_test_' \+ (.*?);/)[1]);
    w.localStorage.setItem(key, JSON.stringify({picks:fixture.picks, result:fixture.test_result}));
    w.fetch = async () => { throw new Error('Saved result must not resubmit'); };
  });
  assert.equal(s.document.getElementById('test-score').textContent, '12 / 12');
  assert.equal(s.document.getElementById('rating-comparison').hidden, true);
  const item = s.document.querySelector('.position-review');
  assert.match(item.querySelector('.test-review-context').textContent, /Accepted moves: d4, e4/);
  item.open = true; item.dispatchEvent(new s.w.Event('toggle'));
  assert.match(item.querySelector('.replay-status').textContent, /Your accepted move, move 1: d4/);
  s.dom.window.close();
});
