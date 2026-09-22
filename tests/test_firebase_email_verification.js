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
  let verificationDeliveryFails = false;
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
      if (url === '/api/v1/auth/profile') return response(200, {telegram_nick:'@member_test'});
      if (url === '/api/v1/auth/email') {
        if (body.type === 'verify' && verificationDeliveryFails) {
          return response(503, {error:'email_delivery_unavailable'});
        }
        return response(200, {ok:true,accepted:true});
      }
      if (target.includes('accounts:signInWithPassword')) return response(200, {idToken:'login-token',refreshToken:'login-refresh',expiresIn:'3600'});
      if (target.includes('accounts:lookup')) return response(200, {users:[{email:'member@example.com',emailVerified:verified}]});
      throw new Error(`Unexpected fetch: ${target}`);
    },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('web/auth.js', 'utf8'), context, {filename:'web/auth.js'});

  await context.BlinqAuth.init();
  const signup = await context.BlinqAuth.signUp('member@example.com', 'password123', '@member_test');
  assert.strictEqual(signup.verification_required, true);
  const profileSave = calls.find(call => call.url === '/api/v1/auth/profile');
  assert(profileSave, 'signup must save the Telegram nickname');
  assert.strictEqual(profileSave.body.telegram_nick, '@member_test');
  const verifyMail = calls.find(call => call.url === '/api/v1/auth/email' && call.body.type === 'verify');
  assert(verifyMail, 'signup must request a BlinQ-branded Firebase verification mail');
  assert.strictEqual(verifyMail.options.headers['X-Blinq-Access-Token'], 'signup-token');
  assert.strictEqual(context.localStorage.getItem('blinq_v4_session'), null, 'signup must not leave an active app session before verification');

  verificationDeliveryFails = true;
  const deliveryFailure = await context.BlinqAuth.signUp('mailfail@example.com', 'password123', '@member_test');
  assert.strictEqual(deliveryFailure.verification_required, true);
  assert.strictEqual(deliveryFailure.email_delivery_failed, true,
    'SMTP failure after Firebase signup must be returned as a recoverable delivery state');
  const recoverySession = JSON.parse(context.localStorage.getItem('blinq_v4_session'));
  assert.strictEqual(recoverySession.access_token, 'signup-token',
    'failed verification delivery must keep the unverified session so Resend can work');
  verificationDeliveryFails = false;

  let verificationError = null;
  try {
    await context.BlinqAuth.signIn('member@example.com','password123');
  } catch (error) {
    verificationError = error;
  }
  assert(verificationError, 'unverified sign-in must produce an explicit error');
  assert.strictEqual(verificationError.code, 'EMAIL_NOT_VERIFIED');
  let preVerifySession = JSON.parse(context.localStorage.getItem('blinq_v4_session'));
  assert.strictEqual(preVerifySession.access_token, 'login-token', 'Firebase session must be kept so resend can work');

  await context.BlinqAuth.resendVerification();
  assert(calls.filter(call => call.url === '/api/v1/auth/email' && call.body.type === 'verify').length >= 2,
    'resend must request another BlinQ verification message');

  verified = true;
  await context.BlinqAuth.signIn('member@example.com','password123');
  const stored = JSON.parse(context.localStorage.getItem('blinq_v4_session'));
  assert.strictEqual(stored.access_token, 'login-token');
  console.log('firebase email verification flow: PASS');
})().catch(error => { console.error(error); process.exit(1); });
