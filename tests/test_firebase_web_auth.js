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
  return {ok: status >= 200 && status < 300, status, json: async () => payload};
}

(async () => {
  const calls = [];
  const context = {
    console,
    localStorage: storage(),
    sessionStorage: storage(),
    location: {origin: 'https://blinq.test', pathname: '/follow-the-data/', hash: ''},
    history: {replaceState() {}},
    URLSearchParams,
    AbortSignal: {timeout: () => undefined},
    Math,
    Date,
    fetch: async (url, options = {}) => {
      calls.push({url: String(url), options});
      if (url === '/api/v1/auth/config') {
        return response(200, {
          enabled: true,
          provider: 'firebase',
          project_id: 'blinq-182',
          auth_domain: 'blinq-182.firebaseapp.com',
        });
      }
      if (String(url).includes('identitytoolkit.googleapis.com/v1/accounts:signInWithPassword')) {
        return response(200, {idToken: 'firebase-id-token', refreshToken: 'firebase-refresh', expiresIn: '3600'});
      }
      if (url === '/api/v1/feed') {
        assert.strictEqual(options.headers['X-Blinq-Access-Token'], 'firebase-id-token');
        return response(200, {account: {id: 'u1'}});
      }
      throw new Error(`Unexpected fetch: ${url}`);
    },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('web/auth.js', 'utf8'), context, {filename: 'web/auth.js'});

  await context.BlinqAuth.init();
  await context.BlinqAuth.signIn('member@example.com', 'password123');
  await context.BlinqAuth.feed();

  assert(calls.some(call => call.url.includes('accounts:signInWithPassword')));
  assert(!calls.some(call => call.url.includes('supabase.co')));
  const stored = JSON.parse(context.localStorage.getItem('blinq_v4_session'));
  assert.strictEqual(stored.provider, 'firebase');
  assert.strictEqual(stored.access_token, 'firebase-id-token');
  console.log('firebase web sign-in/feed flow: PASS');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
