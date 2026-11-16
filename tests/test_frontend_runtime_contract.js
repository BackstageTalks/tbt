'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');

const app = fs.readFileSync('web/app.js','utf8');
const auth = fs.readFileSync('web/auth.js','utf8');
const responsive = fs.readFileSync('web/responsive.js','utf8');
const html = fs.readFileSync('web/index.html','utf8');
const ui = JSON.parse(fs.readFileSync('web/ui-config.json','utf8'));
const release = JSON.parse(fs.readFileSync('web/release.json','utf8'));

function declaredNames(source){
  const out = new Set();
  for (const m of source.matchAll(/\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/g)) out.add(m[1]);
  for (const m of source.matchAll(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\b/g)) out.add(m[1]);
  return out;
}
function bareObjectNames(body){
  return body.split(',').map(v=>v.trim()).filter(Boolean).map(v=>v.split(':',1)[0].trim()).filter(v=>/^[A-Za-z_$][\w$]*$/.test(v));
}

const authObject = auth.match(/window\.BlinqAuth\s*=\s*\{([\s\S]*?)\n\s*\};/);
assert.ok(authObject, 'BlinqAuth export object missing');
const authExports = new Set(bareObjectNames(authObject[1].replace(/\n/g,' ')));
const authDeclared = declaredNames(auth);
for (const name of authExports) assert.ok(authDeclared.has(name), `BlinqAuth exports undefined identifier ${name}`);
for (const m of app.matchAll(/\bBlinqAuth\.([A-Za-z_$][\w$]*)/g)) assert.ok(authExports.has(m[1]), `app.js calls missing BlinqAuth.${m[1]}`);
for (const name of ['adminSaveUiConfig','adminUploadMedia','feed','insights','liveRadar','adminDiagnostics','adminUsers']) assert.ok(authExports.has(name), `critical auth API missing: ${name}`);

const uiObject = responsive.match(/window\.BlinqUI\s*=\s*Object\.freeze\(\{([^}]*)\}\)/);
assert.ok(uiObject, 'BlinqUI export object missing');
const uiExports = new Set(bareObjectNames(uiObject[1]));
for (const m of app.matchAll(/\bBlinqUI\.([A-Za-z_$][\w$]*)/g)) assert.ok(uiExports.has(m[1]), `app.js calls missing BlinqUI.${m[1]}`);

const patch = html.match(/<meta name="blinq-web-patch" content="736-r(\d+)"/);
assert.ok(patch, 'frontend patch marker missing');
const p = patch[1];
assert.equal(release.patch, `736-r${p}`);
assert.equal(ui.ui_patch, `736-r${p}`);
assert.ok(html.includes(`/auth.js?v=${ui.asset_revision}&p=${p}`));
assert.ok(html.includes(`/responsive.js?v=${ui.asset_revision}&p=${p}`));
assert.ok(html.includes(`/app.js?v=${ui.asset_revision}&p=${p}`));
assert.ok(html.includes(`/blinq-app.css?v=${ui.asset_revision}&p=${p}`));

for (const retired of ['SUPPORT STORAGE','VIP_RAIL','VIP_TELEGRAM','FOOTBALL_ACCESS','BTTS_BONUS_PANEL','renderAdminCampaigns','adminPayments','adminAddPayment','adminBannerAnalytics']) {
  assert.equal(app.includes(retired), false, `retired runtime token returned: ${retired}`);
}

// Exercise the actual offer filter, not a duplicate copy of its predicates.
// BlinQ 1.50–1.70 issued Most Aces prices have no external provider ID.
const vm=require('node:vm');
function frontendHelper(name){
  const start=app.indexOf('  function '+name+'(');
  assert.ok(start>=0,'Missing frontend helper '+name);
  const end=app.indexOf('\n  }\n',start);
  assert.ok(end>start,'Unterminated frontend helper '+name);
  return app.slice(start,end+5);
}
const acesContext={};
vm.runInNewContext([
  'authenticLiveProjection','authenticLocalAceProjection',
  'authenticAceWinnerProjection','authenticMarketSectionRow',
  'verifiedFrozenMostAcesLocalOdds',
].map(frontendHelper).join('\n'),acesContext);
const localMostAces={
  event_id:'most-aces-01',market:'most_aces',
  scheduled_at:'2026-11-08T17:00:00+00:00',
  player1:{id:'11',name:'Alpha'},player2:{id:'22',name:'Beta'},
  selection_id:'11',projection_model:'ace-count-projection-v4',
  projection:7.3,opponent_projection:3.1,projection_confidence:0.78,
  price_contract:'player_superiority',price_status:'priced_projection',
  odds:1.59,odds_source:'blinq_statistical',
  price_basis:'blinq_user_most_aces_confidence_band_v1',
  odds_contract_version:'most_aces_local_statistical_v1',
  ace_winner_issued:true,
  provider_id:null,captured_at:null,ou_side:null,market_line:null,
};
const accepts=(row,section='ace')=>acesContext.authenticMarketSectionRow(row,section);
assert.equal(accepts(localMostAces),true,'Issued statistical VIAC ES must appear on offer');
assert.equal(accepts(localMostAces,'sg'),false,'Most Aces cannot leak into Set/Game tab');
assert.equal(accepts({...localMostAces,price_status:'projection_only',odds:null}),true,
  'Old issued ESÁ leader signal must remain visible without betting odds');
for(const [reason,field] of [
  ['not issued',{ace_winner_issued:false}],
  ['ESÁ-only signal masquerading as issued',{ace_winner_source:'issued_aces_signal_only'}],
  ['wrong market',{market:'aces'}],
  ['wrong odds basis',{price_basis:'unknown'}],
  ['wrong price',{odds:1.67}],
  ['missing version',{odds_contract_version:null}],
  ['external ID with local quote',{provider_id:1}],
  ['external timestamp with local quote',{captured_at:'2026-11-08T06:00:00Z'}],
  ['wrong selection',{selection_id:'33'}],
  ['player total substitution',{price_contract:'player_total_ou'}],
  ['injected O/U line',{market_line:4.5}],
  ['insufficient confidence',{projection_confidence:0.59}],
  ['reversed projection',{projection:2}],
]){
  assert.equal(accepts({...localMostAces,...field}),false,'Rejected '+reason);
}

// The live-feed scheduler must behave like a quiet app, not a page reload.
const signatureContext={};
vm.runInNewContext(frontendHelper('feedVisualSignature'),signatureContext);
const signature=signatureContext.feedVisualSignature;
assert.equal(signature({upcoming:[1],__blinq_feed_stage_ms:{fetch:3}}),
  signature({upcoming:[1],__blinq_feed_stage_ms:{fetch:123}}),
  'backend timings must not cause a visual refresh');
assert.equal(signature({upcoming:[1],generated_at:'2026-11-16T20:00:00Z'}),
  signature({upcoming:[1],generated_at:'2026-11-16T20:02:00Z'}),
  'generation timestamps alone must not cause card rerenders');
assert.notEqual(signature({upcoming:[1]}),signature({upcoming:[2]}),
  'a changed prediction must trigger a visual refresh');
const autoCode=app.slice(app.indexOf('  async function loadFeed('),
  app.indexOf('  async function refreshWorkspace('));
assert.ok(autoCode.indexOf('if(skipUnchanged&&lastFeedVisualSignature===feedSignature')>=0,
  'unchanged live feed must bypass the UI rebuild');
assert.ok(app.includes('skipUnchanged:skipUnchanged&&prior===uiVisualSignature()'),
  'unchanged published config must not force a dashboard rebuild');
assert.ok(autoCode.indexOf('if(skipUnchanged&&lastFeedVisualSignature===feedSignature') <
  autoCode.indexOf('cancelResultsPreload();'),
  'unchanged live feed must leave the staged Results loader running');

(async()=>{
  let clock=0;
  const intervals=[],listeners={},calls=[];
  const document={
    hidden:false,activeElement:null,
    querySelector:()=>null,
    addEventListener:(name,callback)=>{listeners['document:'+name]=callback;},
  };
  const nav={onLine:true};
  const context={
    Date:{now:()=>clock}, document,navigator:nav,Promise,console,
    feedLoading:false,state:{route:'predictions',demoMode:false}, 
    $:()=>({hidden:false}),
    window:{addEventListener:(name,callback)=>{listeners['window:'+name]=callback;}},
    setInterval:(callback,ms)=>intervals.push({callback,ms}),
    refreshWorkspace:()=>{calls.push('config+feed');return Promise.resolve();},
    loadFeed:(_show,options)=>{calls.push(options?.skipUnchanged?'silent-feed':'feed');return Promise.resolve();},
    refreshPrivateUpdates:()=>Promise.resolve(),
    renderSystemFooterStatus:()=>{},
    pollAdminModelFactory:()=>Promise.resolve(),
    handleSessionStorageEvent:()=>{},
    setRoute:()=>{},
    location:{hash:'#predictions'},
  };
  vm.runInNewContext(frontendHelper('setupLiveRefresh')+'\nsetupLiveRefresh();',context);
  const timer=intervals.find(x=>x.ms===60000);
  assert.ok(timer,'visible workspace must check for a live update at one-minute scheduler ticks');
  clock=119000;timer.callback();assert.equal(calls.length,0,'no early refresh while the UI settles');
  clock=120000;timer.callback();timer.callback();assert.deepEqual(calls,['silent-feed'],
    'first two-minute sync must be silent and single-flight');
  await Promise.resolve();await Promise.resolve();await Promise.resolve();
  clock=300000;timer.callback();assert.deepEqual(calls,['silent-feed','config+feed'],
    'published UI configuration must still be refreshed every five minutes');
  await Promise.resolve();await Promise.resolve();await Promise.resolve();
  clock=450000;document.hidden=true;timer.callback();assert.equal(calls.length,2,
    'no background polling in a hidden tab');
  document.hidden=false;listeners['document:visibilitychange']();
  assert.equal(calls.length,3,'resume sync on tab visibility');
  await Promise.resolve();await Promise.resolve();await Promise.resolve();
  clock=700000;nav.onLine=false;timer.callback();assert.equal(calls.length,3,'offline must not fetch');
  nav.onLine=true;listeners['window:online']();
  assert.equal(calls.length,4,'reconnection must trigger one catch-up sync');
})().catch(error=>{console.error(error);process.exitCode=1;});

console.log(`frontend runtime contract: PASS (736-r${p})`);
