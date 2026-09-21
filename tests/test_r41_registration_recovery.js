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
  let profileHealthy = false;
  let verified = false;
  const calls = [];
  const context = {
    console,
    localStorage: storage(),
    sessionStorage: storage(),
    location: {origin:'https://blinq.test', pathname:'/', hash:''},
    history: {replaceState() {}},
    URLSearchParams,
    AbortSignal: {timeout: () => undefined},
    Math,
    Date,
    fetch: async (url, options={}) => {
      const target=String(url);
      let body={}; try { body=JSON.parse(options.body||'{}'); } catch {}
      calls.push({target,body,options});
      if(target==='/api/v1/auth/config') return response(200,{enabled:true,provider:'firebase',project_id:'blinq-182'});
      if(target.includes('accounts:signUp')) return response(200,{idToken:'signup-token',refreshToken:'signup-refresh',expiresIn:'3600'});
      if(target==='/api/v1/auth/profile') return profileHealthy ? response(200,{ok:true}) : response(503,{error:'admin_storage_unavailable'});
      if(target==='/api/v1/auth/email') return response(200,{ok:true,accepted:true});
      if(target.includes('accounts:signInWithPassword')) return response(200,{idToken:'login-token',refreshToken:'login-refresh',expiresIn:'3600'});
      if(target.includes('accounts:lookup')) return response(200,{users:[{email:'member@example.com',emailVerified:verified}]});
      throw new Error(`Unexpected fetch: ${target}`);
    },
  };
  context.window=context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('web/auth.js','utf8'),context,{filename:'web/auth.js'});

  await context.BlinqAuth.init();
  const signup=await context.BlinqAuth.signUp('member@example.com','password123','@member_test',{version:'2026-09-16',locale:'sk'});
  assert.strictEqual(signup.verification_required,true);
  assert.strictEqual(signup.profile_pending,true,'profile failure must not lose the created Firebase identity');
  const saved=JSON.parse(context.localStorage.getItem('blinq_v4_session'));
  assert.strictEqual(saved.access_token,'signup-token','recovery session must survive profile failure');
  const pending=JSON.parse(context.localStorage.getItem('blinq_v4_pending_registration_profile'));
  assert.strictEqual(pending.email,'member@example.com');
  assert.strictEqual(pending.payload.telegram_nick,'@member_test');
  assert(calls.some(c=>c.target==='/api/v1/auth/email'&&c.body.type==='verify'),'verification delivery remains independent');

  profileHealthy=true;
  verified=true;
  const session=await context.BlinqAuth.signIn('member@example.com','password123');
  assert.strictEqual(session.access_token,'login-token');
  assert.strictEqual(context.localStorage.getItem('blinq_v4_pending_registration_profile'),null,'successful retry clears pending profile');
  const profileCalls=calls.filter(c=>c.target==='/api/v1/auth/profile');
  assert(profileCalls.length>=2,'profile write must be retried after the initial failure');
  console.log('r41 registration recovery: PASS');
})().catch(error=>{console.error(error);process.exit(1);});
