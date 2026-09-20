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
function createContext(fetchImpl) {
  const context = {
    console,
    localStorage: storage(),
    sessionStorage: storage(),
    location: {origin: 'https://blinq.test', pathname: '/', hash: ''},
    history: {replaceState() {}},
    URLSearchParams,
    AbortSignal: {timeout: () => undefined},
    setTimeout: fn => { fn(); return 1; },
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
  // 1) A transient auth-config 5xx is retried, and signIn is self-initializing.
  {
    let configCalls = 0;
    let firebaseCalls = 0;
    const context = createContext(async (url) => {
      const target = String(url);
      if (url === '/api/v1/auth/config') {
        configCalls += 1;
        if (configCalls === 1) return response(503, {error: 'temporary_backend_startup'});
        return response(200, {enabled: true, provider: 'firebase', project_id: 'blinq-182', server_ready: true});
      }
      if (target.includes('accounts:signInWithPassword')) {
        firebaseCalls += 1;
        return response(200, {idToken: 'token-a', refreshToken: 'refresh-a', expiresIn: '3600'});
      }
      if (target.includes('accounts:lookup')) return response(200, {users: [{emailVerified: true}]});
      throw new Error(`Unexpected fetch: ${target}`);
    });
    await context.BlinqAuth.signIn('member@example.com', 'password123');
    assert.strictEqual(configCalls, 2, 'transient config failure must retry');
    assert.strictEqual(firebaseCalls, 1, 'sign-in must continue after config retry');
    assert.strictEqual(context.BlinqAuth.status().degraded, undefined);
  }

  // 2) If Azure Functions/config is temporarily unreachable, Firebase client
  // sign-in remains available from the trusted compile-time public config.
  {
    let configCalls = 0;
    let firebaseCalls = 0;
    const context = createContext(async (url) => {
      const target = String(url);
      if (url === '/api/v1/auth/config') {
        configCalls += 1;
        throw new Error('network down');
      }
      if (target.includes('accounts:signInWithPassword')) {
        firebaseCalls += 1;
        return response(200, {idToken: 'token-b', refreshToken: 'refresh-b', expiresIn: '3600'});
      }
      if (target.includes('accounts:lookup')) return response(200, {users: [{emailVerified: true}]});
      throw new Error(`Unexpected fetch: ${target}`);
    });
    await context.BlinqAuth.signIn('member@example.com', 'password123');
    assert.strictEqual(configCalls, 3, 'unreachable config endpoint must use bounded retries');
    assert.strictEqual(firebaseCalls, 1, 'Firebase client login must not be disabled by Azure cold start');
    assert.strictEqual(context.BlinqAuth.status().degraded, true);
    assert.strictEqual(context.BlinqAuth.status().enabled, true);
  }

  // 3) Permanent Firebase server misconfiguration must fail closed and must not
  // fall back to client-only readiness.
  {
    let firebaseCalls = 0;
    const context = createContext(async (url) => {
      const target = String(url);
      if (url === '/api/v1/auth/config') {
        return response(503, {enabled: false, provider: 'firebase', server_ready: false, error: 'firebase_server_config_invalid'});
      }
      if (target.includes('identitytoolkit.googleapis.com')) firebaseCalls += 1;
      throw new Error(`Unexpected fetch: ${target}`);
    });
    let error = null;
    try { await context.BlinqAuth.signIn('member@example.com', 'password123'); }
    catch (exc) { error = exc; }
    assert(error, 'permanent server configuration error must reject sign-in');
    assert.strictEqual(String(error.code).toLowerCase(), 'firebase_server_config_invalid');
    assert.strictEqual(firebaseCalls, 0, 'permanent server configuration error must fail before Firebase client login');
  }

  console.log('auth init resilience r35: PASS');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
