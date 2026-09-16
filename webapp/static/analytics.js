// First-party page counts. The server decides what each signed page token means.
// Never read the URL, referrer, user agent, account details, or browser storage.
const contextElement = document.getElementById('analytics-context');

function readContext() {
  try {
    const value = JSON.parse(contextElement?.textContent || 'null');
    if (!value || typeof value.page_token !== 'string' || !value.page_token
        || !['unset', 'yes', 'no'].includes(value.consent)
        || typeof value.excluded !== 'boolean') return null;
    return value;
  } catch {
    return null;
  }
}

function privacySignalEnabled() {
  const signals = [navigator.doNotTrack, navigator.msDoNotTrack, window.doNotTrack];
  return navigator.globalPrivacyControl === true
    || signals.some(value => ['1', 'yes'].includes(String(value).toLowerCase()));
}

function eventId() {
  if (typeof globalThis.crypto?.randomUUID === 'function') return crypto.randomUUID();
  if (typeof globalThis.crypto?.getRandomValues !== 'function') return null;
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function startAnalytics(context) {
  const blockedBySignal = privacySignalEnabled();
  const preferenceForms = [...document.querySelectorAll('form[data-analytics-preference]')];
  const state = document.getElementById('analytics-preference-state');
  const feedback = document.getElementById('analytics-preference-feedback');
  const signalNote = document.getElementById('analytics-signal-note');
  let banner = null;
  let queue = Promise.resolve();
  let saving = false;

  // Serialize requests: the preference uses the same first-party session as the page.
  function post(endpoint, payload) {
    const request = queue.then(async () => {
      const abort = new AbortController();
      const timeout = setTimeout(() => abort.abort(), 5000);
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          credentials: 'same-origin',
          referrerPolicy: 'no-referrer',
          keepalive: true,
          signal: abort.signal,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        return response.ok ? response : null;
      } catch {
        return false;
      } finally {
        clearTimeout(timeout);
      }
    });
    queue = request.then(() => undefined, () => undefined);
    return request;
  }

  function refreshControls() {
    if (state) {
      state.textContent = context.excluded
        ? 'This browser is excluded from analytics.'
        : context.consent === 'yes' && !blockedBySignal
          ? 'Visit history is enabled in this browser.'
          : 'Visit history is disabled. Pages are counted anonymously.';
    }
    if (signalNote) signalNote.hidden = !blockedBySignal;
    for (const form of preferenceForms) {
      const choice = form.elements.namedItem('choice')?.value;
      const button = form.querySelector('button[type="submit"]');
      if (!button) continue;
      button.disabled = saving
        || (choice === 'yes' && (blockedBySignal || (!context.excluded && context.consent === 'yes')))
        || (choice === 'no' && context.consent === 'no')
        || (choice === 'exclude' && context.excluded)
        || (choice === 'include' && !context.excluded);
    }
  }

  async function savePreference(choice, source) {
    if (saving || !['yes', 'no', 'exclude', 'include'].includes(choice)
        || (choice === 'yes' && blockedBySignal)) return;
    saving = true;
    refreshControls();
    const buttons = banner ? [...banner.querySelectorAll('button')] : [];
    for (const button of buttons) button.disabled = true;
    const notice = source === 'banner' ? banner.querySelector('[role="status"]') : feedback;
    if (notice) notice.textContent = 'Saving your preference…';
    const saved = await post('/api/analytics/preference', { choice, page_token: context.page_token });
    if (!saved) {
      saving = false;
      if (notice) notice.textContent = 'Your preference could not be saved. Please try again.';
      for (const button of buttons) button.disabled = false;
      refreshControls();
      return;
    }
    if (choice === 'yes') {
      context.consent = 'yes';
      context.excluded = false;
    } else if (choice === 'exclude') {
      context.consent = 'no';
      context.excluded = true;
    } else if (choice === 'include') {
      context.consent = 'no';
      context.excluded = false;
    } else {
      context.consent = 'no';
    }
    // Use effective server state when supplied (the owner's browser, for example,
    // remains excluded even if a preference button is pressed).
    try {
      const effective = await saved.json();
      if (['yes', 'no'].includes(effective?.consent)
          && typeof effective.excluded === 'boolean') {
        context.consent = effective.consent;
        context.excluded = effective.excluded;
      }
    } catch {
      // A successful preference response need not include a body.
    }
    saving = false;
    const confirmation = context.excluded
      ? 'This browser is excluded from analytics from now on.'
      : choice === 'yes'
      ? 'Future activity can now be linked. This page’s anonymous visit stays anonymous.'
        : choice === 'include'
          ? 'Future activity will be counted anonymously. Visit history remains disabled.'
          : 'Visit history is disabled. Pages will still be counted anonymously.';
    if (notice) notice.textContent = confirmation;
    if (banner) {
      banner.querySelector('.analytics-consent-copy').hidden = true;
      banner.querySelector('.analytics-consent-actions').hidden = true;
      if (source !== 'banner') banner.hidden = true;
    }
    refreshControls();
  }

  for (const form of preferenceForms) {
    form.addEventListener('submit', event => {
      event.preventDefault();
      void savePreference(form.elements.namedItem('choice')?.value, 'privacy');
    });
  }
  refreshControls();

  if (context.excluded) return;

  if (blockedBySignal) {
    // A browser signal always overrides an earlier opt-in.
    context.consent = 'no';
    void post('/api/analytics/preference', { choice: 'no', page_token: context.page_token });
    refreshControls();
  }

  const id = eventId();
  if (id) {
    void post('/api/analytics/page', {
      page_token: context.page_token,
      event_id: id,
      visitor_consent: context.consent === 'yes' && !blockedBySignal,
    });
  }

  // The initial page is counted once. An opt-in can link future learning actions,
  // but never upgrades this page's already anonymous event.
  if (context.consent !== 'unset' || blockedBySignal || context.kind === 'privacy') return;
  banner = document.createElement('aside');
  banner.id = 'analytics-consent';
  banner.className = 'analytics-consent';
  banner.setAttribute('aria-label', 'Visit history preference');
  banner.innerHTML = `
    <div class="analytics-consent-copy">
      <p><strong>Allow visit history?</strong> Help improve the site by linking the pages and exercises you use. No names are collected for guests.</p>
    </div>
    <div class="analytics-consent-actions row">
      <button type="button" class="btn" data-choice="yes">Allow</button>
      <button type="button" class="btn" data-choice="no">No thanks</button>
      <a href="/privacy">Privacy and controls</a>
    </div>
    <p class="analytics-consent-status" role="status" aria-live="polite"></p>`;
  for (const button of banner.querySelectorAll('button')) {
    button.addEventListener('click', () => { void savePreference(button.dataset.choice, 'banner'); });
  }
  const masthead = document.querySelector('.masthead');
  if (masthead) masthead.insertAdjacentElement('afterend', banner);
  else (document.querySelector('main') || document.body).prepend(banner);
}

const context = readContext();
if (context && contextElement.dataset.analyticsInitialized !== 'true') {
  contextElement.dataset.analyticsInitialized = 'true';
  startAnalytics(context);
}
