'use strict';
// Exercise the actual browser auth.js transport with mocked authenticated HTTP.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function storage() {
  const values = new Map();
  return {
    getItem:key=>values.has(key)?values.get(key):null,
    setItem:(key,value)=>values.set(key,String(value)),
    removeItem:key=>values.delete(key),
  };
}
const valid = (id='user-a')=>({upcoming:[],results:[],account:{id},entitlements:{results:true}});
const response = (status,payload,headers={})=>({
  status,ok:status>=200&&status<300,
  headers:{get:name=>headers[String(name).toLowerCase()]||null},
  json:async()=>payload,
});
function browser(fetchImpl,{trace=false,local=storage()}={}) {
  const context = {
    window:null,document:undefined,console,
    localStorage:local,sessionStorage:storage(),
    location:{origin:'https://blinq.test',search:trace?'?blinq_boot_trace=1':'',pathname:'/'},
    URLSearchParams,AbortController,AbortSignal,
    Date,Math,setTimeout,clearTimeout,
    fetch:fetchImpl,
  };
  context.window=context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('web/auth.js','utf8'),context);
  return {auth:context.BlinqAuth,local};
}
function setSession(local,id='secret-a',epoch='epoch-a') {
  local.setItem('blinq_v4_session_epoch',epoch);
  local.setItem('blinq_v4_session',JSON.stringify({
    access_token:id,refresh_token:'refresh-'+id,expires_at:Date.now()/1000+3600,provider:'firebase',
  }));
}
const isGzip = url=>String(url).includes('blinq_feed_gzip=1');
async function test() {
  { // A complete first gzip response is one request, and has harmless diagnostics.
    let calls=0;
    const {auth,local}=browser(async(url,opts)=>{
      calls++;
      assert(isGzip(url));assert.equal(opts.headers['X-Blinq-Access-Token'],'secret-a');
      assert.equal(opts.headers['X-Blinq-Feed-Encoding'],'gzip');
      return response(200,valid(),{'server-timing':'blinq_json;dur=45.2, blinq_gzip;dur=30.8',
        'content-encoding':'gzip'});
    },{trace:true});
    setSession(local);
    assert.equal((await auth.feed()).account.id,'user-a');
    assert.equal(calls,1);
    const diag=auth.feedDiagnostics();
    assert.equal(diag.attempts.length,1);
    assert.equal(diag.attempts[0].timingHeader,true);
    assert.deepEqual(Array.from(diag.attempts[0].serverTiming,part=>Array.from(part)),[
      ['blinq_json',45],['blinq_gzip',31]]);
    assert.equal(JSON.stringify(diag).includes('secret'),false);
  }
  { // A broken gzip decoder falls back exactly once; never repeats both requests.
    const seen=[];
    const {auth,local}=browser(async (url,opts)=>{
      seen.push(isGzip(url)?'gzip':'plain');
      assert.equal(opts.headers['X-Blinq-Feed-Encoding'],isGzip(url)?'gzip':undefined);
      if(isGzip(url))return { ...response(200,{}),json:async()=>{throw new SyntaxError('bad stream');} };
      return response(200,valid());
    },{trace:true});
    setSession(local);
    await auth.feed();
    assert.deepEqual(seen,['gzip','plain']);
    assert.equal(auth.feedDiagnostics().fallback,'feed_decode_error');
  }
  { // HTTP 503 and network failures retry the SAME encoding, never plain.
    for(const kind of ['http','network']) {
      let calls=0;const seen=[];
      const {auth,local}=browser(async url=>{
        seen.push(isGzip(url)?'gzip':'plain');calls++;
        if(calls===1){
          if(kind==='network')throw new TypeError('offline');
          return response(503,{error:'unavailable'});
        }
        return response(200,valid());
      },{trace:true});
      setSession(local);
      await auth.feed();
      assert.deepEqual(seen,['gzip','gzip']);
      assert.equal(auth.feedDiagnostics().fallback,'transient_retry');
    }
  }
  { // 401/403 never retry, and protected data are not exposed.
    for(const code of [401,403]) {
      let calls=0;
      const {auth,local}=browser(async()=>{calls++;return response(code,{error:'unauthorized'});});
      setSession(local);
      await assert.rejects(auth.feed(),error=>error.status===code);
      assert.equal(calls,1);
    }
  }
  { // Same-session concurrent callers share exactly one flight.
    let resolveRequest;let calls=0;
    const {auth,local}=browser(async()=>{calls++;return new Promise(resolve=>{resolveRequest=resolve;});});
    setSession(local);
    const first=auth.feed(),second=auth.feed();
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(calls,1);
    resolveRequest(response(200,valid()));
    const both=await Promise.all([first,second]);
    assert.equal(both[0].account.id,'user-a');
    assert.equal(both[1].account.id,'user-a');
  }
  { // Logout and account switching invalidate stale flights, even if fetch ignores abort.
    let resolveOld;const requests=[];
    const {auth,local}=browser(async(url,opts)=>{
      requests.push(opts.headers['X-Blinq-Access-Token']);
      if(requests.length===1)return new Promise(resolve=>{resolveOld=resolve;});
      return response(200,valid('user-b'));
    });
    setSession(local);
    const old=auth.feed();
    await new Promise(resolve=>setImmediate(resolve));
    await auth.signOut();
    setSession(local,'secret-b','epoch-b');
    assert.equal((await auth.feed()).account.id,'user-b');
    resolveOld(response(200,valid('user-a')));
    await assert.rejects(old,error=>error.code==='FEED_SESSION_CHANGED');
    assert.deepEqual(requests,['secret-a','secret-b']);
  }
  { // A cross-tab account change is detected even without an abort event.
    let resolveOld,oldSignal;
    const {auth,local}=browser(async(_url,options)=>{
      oldSignal=options.signal;
      return new Promise(resolve=>{resolveOld=resolve;});
    });
    setSession(local);
    const pending=auth.feed();
    await new Promise(resolve=>setImmediate(resolve));
    setSession(local,'secret-b','epoch-b');
    await auth.restore(); // Cross-tab storage event follows this path.
    assert.equal(oldSignal.aborted,true,'stale account request must abort promptly');
    resolveOld(response(200,valid('user-a')));
    await assert.rejects(pending,error=>error.code==='FEED_SESSION_CHANGED');
  }
  console.log('bounded feed retries, diagnostics and session isolation: PASS');
}
test().catch(error=>{console.error(error);process.exitCode=1;});
