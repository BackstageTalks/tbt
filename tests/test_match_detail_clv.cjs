const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const start=source.indexOf('  function renderMatchMarketTrend(');
const end=source.indexOf('  function renderMotivationPanel(',start);
assert.ok(start>0&&end>start);
const ctx={
  lcopy:(en,sk)=>sk,
  escapeHtml:x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;'),
  contentLocale:()=> 'sk',
};
vm.createContext(ctx);
vm.runInContext(source.slice(start,end),ctx);

const row={
  event_id:'321',scheduled_at:'2026-11-02T15:00:00Z',
  player1:{id:'1',name:'Karolína Muchová'},
  player2:{id:'2',name:'Rebecca Šramková'},
  winner_id:'1',betting:{odds_source:'tennisapi_provider_1'},
  match_winner_market:{
    provider_id:1,bookmaker:'tennisapi_provider_1',
    captured_at:'2026-11-02T14:45:00Z',
    player1_odds:3.00,player2_odds:1.36,
  },
};
const currentOnly=ctx.renderMatchMarketTrend(row);
assert.match(currentOnly,/Overený aktuálny kurz/);
assert.match(currentOnly,/druhý overený snapshot/);
assert.doesNotMatch(currentOnly,/CLV \(proxy\)/);
const history={
  provider:'propline',bookmaker:'Book A',
  verified:true,exact_event_id_used:true,history:[
    {event_id:'321',bookmaker:'Book A',captured_at:'2026-11-02T12:00:00Z',odds1:2.4,odds2:1.6},
    {event_id:'321',bookmaker:'Book A',captured_at:'2026-11-02T14:30:00Z',odds1:2.1,odds2:1.8},
  ],
};
const ready=ctx.renderMatchMarketTrend({...row,market_movement:history});
assert.match(ready,/Pozorované CLV \(proxy\)/);
assert.match(ready,/PropLine · Book A/);
assert.match(ready,/Iný overený zdroj/);
assert.match(ready,/3\.00/);
assert.match(ready,/2\.40 → 2\.10/);
assert.doesNotMatch(ready,/Na vykreslenie CLV trendu potrebujeme/);
const contaminated={
  ...history,history:[history.history[0],{...history.history[1],bookmaker:'Book B'}],
};
const noMixed=ctx.renderMatchMarketTrend({...row,market_movement:contaminated});
assert.match(noMixed,/druhý overený snapshot/);
assert.doesNotMatch(noMixed,/Pozorované CLV \(proxy\)/);
const wrongEvent={
  ...history,history:[history.history[0],{...history.history[1],event_id:'other'}],
};
assert.doesNotMatch(ctx.renderMatchMarketTrend({...row,market_movement:wrongEvent}),/Pozorované CLV \(proxy\)/);
const early={
  ...history,history:[history.history[0],{...history.history[1],captured_at:'2026-11-02T13:00:00Z'}],
};
const earlyHtml=ctx.renderMatchMarketTrend({...row,market_movement:early});
assert.doesNotMatch(earlyHtml,/Pozorované CLV \(proxy\)/);
assert.match(earlyHtml,/PropLine · Book A/);
console.log('TOP/VALUE Detail CLV: current quote, provider separation, exact event, same bookmaker and near-close proxy PASS');
