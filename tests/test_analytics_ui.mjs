import { JSDOM } from 'jsdom';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = readFileSync(path.join(root, 'webapp/static/analytics.js'), 'utf8');
const baseContext = { page_token: 'signed-page-token', consent: 'unset', excluded: false,
  path: '/learn', kind: 'learn', concept: null };
const privacyControls = `
  <p id="analytics-preference-state" role="status"></p>
  <p id="analytics-signal-note" hidden>Browser privacy signal</p>
  ${['yes', 'no', 'exclude', 'include'].map(choice => `
    <form method="post" action="/analytics/preference" data-analytics-preference>
      <input type="hidden" name="page_token" value="signed-page-token">
      <input type="hidden" name="choice" value="${choice}">
      <button type="submit">${choice}</button>
    </form>`).join('')}
  <p id="analytics-preference-feedback" role="status"></p>`;

const settle = async () => {
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
};

async function setup({ context = baseContext, rawContext, controls = false, signals = {},
  fetchImpl = async () => ({ ok: true }), fallbackUUID = false, requestTimeoutMs } = {}) {
  const config = rawContext ?? JSON.stringify(context);
  const dom = new JSDOM(`<!doctype html><html><body><div class="sheet"><div class="masthead"></div>
    <main><h1>Learn</h1><input name="email" value="private@example.invalid">
    <input name="password" type="password" value="sensitive-password">
    ${controls ? privacyControls : ''}</main></div>
    ${context === null && rawContext === undefined ? '' : `<script type="application/json" id="analytics-context">${config}</script>`}
    </body></html>`, {
    url: 'https://fixture.invalid/learn?email=private@example.invalid&token=secret#private-hash',
    referrer: 'https://example.invalid/?sensitive=referrer', runScripts: 'outside-only',
  });
  const { window } = dom;
  const { document } = window;
  if (requestTimeoutMs !== undefined) {
    const timeout = window.setTimeout.bind(window);
    window.setTimeout = (callback, delay, ...args) => timeout(callback,
      delay === 5000 ? requestTimeoutMs : delay, ...args);
  }
  for (const [name, value] of Object.entries(signals)) {
    const target = name === 'windowDoNotTrack' ? window : window.navigator;
    Object.defineProperty(target, name === 'windowDoNotTrack' ? 'doNotTrack' : name,
      { configurable: true, value });
  }
  for (const name of ['localStorage', 'sessionStorage']) {
    Object.defineProperty(window, name, { get() { throw new Error('Analytics must not access browser storage'); } });
  }
  if (fallbackUUID) Object.defineProperty(window.crypto, 'randomUUID', { value: undefined });
  const fetches = [];
  window.fetch = async (url, options) => {
    const call = { url, options, body: JSON.parse(options.body) };
    fetches.push(call);
    return fetchImpl(call, fetches.length);
  };
  let evaluation = 0;
  async function run() {
    const module = new vm.SourceTextModule(source,
      { context: dom.getInternalVMContext(), identifier: `analytics-${evaluation++}.js` });
    await module.link(() => { throw new Error('No external analytics modules allowed'); });
    await module.evaluate();
    await settle();
  }
  await run();
  return { window, document, fetches, run, close: () => window.close(),
    banner: () => document.getElementById('analytics-consent'),
    choose: choice => document.querySelector(`[data-choice="${choice}"]`).click(),
    submit: choice => document.querySelector(`input[name="choice"][value="${choice}"]`)
      .form.querySelector('button').click(),
  };
}

test('unset preference sends one anonymous page and asks without capturing URL or form data', async () => {
  const s = await setup();
  assert.equal(s.fetches.length, 1);
  const call = s.fetches[0];
  assert.equal(call.url, '/api/analytics/page');
  assert.deepEqual(Object.keys(call.body).sort(), ['event_id', 'page_token', 'visitor_consent']);
  assert.equal(call.body.page_token, baseContext.page_token);
  assert.equal(call.body.visitor_consent, false);
  assert.match(call.body.event_id, /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i);
  assert.equal(call.options.method, 'POST');
  assert.equal(call.options.credentials, 'same-origin');
  assert.equal(call.options.referrerPolicy, 'no-referrer');
  assert.equal(call.options.keepalive, true);
  assert.doesNotMatch(JSON.stringify(s.fetches), /private@example|secret|private-hash|sensitive-password|sensitive=referrer/);
  assert.ok(s.banner());
  assert.match(s.banner().textContent, /Allow visit history/);
  assert.equal(s.banner().hasAttribute('aria-modal'), false);
  assert.equal(s.document.activeElement, s.document.body);
  await s.run();
  s.window.dispatchEvent(new s.window.Event('pageshow'));
  s.document.dispatchEvent(new s.window.Event('visibilitychange'));
  await settle();
  assert.equal(s.fetches.length, 1);
  assert.equal(s.document.querySelectorAll('#analytics-consent').length, 1);
  s.close();
});

test('Allow saves consent for future pages without identifying or resending this page', async () => {
  const s = await setup();
  s.choose('yes');
  s.choose('yes');
  await settle();
  assert.equal(s.fetches.length, 2);
  assert.equal(s.fetches[1].url, '/api/analytics/preference');
  assert.deepEqual(s.fetches[1].body, { choice: 'yes', page_token: baseContext.page_token });
  assert.equal(s.fetches[0].body.visitor_consent, false);
  assert.match(s.banner().textContent, /Future activity can now be linked/);
  assert.equal(s.banner().querySelector('.analytics-consent-actions').hidden, true);
  await s.run();
  assert.equal(s.fetches.length, 2);
  s.close();
});

test('No thanks saves refusal and leaves the single page anonymous', async () => {
  const s = await setup();
  s.choose('no');
  await settle();
  assert.deepEqual(s.fetches.map(call => call.url), ['/api/analytics/page', '/api/analytics/preference']);
  assert.equal(s.fetches[1].body.choice, 'no');
  assert.equal(s.fetches[0].body.visitor_consent, false);
  assert.match(s.banner().textContent, /Visit history is disabled/);
  s.close();
});

test('saved opt-in links the page, and saved refusal keeps it anonymous without another prompt', async () => {
  for (const consent of ['yes', 'no']) {
    const s = await setup({ context: { ...baseContext, consent } });
    assert.equal(s.fetches.length, 1);
    assert.equal(s.fetches[0].body.visitor_consent, consent === 'yes');
    assert.equal(s.banner(), null);
    s.close();
  }
});

test('GPC and DNT override a saved opt-in before posting an anonymous page', async () => {
  for (const signals of [{ globalPrivacyControl: true }, { doNotTrack: '1' },
    { doNotTrack: 'yes' }, { msDoNotTrack: '1' }, { windowDoNotTrack: '1' }]) {
    const s = await setup({ context: { ...baseContext, consent: 'yes' }, signals });
    assert.equal(s.banner(), null);
    assert.deepEqual(s.fetches.map(call => call.url), ['/api/analytics/preference', '/api/analytics/page']);
    assert.equal(s.fetches[0].body.choice, 'no');
    assert.equal(s.fetches[1].body.visitor_consent, false);
    s.close();
  }
});

test('disabled browser signals leave the consent choice available', async () => {
  const s = await setup({ signals: { globalPrivacyControl: false, doNotTrack: '0' } });
  assert.ok(s.banner());
  assert.equal(s.fetches.length, 1);
  s.close();
});

test('excluded browsers send nothing while privacy controls can include them anonymously', async () => {
  const s = await setup({ context: { ...baseContext, kind: 'privacy', consent: 'no', excluded: true }, controls: true });
  assert.equal(s.fetches.length, 0);
  assert.equal(s.banner(), null);
  s.submit('include');
  await settle();
  assert.equal(s.fetches.length, 1);
  assert.equal(s.fetches[0].url, '/api/analytics/preference');
  assert.equal(s.fetches[0].body.choice, 'include');
  assert.match(s.document.getElementById('analytics-preference-state').textContent, /Pages are counted anonymously/);
  assert.match(s.document.getElementById('analytics-preference-feedback').textContent, /Future activity will be counted anonymously/);
  s.close();
});

test('privacy controls support opt-in, disabling history and exclusion without duplicate pages', async () => {
  const s = await setup({ context: { ...baseContext, kind: 'privacy' }, controls: true });
  assert.equal(s.banner(), null);
  for (const choice of ['yes', 'no', 'exclude']) {
    s.submit(choice);
    await settle();
  }
  assert.equal(s.fetches.filter(call => call.url === '/api/analytics/page').length, 1);
  assert.deepEqual(s.fetches.slice(1).map(call => call.body.choice), ['yes', 'no', 'exclude']);
  assert.match(s.document.getElementById('analytics-preference-state').textContent, /excluded from analytics/);
  s.close();
});

test('privacy controls disclose active browser signals and cannot opt in against them', async () => {
  const s = await setup({ context: { ...baseContext, kind: 'privacy' }, controls: true,
    signals: { globalPrivacyControl: true } });
  assert.equal(s.document.getElementById('analytics-signal-note').hidden, false);
  const form = s.document.querySelector('input[name="choice"][value="yes"]').form;
  assert.equal(form.querySelector('button').disabled, true);
  form.dispatchEvent(new s.window.Event('submit', { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(s.fetches.some(call => call.body.choice === 'yes'), false);
  s.close();
});

test('privacy UI reflects effective server exclusion after a preference is saved', async () => {
  const s = await setup({ context: { ...baseContext, kind: 'privacy', excluded: true }, controls: true,
    fetchImpl: async () => ({ ok: true, json: async () => ({ consent: 'yes', excluded: true }) }) });
  s.submit('yes');
  await settle();
  assert.match(s.document.getElementById('analytics-preference-state').textContent, /excluded from analytics/);
  assert.match(s.document.getElementById('analytics-preference-feedback').textContent, /excluded from analytics/);
  assert.equal(s.fetches.filter(call => call.url === '/api/analytics/page').length, 0);
  s.close();
});

test('blocked page requests do not stop consent controls or trigger retries', async () => {
  const s = await setup({ fetchImpl: async call => {
    if (call.url === '/api/analytics/page') throw new Error('Network blocked');
    return { ok: true };
  } });
  s.choose('no');
  await settle();
  assert.equal(s.fetches.length, 2);
  assert.match(s.banner().textContent, /Visit history is disabled/);
  await s.run();
  assert.equal(s.fetches.length, 2);
  s.close();
});

test('failed preference requests preserve controls and can be retried explicitly', async () => {
  let attempts = 0;
  const s = await setup({ fetchImpl: async call => ({ ok: call.url === '/api/analytics/page' || ++attempts > 1 }) });
  s.choose('yes');
  await settle();
  assert.match(s.banner().textContent, /could not be saved/);
  assert.equal(s.banner().querySelector('[data-choice="yes"]').disabled, false);
  s.choose('yes');
  await settle();
  assert.match(s.banner().textContent, /Future activity can now be linked/);
  assert.equal(s.fetches.filter(call => call.url === '/api/analytics/page').length, 1);
  s.close();
});

test('a stalled page request times out so it cannot indefinitely block a preference', async () => {
  let aborted = false;
  const s = await setup({ requestTimeoutMs: 0, fetchImpl: call => {
    if (call.url !== '/api/analytics/page') return Promise.resolve({ ok: true });
    return new Promise((resolve, reject) => {
      call.options.signal.addEventListener('abort', () => {
        aborted = true;
        reject(new Error('Request timed out'));
      });
    });
  } });
  s.choose('no');
  await new Promise(resolve => setTimeout(resolve, 10));
  await settle();
  assert.equal(aborted, true);
  assert.deepEqual(s.fetches.map(call => call.url), ['/api/analytics/page', '/api/analytics/preference']);
  assert.match(s.banner().textContent, /Visit history is disabled/);
  s.close();
});

test('a rapid opt-in waits for the initial page to avoid session-cookie races', async () => {
  let finishPage;
  const s = await setup({ fetchImpl: call => call.url === '/api/analytics/page'
    ? new Promise(resolve => { finishPage = resolve; }) : Promise.resolve({ ok: true }) });
  s.choose('yes');
  await settle();
  assert.equal(s.fetches.length, 1);
  finishPage({ ok: true });
  await settle();
  assert.deepEqual(s.fetches.map(call => call.url), ['/api/analytics/page', '/api/analytics/preference']);
  assert.equal(s.fetches[0].body.visitor_consent, false);
  s.close();
});

test('missing or invalid configuration quietly skips collection', async () => {
  for (const options of [{ context: null }, { rawContext: '{broken' },
    { context: { ...baseContext, page_token: '' } },
    { context: { ...baseContext, consent: 'invalid' } },
    { context: { ...baseContext, excluded: 'false' } }]) {
    const s = await setup(options);
    assert.equal(s.fetches.length, 0);
    assert.equal(s.banner(), null);
    s.close();
  }
});

test('browsers without randomUUID use an ephemeral UUID without browser storage', async () => {
  const s = await setup({ fallbackUUID: true });
  assert.equal(s.fetches.length, 1);
  assert.match(s.fetches[0].body.event_id, /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i);
  s.close();
});
