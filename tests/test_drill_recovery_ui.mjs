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
import json, re, sys, uuid
sys.path.insert(0, ${JSON.stringify(path.join(root, 'tests'))})
from test_app import site

def answer(client, idx, picked=None):
    pos = site.BY_ID[0]['drill'][idx]
    with client.session_transaction() as session:
        owner = session['code']
    payload = dict(owner=owner, concept=0, idx=idx, fen=pos['fen'], picked=picked or pos['best'], seconds=17, request_id=str(uuid.uuid4()))
    result = client.post('/api/answer', json=payload)
    assert result.status_code == 200
    return payload, result.json

def page(client, mode='continue'):
    return client.get('/pattern/0/drill?mode='+mode).get_data(as_text=True)

client = site.app.test_client()
before = page(client)
payload, result = answer(client, 0)
normal = dict(before=before, after=page(client), payload=payload, result=result)

client = site.app.test_client()
page(client)
for i in range(35): answer(client, i)
before = page(client)
payload, result = answer(client, 35)
final = dict(before=before, after=page(client), payload=payload, result=result)

client = site.app.test_client()
before = page(client, 'restart')
payload, result = answer(client, 20)
restart = dict(before=before, after=page(client, 'restart'), payload=payload, result=result)

client = site.app.test_client()
page(client)
for i in (1, 3, 5):
    pos = site.BY_ID[0]['drill'][i]
    wrong = next(m for m in site.board_of(pos['fen'])['legal'] if m != pos['best'])
    answer(client, i, wrong)
before = page(client, 'missed')
payload, result = answer(client, 3)
missed = dict(before=before, after=page(client, 'missed'), payload=payload, result=result)
print(json.dumps(dict(normal=normal, final=final, restart=restart, missed=missed)))
`;
const fixtures = JSON.parse(execFileSync(process.env.TEST_PYTHON || 'python3', ['-c', fixtureCode],
  {encoding:'utf8', maxBuffer:20 * 1024 * 1024}));
const flush = () => new Promise(resolve => setImmediate(resolve));
const ok = data => ({ok:true, json:async () => data});
const keyFor = (f, mode='continue') => `mu_pending_drill_v2_${f.payload.owner}_0_${mode}`;
const draftFor = (f, phase='submitted', mode='continue') => ({version:2, owner:f.payload.owner,
  cid:0, mode, position:f.payload.idx, fen:f.payload.fen, picked:f.payload.picked,
  requestId:f.payload.request_id, phase, seconds:phase === 'chosen' ? null : 17});

async function setup(html, {storage={}, fetch, storageFails=false}={}) {
  const dom = new JSDOM(html, {url:'https://recovery-test.invalid', runScripts:'outside-only', pretendToBeVisual:true});
  const w = dom.window;
  w.HTMLElement.prototype.scrollIntoView = function() {};
  Object.entries(storage).forEach(([key,value]) => w.localStorage.setItem(key, JSON.stringify(value)));
  if (storageFails) w.Storage.prototype.setItem = function() {throw new Error('Storage full');};
  const calls = [];
  w.fetch = async (url, options) => {
    const payload = JSON.parse(options.body); calls.push({url, payload});
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
}
function snapshot(s) {
  return Object.fromEntries(Array.from({length:s.storage.length},(_,i) => {
    const key=s.storage.key(i); return [key,JSON.parse(s.storage.getItem(key))];
  }));
}

test('lost save reply restores its real receipt after the answered position leaves the queue', async () => {
  const f=fixtures.normal, key=keyFor(f);
  const s=await setup(f.before, {storage:{[key]:draftFor(f,'chosen')}});
  click(s,'lock'); await flush();
  assert.equal(s.calls[0].url,'/api/answer');
  assert.equal(JSON.parse(s.storage.getItem(key)).phase,'submitted');
  const saved=snapshot(s), sent=s.calls[0].payload; s.dom.window.close();
  const t=await setup(f.after,{storage:saved,fetch:async (url,payload) => {
    assert.equal(url,'/api/answer/recover'); assert.deepEqual(payload,sent);
    return ok({status:'saved',result:f.result});
  }});
  assert.equal(t.d.getElementById('feedback').hidden,false);
  assert.match(t.d.getElementById('save-status').textContent,/restored/);
  assert.equal(t.d.activeElement.id,'verdict');
  assert.equal(JSON.parse(t.storage.getItem(key)).phase,'feedback');
  assert.equal(t.calls.length,1);
  click(t,'next');
  assert.equal(t.storage.getItem(key),null);
  assert.equal(t.d.activeElement.id,'counter');
  const positions=JSON.parse(f.after.match(/const POS = (.*?), PIECES = /)[1]);
  choose(t,positions[0].legal[0]);
  assert.equal(JSON.parse(t.storage.getItem(key)).position,1);
  t.dom.window.close();
});

test('successful feedback stays recoverable until Next, including the final completed position', async () => {
  const f=fixtures.final,key=keyFor(f);
  const s=await setup(f.before,{storage:{[key]:draftFor(f,'chosen')},fetch:async () => ok(f.result)});
  click(s,'lock'); await flush();
  const saved=snapshot(s); assert.equal(saved[key].phase,'feedback'); s.dom.window.close();
  assert.match(f.after,/const POS = \[\]/);
  const t=await setup(f.after,{storage:saved,fetch:async url => {
    assert.equal(url,'/api/answer/recover'); return ok({status:'saved',result:f.result});
  }});
  assert.equal(t.d.getElementById('practice-flow').hidden,false);
  assert.equal(t.d.getElementById('practice-empty').hidden,true);
  assert.equal(t.d.getElementById('feedback').hidden,false);
  click(t,'next');
  assert.equal(t.d.getElementById('session-title').textContent,'Group complete');
  assert.equal(t.d.getElementById('session-score').textContent,'1 / 1');
  assert.match(t.d.getElementById('group-progress').textContent,/36 of 36 positions tried, 36 engine moves found/);
  assert.equal(t.d.getElementById('next-group').hidden,false);
  assert.equal(t.storage.getItem(key),null); assert.equal(t.calls.length,1);
  t.dom.window.close();
});

test('a missing receipt offers an explicit retry with unchanged identity, move and elapsed time', async () => {
  const f=fixtures.normal,key=keyFor(f);
  const s=await setup(f.before,{storage:{[key]:draftFor(f)},fetch:async url => {
    return url.endsWith('/recover') ? ok({status:'missing'}) : ok(f.result);
  }});
  assert.equal(s.calls.length,1); assert.equal(s.d.getElementById('lock').textContent,'Retry saving');
  assert.equal(s.d.getElementById('undo').disabled,true);
  click(s,'lock'); click(s,'lock'); await flush();
  assert.equal(s.calls.length,2);
  assert.deepEqual(s.calls[0].payload,s.calls[1].payload);
  assert.equal(s.calls[1].payload.seconds,17);
  assert.equal(s.d.getElementById('feedback').hidden,false);
  s.dom.window.close();
});

test('offline recovery preserves the draft and retries reading without posting a new answer', async () => {
  const f=fixtures.normal,key=keyFor(f),draft=draftFor(f);
  const s=await setup(f.after,{storage:{[key]:draft}});
  assert.equal(s.d.getElementById('lock').textContent,'Retry restoring');
  assert.deepEqual(JSON.parse(s.storage.getItem(key)),draft);
  click(s,'lock'); await flush();
  assert.deepEqual(s.calls.map(call=>call.url),['/api/answer/recover','/api/answer/recover']);
  assert.deepEqual(s.calls[0].payload,s.calls[1].payload);
  assert.equal(s.d.getElementById('feedback').hidden,true);
  s.dom.window.close();
});

test('reloaded restart and missed queues advance past earlier visited entries', async () => {
  for (const [name,mode,nextIdx] of [['restart','restart',21],['missed','missed',5]]) {
    const f=fixtures[name],key=keyFor(f,mode);
    const s=await setup(f.after,{storage:{[key]:draftFor(f,'submitted',mode)},
      fetch:async () => ok({status:'saved',result:f.result})});
    click(s,'next');
    const all=JSON.parse(f.before.match(/const POS = (.*?), PIECES = /)[1]);
    choose(s,all.find(p=>p.idx===nextIdx).legal[0]);
    assert.equal(JSON.parse(s.storage.getItem(key)).position,nextIdx);
    s.dom.window.close();
  }
});

test('invalid, stale, illegal and other-owner drafts never recover or reveal feedback', async () => {
  const f=fixtures.normal,key=keyFor(f),original=draftFor(f);
  for (const draft of [{...original,owner:'someone-else'},{...original,fen:'stale'},
    {...original,picked:'a1a8'},{...original,requestId:'bad'}, {...original,seconds:-1},
    {...original,phase:'unknown'},{...original,version:1}]) {
    const s=await setup(f.before,{storage:{[key]:draft}});
    assert.equal(s.calls.length,0); assert.equal(s.storage.getItem(key),null);
    assert.equal(s.d.getElementById('lock').disabled,true);
    assert.equal(s.d.getElementById('feedback').hidden,true);
    s.dom.window.close();
  }
  const s=await setup(f.before,{storage:{[`mu_pending_drill_v2_someone-else_0_continue`]:original}});
  assert.equal(s.calls.length,0); assert.equal(s.d.getElementById('lock').disabled,true);
  s.dom.window.close();
});

test('storage failure still allows a live save and clearly limits reload recovery', async () => {
  const f=fixtures.normal;
  const s=await setup(f.before,{storageFails:true,fetch:async () => ok(f.result)});
  choose(s,f.payload.picked); click(s,'lock'); await flush();
  assert.equal(s.calls.length,1); assert.equal(s.d.getElementById('feedback').hidden,false);
  assert.match(s.d.getElementById('save-status').textContent,/Answer saved.*could not keep your place/);
  click(s,'next'); assert.equal(s.d.getElementById('feedback').hidden,true);
  s.dom.window.close();
});

test('a mismatched saved response remains unacknowledged and can be restored again', async () => {
  const f=fixtures.normal,key=keyFor(f);
  const s=await setup(f.after,{storage:{[key]:draftFor(f)},fetch:async () => ok({status:'saved',result:fixtures.final.result})});
  assert.equal(s.d.getElementById('feedback').hidden,true);
  assert.equal(s.d.getElementById('lock').textContent,'Retry restoring');
  assert.equal(JSON.parse(s.storage.getItem(key)).phase,'submitted');
  s.dom.window.close();
});
