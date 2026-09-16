const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const csstree=require('css-tree');
const root=path.resolve(__dirname,'../../web');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
const ui=JSON.parse(fs.readFileSync(path.join(root,'ui-config.json'),'utf8'));
const clone=x=>JSON.parse(JSON.stringify(x));
const dom=new JSDOM(html,{url:'https://blinq.test/',runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window,d=w.document;
const errors=[];
w.addEventListener('error',e=>errors.push(e.error));
let width=390,columns=1,fail=false,feedCalls=0,resolveFeed;
const media=[];
w.matchMedia=query=>{const m={media:query,get matches(){return width<=1023},addEventListener:(name,fn)=>media.push(fn)};return m;};
w.scrollTo=()=>{};
w.HTMLElement.prototype.getClientRects=function(){return this.hidden?[]:[{}];};
w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
w.HTMLDialogElement.prototype.close=function(){this.open=false;};
w.getComputedStyle=()=>({getPropertyValue:name=>name==='--cards-per-panel'?String(columns):''});
const intervals=[];
w.setInterval=(fn,ms)=>{intervals.push({fn,ms});return intervals.length;};
w.fetch=async url=>({ok:true,json:async()=>url==='/ui-config.json'?clone(ui):{}});
w.BlinqAuth={bannerEvent:async()=>{},clear:()=>{},signOut:async()=>{},feed:async()=>{feedCalls++;if(resolveFeed)return new Promise(r=>resolveFeed=r);if(fail)throw Error('offline fixture');return clone(fixture);}};
w.eval(fs.readFileSync(path.join(root,'responsive.js'),'utf8'));
// Expose lexical functions only in this test process. Production code stays private.
w.eval(app.replace('  boot();',`  window.testApp={state,setupEvents,setupLiveRefresh,renderAllUiContent,renderPredictions,renderMarketSections,renderDashboardComposition,setRoute,loadFeed,auth,buildDemoMatch,buildDemoProjection,signOutCurrentSession};`));
const a=w.testApp;
const fixture={generated_at:new Date().toISOString(),account:{name:'Test member',plan:'elite',status:'active'},upcoming:[],results:[],model:{version:'QA'},prime_picks:Array.from({length:5},(_,i)=>a.buildDemoMatch(i)),top_daily_picks:Array.from({length:6},(_,i)=>a.buildDemoMatch(i,'top_daily')),value_picks:[a.buildDemoMatch(0,'value')],ace_picks:[a.buildDemoProjection(0)]};
function count(selector){return d.querySelectorAll(selector).length;}
function click(selector){const el=d.querySelector(selector);assert(el,selector);el.click();}
async function flush(){await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));}
(async()=>{
  a.state.ui=clone(ui);a.state.uiSource=clone(ui);a.state.feed=clone(fixture);
  a.setupEvents();w.BlinqUI.init();a.setupLiveRefresh();
  await a.loadFeed(false);
  assert.equal(d.getElementById('appShell').hidden,false);
  assert.match(d.getElementById('syncStatus').textContent,/Auto-refresh on/);
  assert.equal(count('#predictionsView .promo-banner'),3);
  assert.equal(count('#predictionGrid .prediction-card'),1);
  assert.equal(count('#topDailyGrid .prediction-card'),1);
  const first=d.querySelector('#predictionGrid .player-name').textContent;
  click('#nextPick');assert.notEqual(d.querySelector('#predictionGrid .player-name').textContent,first);
  assert.equal(d.querySelector('#pickCarouselShell .page-position').textContent,'2 / 5');
  click('#prevPick');assert.equal(d.querySelector('#predictionGrid .player-name').textContent,first);
  // Width transitions use the shared CSS variable, without dropping the final pick.
  for(const viewport of [320,375,390,430,640,768,820,1024,1199,1200,1440,1560,1920,2560]){
    width=viewport;columns=viewport<640?1:viewport<1200?2:viewport<1560?1:2;
    a.state.page=0;a.renderPredictions();a.renderMarketSections();
    assert.equal(count('#predictionGrid .prediction-card'),columns,`cards at ${width}`);
    for(let i=0;i<10;i++)click('#nextPick');
    assert.equal(count('#predictionGrid .prediction-card'),1);
    assert.equal(d.getElementById('nextPick').disabled,true);
    assert.equal(count('#valueGrid .prediction-card'),1);
  }
  width=390;columns=1;
  click('#menuToggle');assert.equal(d.getElementById('mainContent').inert,true);assert.equal(d.getElementById('menuToggle').getAttribute('aria-expanded'),'true');
  d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert.equal(d.getElementById('mainContent').inert,false);
  click('#menuToggle');click('#mainNavigation [data-route="prime"]');
  assert.equal(d.body.classList.contains('nav-open'),false);
  assert.equal(d.getElementById('pageTitle').textContent,'Prime Picks');
  assert.equal(count('.picks-table tbody tr'),5);
  assert.equal(count('.picks-table tbody td:not([data-label])'),0);
  assert.equal(count('.selection-details'),1);
  assert.equal(d.querySelector('.selection-details').open,false);
  click('.mobile-tabs [data-route="results"]');assert.match(d.getElementById('routePanel').textContent,/No settled/);
  click('.mobile-tabs [data-route="account"]');assert(count('.membership-card')>=4);
  click('.mobile-tabs [data-route="predictions"]');
  a.state.feed.account.plan='rookie';a.state.ui.dashboard.sections.prime.plans.rookie.visible_picks=0;a.renderPredictions();
  assert.equal(count('#predictionGrid .player-name'),0,'locked cards do not contain player data');
  assert.equal(count('#predictionGrid [data-upgrade-plan]'),1);
  a.setRoute('admin');assert.equal(a.state.route,'predictions','non-admin route guarded');
  a.state.ui=clone(ui);a.state.feed=clone(fixture);
  for(const route of ['prime','top_daily','value','ace','sg','doubles','results','account','how_blinq_works','methodology','model_data','faq','responsible_use'])a.setRoute(route);
  a.setRoute('predictions');
  fail=true;await assert.rejects(a.loadFeed(false));assert.equal(d.getElementById('appShell').hidden,false);assert.match(d.getElementById('syncStatus').textContent,/failed/);
  w.dispatchEvent(new w.Event('offline'));assert.match(d.getElementById('syncStatus').textContent,/offline/);
  fail=false;w.dispatchEvent(new w.Event('online'));await flush();assert.match(d.getElementById('syncStatus').textContent,/Auto-refresh/);
  assert(intervals.some(x=>x.ms===300000),'five-minute refresh installed');
  a.state.feed={...clone(fixture),prime_picks:[],top_daily_picks:[],value_picks:[],ace_picks:[]};a.setRoute('predictions');assert.match(d.getElementById('predictionGrid').textContent,/No Prime Picks/);
  a.state.feed=clone(fixture);a.state.feed.account.is_admin=true;a.setRoute('admin');assert(count('.admin-console')>0);
  // A pending response must never reopen the dashboard after logout.
  resolveFeed=true;const pending=a.loadFeed(false);await flush();
  const finishPending=resolveFeed;await a.signOutCurrentSession();finishPending(clone(fixture));await pending;
  assert.equal(d.getElementById('appShell').hidden,true);
  assert.equal(d.getElementById('authDialog').open,true);
  // No lost named elements or invalid local entry-point references.
  const ids=[...d.querySelectorAll('[id]')].map(x=>x.id);assert.equal(ids.length,new Set(ids).size);
  for(const node of d.querySelectorAll('script[src],link[href]')){const ref=node.getAttribute('src')||node.getAttribute('href');if(ref.startsWith('/'))assert(fs.existsSync(path.join(root,ref.split('?')[0])),ref);}
  for(const name of ['styles.css','responsive.css'])csstree.parse(fs.readFileSync(path.join(root,name),'utf8'));
  assert.equal(errors.length,0,errors.map(String).join('\n'));
  console.log('PASS: 14 viewport pagination cases; navigation and focus; all public routes; tables; empty/locked/admin states; 3 ads; failure and online recovery; refresh scheduler; JS/CSS/assets.');
  dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1;});
