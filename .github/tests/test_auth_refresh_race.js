'use strict';

const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

function storage() {
  const values = new Map();
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  };
}

function response(status, payload) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

function makeContext(localStorage, fetchImpl) {
  const context = {
    console,
    localStorage,
    sessionStorage: storage(),
    location: {origin: 'https://blinq.test', pathname: '/follow-the-data/', hash: ''},
    history: {replaceState() {}},
    URLSearchParams,
    AbortSignal: {timeout: () => undefined},
    Math,
    Date,
    fetch: fetchImpl,
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('web/auth.js', 'utf8'), context, {filename: 'web/auth.js'});
  return context;
}

(async () => {
  let resolveRefresh;
  const sharedLocalStorage = storage();

  const commonFetch = async (url) => {
    if (url === '/api/v1/auth/config') {
      return response(200, {
        enabled: true,
        provider: 'firebase',
        project_id: 'blinq-182',
        auth_domain: 'blinq-182.firebaseapp.com',
      });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  };

  const tabA = makeContext(sharedLocalStorage, async (url) => {
    if (String(url).includes('securetoken.googleapis.com/v1/token')) {
      return new Promise(resolve => { resolveRefresh = resolve; });
    }
    return commonFetch(url);
  });
  const tabB = makeContext(sharedLocalStorage, commonFetch);

  await tabA.BlinqAuth.init();
  await tabB.BlinqAuth.init();
  sharedLocalStorage.setItem('blinq_v4_session', JSON.stringify({
    provider: 'firebase',
    access_token: 'old-access',
    refresh_token: 'old-refresh',
    expires_at: 1,
  }));

  const pendingRestore = tabA.BlinqAuth.restore();
  await Promise.resolve();
  assert.strictEqual(typeof resolveRefresh, 'function');

  // Logout in a different tab must invalidate the already-running refresh in A.
  await tabB.BlinqAuth.signOut();
  resolveRefresh(response(200, {
    id_token: 'refreshed-access',
    refresh_token: 'refreshed-refresh',
    expires_in: '3600',
  }));

  assert.strictEqual(await pendingRestore, null);
  assert.strictEqual(sharedLocalStorage.getItem('blinq_v4_session'), null);
  console.log('auth cross-tab refresh/logout race: PASS');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
