import { JSDOM } from 'jsdom';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const page = execFileSync(process.env.TEST_PYTHON || 'python3', ['-c',
  'from tests.test_candidate_review import html_fixture; from scripts.candidate_review import review_html; print(review_html(html_fixture(), "a" * 64))'],
  {cwd: root, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024});
function setup() {
  const dom = new JSDOM(page, {runScripts: 'dangerously', url: 'https://offline-review.invalid'});
  return {dom, w: dom.window, d: dom.window.document};
}

test('saved root replay works at both depths, without any network or engine', () => {
  const {dom, w, d} = setup();
  try {
    assert.equal(d.querySelectorAll('.square').length, 64);
    const square = name => [...d.querySelectorAll('.square')].find(node => node.querySelector('.coord').textContent === name);
    assert.equal(square('a1').classList.contains('dark'), true);
    assert.equal(square('a8').classList.contains('light'), true);
    assert.match(d.getElementById('accepted').textContent, /e4/);
    assert.equal(d.getElementById('branch').options.length, 20);
    const start = d.getElementById('board').getAttribute('aria-label');
    d.getElementById('forward').click();
    assert.notEqual(d.getElementById('board').getAttribute('aria-label'), start);
    assert.equal(d.getElementById('forward').disabled, true);
    d.getElementById('start').click();
    assert.equal(d.getElementById('board').getAttribute('aria-label'), start);
    d.getElementById('depth').value = '20';
    d.getElementById('depth').dispatchEvent(new w.Event('change'));
    assert.equal(d.getElementById('branch').options.length, 20);
    assert.match(d.getElementById('score').textContent, /achieved depth 20/);
    assert.equal(d.querySelectorAll('script[src],link[href],img[src]').length, 0);
  } finally { dom.window.close(); }
});

test('review notes persist across navigation and re-import into the same exact packet', () => {
  const {dom, w, d} = setup();
  try {
    d.getElementById('explanation').value = '<script>plain text only</script>';
    d.getElementById('explanation').dispatchEvent(new w.Event('input'));
    d.getElementById('status').value = 'promising';
    d.getElementById('status').dispatchEvent(new w.Event('input'));
    d.getElementById('next').click();
    assert.equal(d.getElementById('explanation').value, '');
    d.getElementById('previous').click();
    assert.equal(d.getElementById('explanation').value, '<script>plain text only</script>');
    assert.match(d.getElementById('progress').textContent, /^1 \/ 2/);
    const exported = JSON.parse(JSON.stringify(w.reviewDesk.exportValue()));
    w.reviewDesk.importReviews(exported);
    assert.equal(d.getElementById('status').value, 'promising');
    assert.equal(Object.hasOwn(exported.items[0], 'trainer_ready'), false);
  } finally { dom.window.close(); }
});

test('invalid imports preserve existing notes and never alter evidence or readiness', () => {
  const {dom, w, d} = setup();
  try {
    d.getElementById('explanation').value = 'Keep this note';
    d.getElementById('explanation').dispatchEvent(new w.Event('input'));
    const original = JSON.parse(JSON.stringify(w.reviewDesk.exportValue()));
    for (const mutate of [v => {v.packet_sha256 = 'bad';}, v => {v.items[0].trainer_ready = true;},
      v => {v.items[1] = v.items[0];}, v => {v.items[0].evidence_sha256 = 'bad';}]) {
      const bad = structuredClone(original); mutate(bad);
      assert.throws(() => w.reviewDesk.importReviews(bad));
      assert.equal(d.getElementById('explanation').value, 'Keep this note');
      assert.equal(JSON.stringify(w.reviewDesk.exportValue()), JSON.stringify(original));
    }
  } finally { dom.window.close(); }
});
