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
import json, sys
from urllib.parse import parse_qs, urlparse
sys.path.insert(0, ${JSON.stringify(path.join(root, 'tests'))})
from test_app import site
explained = next(key for key, note in site.PRACTICE_NOTES.items() if note.get('comparison'))
other_note = next(key for key, note in site.PRACTICE_NOTES.items() if not note.get('comparison'))
plain = next(key for key in site.TEST_DATA['items'] if key not in site.PRACTICE_NOTES)
keys = [explained, other_note, plain]
keys += [key for key in site.TEST_DATA['items'] if key not in keys][:9]
fixtures = []
for perfect in (False, True):
    client = site.app.test_client()
    fresh = client.get('/test?new=1')
    original = parse_qs(urlparse(fresh.location).query)['attempt'][0]
    payload = site.read_test(original)
    payload['items'] = keys
    token = site.test_signer().dumps(payload)
    url = '/test?attempt=' + token
    page = client.get(url)
    assert page.status_code == 200
    picks = []
    for index, key in enumerate(keys):
        cid, idx = map(int, key.split(':'))
        position = site.BY_ID[cid]['drill'][idx]
        move = position['best']
        if not perfect and index in (0, 2):
            move = next(move.uci() for move in site.chess.Board(position['fen']).legal_moves
                        if move.uci() != position['best'])
        picks.append(move)
    result = client.post('/api/blindspot', json={'attempt': token, 'picks': picks})
    assert result.status_code == 200
    fixtures.append({'page':page.get_data(as_text=True), 'url':url,
                     'token':token, 'key':'mu_test_' + payload['id'],
                     'picks':picks, 'keys':keys, 'result':result.json})
print(json.dumps(fixtures))
`;
const fixtures = JSON.parse(execFileSync(process.env.TEST_PYTHON || 'python3', ['-c', fixtureCode],
  {encoding: 'utf8', maxBuffer: 10 * 1024 * 1024}));
const flush = () => new Promise(resolve => setImmediate(resolve));

async function setup(fixture, saved) {
  const dom = new JSDOM(fixture.page, {
    url: 'https://test-review.invalid' + fixture.url,
    runScripts: 'outside-only', pretendToBeVisual: true,
  });
  const w = dom.window;
  w.HTMLElement.prototype.scrollIntoView = function() {};
  if (saved) w.localStorage.setItem(fixture.key, JSON.stringify(saved));
  const submissions = [];
  w.fetch = async (url, init) => {
    assert.equal(url, '/api/blindspot');
    submissions.push(JSON.parse(init.body));
    return {ok: true, json: async () => fixture.result};
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
  return {dom, w, document:w.document, submissions};
}

function open(s, detail) {
  detail.open = true;
  detail.dispatchEvent(new s.w.Event('toggle'));
}

test('test review stays concealed until completion and leads with actual answers', async () => {
  const fixture = fixtures[0];
  const unanswered = await setup(fixture);
  assert.equal(unanswered.document.getElementById('result').hidden, true);
  assert.equal(unanswered.document.querySelector('.study-explanation'), null);
  assert.equal(unanswered.submissions.length, 0);
  unanswered.dom.window.close();

  const s = await setup(fixture, {picks: fixture.picks, result:null});
  await flush();
  assert.equal(s.submissions.length, 1);
  assert.deepEqual(s.submissions[0], {attempt:fixture.token, picks:fixture.picks});
  assert.equal(s.document.getElementById('test-score').textContent, '10 / 12');
  assert.equal(s.document.getElementById('verdictline').textContent, 'You found 10 of 12 engine moves.');
  assert.match(s.document.getElementById('review-guidance').textContent, /2 positions to revisit/);
  assert.equal(s.document.getElementById('rating-comparison').open, false);
  assert.ok(s.document.getElementById('reveal').compareDocumentPosition(
    s.document.getElementById('rating-comparison')) & s.w.Node.DOCUMENT_POSITION_FOLLOWING);
  assert.equal(s.document.activeElement.id, 'result-heading');
  s.dom.window.close();
});

test('test explanations retain legal saved comparisons and group links, with a plain-line fallback', async () => {
  const fixture = fixtures[0];
  const s = await setup(fixture, {picks:fixture.picks, result:fixture.result});
  assert.equal(s.submissions.length, 0, 'viewing a saved result must not create another submission');
  const reviews = [...s.document.querySelectorAll('.position-review')];
  assert.equal(reviews.length, 12);
  assert.equal(reviews.filter(detail => !detail.hidden).length, 2);
  assert.equal(s.document.getElementById('review-missed').getAttribute('aria-pressed'), 'true');

  open(s, reviews[0]);
  const rich = fixture.result.reveal[0];
  assert.ok(reviews[0].querySelector('.study-explanation').textContent.includes(rich.line.note.purpose));
  const choice = reviews[0].querySelector('select');
  assert.equal(choice.options.length, 2);
  choice.value = '1'; choice.dispatchEvent(new s.w.Event('change'));
  assert.match(reviews[0].querySelector('.replay-status').textContent, /Comparison line/);
  assert.ok(reviews[0].querySelector('.replay-status').textContent.includes(rich.line.comparison.san));
  assert.match(reviews[0].querySelector('.test-review-context').textContent, new RegExp(rich.picked_san.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));

  open(s, reviews[2]);
  assert.equal(reviews[2].querySelector('.study-explanation'), null);
  assert.ok(reviews[2].querySelector('.replay-controls'));
  assert.equal(reviews[2].querySelector('select'), null);

  s.document.getElementById('review-all').click();
  assert.ok(reviews.every(detail => !detail.hidden));
  open(s, reviews[1]);
  assert.ok(reviews[1].querySelector('.study-explanation'));
  assert.equal(reviews[1].querySelector('select'), null);
  for (const [index, detail] of reviews.entries()) {
    const cid = fixture.keys[index].split(':')[0];
    assert.equal(detail.querySelector('a').getAttribute('href'), '/pattern/' + cid);
  }
  s.document.getElementById('review-missed').click();
  assert.equal(reviews.filter(detail => !detail.hidden).length, 2);
  assert.equal(s.submissions.length, 0);
  s.dom.window.close();
});

test('perfect test results keep all positions accessible and copied results avoid rating claims', async () => {
  const fixture = fixtures[1];
  const s = await setup(fixture, {picks:fixture.picks, result:fixture.result});
  assert.equal(s.document.getElementById('review-missed').disabled, true);
  assert.equal(s.document.getElementById('review-all').getAttribute('aria-pressed'), 'true');
  assert.ok([...s.document.querySelectorAll('.position-review')].every(detail => !detail.hidden));
  assert.match(s.document.getElementById('review-guidance').textContent, /every engine move/);
  s.document.getElementById('sharebtn').click(); await flush();
  const copied = s.document.getElementById('share-status').textContent;
  assert.match(copied, /12\/12/);
  assert.doesNotMatch(copied, /rating|Lichess|closest/i);
  assert.equal(s.submissions.length, 0);
  s.dom.window.close();
});
