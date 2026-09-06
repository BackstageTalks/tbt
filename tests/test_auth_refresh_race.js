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
        supabase_url: 'https://supabase.test',
        anon_key: 'anon',
      });
    }
    if (String(url).includes('/logout')) return response(200, {});
    throw new Error(`Unexpected fetch: ${url}`);
  };

  const tabA = makeContext(sharedLocalStorage, async (url) => {
    if (String(url).includes('/token?grant_type=refresh_token')) {
      return new Promise(resolve => { resolveRefresh = resolve; });
    }
    return commonFetch(url);
  });
  const tabB = makeContext(sharedLocalStorage, commonFetch);

  await tabA.BlinqAuth.init();
  await tabB.BlinqAuth.init();
  sharedLocalStorage.setItem('blinq_v3_session', JSON.stringify({
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
    access_token: 'refreshed-access',
    refresh_token: 'refreshed-refresh',
    expires_in: 3600,
  }));

  assert.strictEqual(await pendingRestore, null);
  assert.strictEqual(sharedLocalStorage.getItem('blinq_v3_session'), null);
  console.log('auth cross-tab refresh/logout race: PASS');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
