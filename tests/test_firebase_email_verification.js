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
  let verified = false;
  const context = {
    console,
    localStorage: storage(),
    sessionStorage: storage(),
    location: {origin: 'https://blinq.test', pathname: '/', hash: ''},
    history: {replaceState() {}},
    URLSearchParams,
    AbortSignal: {timeout: () => undefined},
    Math,
    Date,
    fetch: async (url, options = {}) => {
      const target = String(url);
      let body = {};
      try { body = JSON.parse(options.body || '{}'); } catch {}
      calls.push({url: target, options, body});
      if (url === '/api/v1/auth/config') return response(200, {enabled:true,provider:'firebase',project_id:'blinq-182'});
      if (target.includes('accounts:signUp')) return response(200, {idToken:'signup-token',refreshToken:'signup-refresh',expiresIn:'3600'});
      if (target.includes('accounts:update')) return response(200, {idToken:'signup-token'});
      if (target.includes('accounts:sendOobCode')) return response(200, {email:'member@example.com'});
      if (target.includes('accounts:signInWithPassword')) return response(200, {idToken:'login-token',refreshToken:'login-refresh',expiresIn:'3600'});
      if (target.includes('accounts:lookup')) return response(200, {users:[{email:'member@example.com',emailVerified:verified}]});
      throw new Error(`Unexpected fetch: ${target}`);
    },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('web/auth.js', 'utf8'), context, {filename:'web/auth.js'});

  await context.BlinqAuth.init();
  const signup = await context.BlinqAuth.signUp('member@example.com', 'password123', 'Member');
  assert.strictEqual(signup.verification_required, true);
  const verifyMail = calls.find(call => call.url.includes('accounts:sendOobCode') && call.body.requestType === 'VERIFY_EMAIL');
  assert(verifyMail, 'signup must request a Firebase VERIFY_EMAIL mail');
  assert.strictEqual(context.localStorage.getItem('blinq_v4_session'), null, 'signup must not leave an active app session before verification');

  await context.BlinqAuth.signIn('member@example.com','password123');
  let preVerifySession = JSON.parse(context.localStorage.getItem('blinq_v4_session'));
  assert.strictEqual(preVerifySession.access_token, 'login-token', 'Firebase session must be kept so API can enforce verification and resend can work');

  await context.BlinqAuth.resendVerification();
  assert(calls.filter(call => call.url.includes('accounts:sendOobCode') && call.body.requestType === 'VERIFY_EMAIL').length >= 2,
    'resend must request another VERIFY_EMAIL message');

  verified = true;
  await context.BlinqAuth.signIn('member@example.com','password123');
  const stored = JSON.parse(context.localStorage.getItem('blinq_v4_session'));
  assert.strictEqual(stored.access_token, 'login-token');
  console.log('firebase email verification flow: PASS');
})().catch(error => { console.error(error); process.exit(1); });
