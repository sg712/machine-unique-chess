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
client.get('/review')
with client.session_transaction() as session:
    owner = session['code']
def answer(client, cid, idx, correct):
    with client.session_transaction() as session:
        code = session['code']
    pos = site.BY_ID[cid]['drill'][idx]
    picked = pos['best'] if correct else next(m for m in site.board_of(pos['fen'])['legal'] if m != pos['best'])
    payload = dict(owner=code, concept=cid, idx=idx, fen=pos['fen'], picked=picked,
                   seconds=17, request_id=str(uuid.uuid4()))
    response = client.post('/api/answer', json=payload)
    assert response.status_code == 200
    return payload, response.json
order = [(7, 0), (1, 0), (3, 2), (0, 0)]
for cid, idx in order:
    answer(client, cid, idx, False)
before = client.get('/review').get_data(as_text=True)
payload, result = answer(client, 7, 0, True)
after = client.get('/review').get_data(as_text=True)
answer(client, 1, 0, True)
answer(client, 2, 0, False)
changed = client.get('/review').get_data(as_text=True)
responses = {'7:0':result}
best = {}
for cid, idx in order:
    key = f'{cid}:{idx}'
    best[key] = site.BY_ID[cid]['drill'][idx]['best']
    if key not in responses:
        _, responses[key] = answer(client, cid, idx, True)
answer(client, 2, 0, True)
old_wrong_payload, old_wrong_result = answer(client, 7, 0, False)
old_correct_page = client.get('/review').get_data(as_text=True)
answer(client, 7, 0, True)
old_wrong_page = client.get('/review').get_data(as_text=True)
other = site.app.test_client()
other.get('/review')
answer(other, 7, 0, False)
with other.session_transaction() as session:
    other_owner = session['code']
print(json.dumps(dict(before=before, after=after, changed=changed,
                     old_correct_page=old_correct_page, old_wrong_page=old_wrong_page,
                     old_wrong_payload=old_wrong_payload, old_wrong_result=old_wrong_result,
                     other=other.get('/review').get_data(as_text=True), other_owner=other_owner,
                     owner=owner, payload=payload, result=result, responses=responses, best=best)))
`;
const f = JSON.parse(execFileSync(process.env.TEST_PYTHON || 'python3', ['-c', fixtureCode],
  {encoding:'utf8', maxBuffer:10 * 1024 * 1024}));
const flush = () => new Promise(resolve => setImmediate(resolve));
const ok = data => ({ok:true, json:async () => data});
const key = `mu_pending_drill_v2_${f.owner}_-1_review`;
const draftFor = (phase='submitted') => ({version:2, owner:f.owner, cid:-1, mode:'review',
  position:'7:0', fen:f.payload.fen, picked:f.payload.picked, requestId:f.payload.request_id,
  phase, seconds:phase === 'chosen' ? null : 17, remaining:['1:0','3:2','0:0']});

async function setup(html=f.before, {storage={}, fetch}={}) {
  const dom = new JSDOM(html, {url:'https://mixed-review.invalid/review', runScripts:'outside-only', pretendToBeVisual:true});
  const w = dom.window;
  w.HTMLElement.prototype.scrollIntoView = function() {};
  Object.entries(storage).forEach(([name,value]) => w.localStorage.setItem(name, JSON.stringify(value)));
  const calls = [];
  w.fetch = async (url, init) => {
    const payload = JSON.parse(init.body); calls.push({url,payload});
    if (fetch) return fetch(url, payload, calls.length);
    throw new w.TypeError('offline');
  };
  const context = dom.getInternalVMContext(), modules = new Map();
  async function moduleFor(file) {
    if (modules.has(file)) return modules.get(file);
    const module = new vm.SourceTextModule(readFileSync(path.join(root,'webapp/static',file),'utf8'), {context});
    modules.set(file,module); await module.link(spec => moduleFor(path.basename(spec))); return module;
  }
  const script = [...w.document.querySelectorAll('script[type="module"]')].find(s => s.textContent.trim());
  const module = new vm.SourceTextModule(script.textContent,{context});
  await module.link(spec => moduleFor(path.basename(spec))); await module.evaluate(); await flush();
  return {dom,w,d:w.document,calls,storage:w.localStorage};
}
const click = (s,id) => s.d.getElementById(id).click();
function choose(s, uci) {
  s.d.querySelector(`#board [data-sq="${uci.slice(0,2)}"]`).click();
  s.d.querySelector(`#board [data-sq="${uci.slice(2,4)}"]`).click();
  if (uci.length === 5) {
    const promotion = {q:'Queen',r:'Rook',b:'Bishop',n:'Knight'}[uci[4]];
    [...s.d.querySelectorAll('.promotion-picker button')].find(button => button.textContent === promotion)?.click();
  }
}
function snapshot(s) {
  return Object.fromEntries(Array.from({length:s.storage.length},(_,i) => {
    const name=s.storage.key(i); return [name,JSON.parse(s.storage.getItem(name))];
  }));
}
const correctResponse = async (_url,payload) => ok(f.responses[`${payload.concept}:${payload.idx}`]);

test('mixed review keeps repeated numeric indices distinct and replaces the attempt workspace with feedback', async () => {
  const s=await setup(f.before,{fetch:correctResponse});
  for (const cid of [7,1]) {
    choose(s,f.best[`${cid}:0`]);
    const draft=JSON.parse(s.storage.getItem(key));
    assert.equal(draft.position,`${cid}:0`);
    assert.equal(s.d.getElementById('attempt-workspace').hidden,false);
    click(s,'lock'); await flush();
    assert.equal(s.calls.at(-1).payload.concept,cid);
    assert.equal(s.calls.at(-1).payload.idx,0);
    assert.equal(typeof s.calls.at(-1).payload.idx,'number');
    assert.equal(s.d.getElementById('feedback').hidden,false);
    assert.equal(s.d.getElementById('attempt-workspace').hidden,true);
    assert.equal(s.d.activeElement.id,'verdict');
    click(s,'next');
    assert.equal(s.d.getElementById('attempt-workspace').hidden,false);
    assert.equal(s.d.getElementById('feedback').hidden,true);
  }
  assert.notEqual(s.calls[0].payload.request_id,s.calls[1].payload.request_id);
  assert.match(s.d.getElementById('review-source').textContent,/Pattern 4.*position 3/);
  s.dom.window.close();
});

test('lost mixed save restores after leaving the server queue and preserves the saved nonnumeric tail', async () => {
  const s=await setup(f.before,{storage:{[key]:draftFor('chosen')}});
  click(s,'lock'); await flush();
  assert.equal(s.calls.length,1);
  assert.equal(s.calls[0].payload.concept,7);
  const saved=snapshot(s), sent=s.calls[0].payload;
  assert.deepEqual(saved[key].remaining,['1:0','3:2','0:0']);
  s.dom.window.close();
  const t=await setup(f.after,{storage:saved,fetch:async (url,payload) => {
    assert.equal(url,'/api/answer/recover'); assert.deepEqual(payload,sent);
    return ok({status:'saved',result:f.result});
  }});
  assert.equal(t.d.getElementById('feedback').hidden,false);
  assert.equal(t.d.getElementById('attempt-workspace').hidden,true);
  click(t,'next'); choose(t,f.best['1:0']);
  assert.equal(JSON.parse(t.storage.getItem(key)).position,'1:0');
  assert.deepEqual(JSON.parse(t.storage.getItem(key)).remaining,['3:2','0:0']);
  assert.equal(t.calls.length,1);
  t.dom.window.close();
});

test('mixed reload drops tail positions cleared elsewhere without replacing the saved session order', async () => {
  const s=await setup(f.changed,{storage:{[key]:draftFor()},fetch:async (url,payload) =>
    url.endsWith('/recover') ? ok({status:'saved',result:f.result}) : correctResponse(url,payload)});
  click(s,'next'); choose(s,f.best['3:2']);
  assert.equal(JSON.parse(s.storage.getItem(key)).position,'3:2');
  assert.deepEqual(JSON.parse(s.storage.getItem(key)).remaining,['0:0']);
  click(s,'lock'); await flush(); click(s,'next'); choose(s,f.best['0:0']);
  assert.equal(JSON.parse(s.storage.getItem(key)).position,'0:0');
  assert.deepEqual(JSON.parse(s.storage.getItem(key)).remaining,[]);
  s.dom.window.close();
});

test('mixed drafts reject another owner and invalid queue tails without recovering answers', async () => {
  const original=draftFor();
  const invalid=[{...original,owner:f.other_owner}, {...original,remaining:['1:0','1:0']},
    {...original,remaining:['7:0']}, {...original,remaining:['99:99']},
    {...original,remaining:null}, {...original,fen:'stale'}];
  for (const draft of invalid) {
    const s=await setup(f.before,{storage:{[key]:draft}});
    assert.equal(s.calls.length,0);
    assert.equal(s.storage.getItem(key),null);
    assert.equal(s.d.getElementById('feedback').hidden,true);
    assert.equal(s.d.getElementById('lock').disabled,true);
    s.dom.window.close();
  }
  const s=await setup(f.other,{storage:{[key]:original}});
  assert.equal(s.calls.length,0);
  assert.equal(s.d.getElementById('lock').disabled,true);
  assert.equal(s.d.getElementById('feedback').hidden,true);
  s.dom.window.close();
});

test('failed mixed feedback render leaves the attempt available and retries the exact saved request once', async () => {
  const broken=JSON.parse(JSON.stringify(f.result));
  delete broken.line.note;
  broken.line.sans=null;
  const s=await setup(f.before,{fetch:async (_url,_payload,count) => ok(count === 1 ? broken : f.result)});
  choose(s,f.payload.picked); click(s,'lock'); click(s,'lock'); await flush();
  assert.equal(s.calls.length,1);
  assert.equal(s.d.getElementById('attempt-workspace').hidden,false);
  assert.equal(s.d.getElementById('feedback').hidden,true);
  assert.equal(s.d.getElementById('lock').disabled,false);
  assert.equal(s.d.getElementById('lock').textContent,'Retry saving');
  assert.equal(JSON.parse(s.storage.getItem(key)).phase,'submitted');
  click(s,'lock'); click(s,'lock'); await flush();
  assert.equal(s.calls.length,2);
  assert.deepEqual(s.calls[0].payload,s.calls[1].payload);
  assert.equal(s.d.getElementById('attempt-workspace').hidden,true);
  assert.equal(s.d.getElementById('feedback').hidden,false);
  assert.equal(JSON.parse(s.storage.getItem(key)).phase,'feedback');
  assert.equal(s.d.querySelectorAll('#tally i').length,1);
  s.dom.window.close();
});

test('finishing a short mixed review counts the session without declaring a group complete', async () => {
  const s=await setup(f.before,{fetch:correctResponse});
  for (const position of ['7:0','1:0','3:2','0:0']) {
    choose(s,f.best[position]); click(s,'lock'); await flush(); click(s,'next');
  }
  assert.equal(s.d.getElementById('session-title').textContent,'Review session complete');
  assert.equal(s.d.getElementById('session-score').textContent,'4 / 4');
  assert.match(s.d.getElementById('group-progress').textContent,/0 positions still need another look/);
  assert.equal(s.d.getElementById('next-group').hidden,true);
  assert.equal(s.d.getElementById('continue').hidden,true);
  assert.equal(s.storage.getItem(key),null);
  assert.equal(s.calls.length,4);
  s.dom.window.close();
});

test('restoring an older receipt preserves the review queue from later attempts', async () => {
  const scenarios=[
    {page:f.old_correct_page, draft:{...draftFor(),remaining:[]}, result:f.result, count:1},
    {page:f.old_wrong_page, draft:{...draftFor(),remaining:[],
      picked:f.old_wrong_payload.picked,requestId:f.old_wrong_payload.request_id},
      result:f.old_wrong_result,count:0},
  ];
  for (const scenario of scenarios) {
    const s=await setup(scenario.page,{storage:{[key]:scenario.draft},fetch:async url => {
      assert.equal(url,'/api/answer/recover');
      return ok({status:'saved',result:scenario.result});
    }});
    assert.equal(s.d.getElementById('feedback').hidden,false);
    click(s,'next');
    assert.match(s.d.getElementById('group-progress').textContent,
      new RegExp(`^${scenario.count} position`));
    assert.equal(s.d.getElementById('session-title').textContent,'Review session complete');
    const queueLink=[...s.d.querySelectorAll('#session-done a')].find(link => link.textContent === 'Check review queue');
    assert.equal(queueLink.getAttribute('href'),'/review');
    assert.equal(queueLink.hidden,false);
    assert.equal(s.calls.length,1);
    s.dom.window.close();
  }
});
