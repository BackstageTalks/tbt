'use strict';
const fs=require('node:fs');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const app=fs.readFileSync('web/app.js','utf8');
const css=fs.readFileSync('web/blinq-app.css','utf8');
const html=fs.readFileSync('web/index.html','utf8');
const start=app.indexOf('  const MONTHLY_SECTIONS=[');
const end=app.indexOf('  function renderResults(){',start);
assert.ok(start>=0&&end>start);
const fixtures=[
  {row:{scheduled_at:'2026-11-01T12:00:00+01:00',tour:'ATP',surface:'hard'},publication:{section:'top_daily',market:'match_winner',price_status:'priced',odds:1.7,result:{outcome:'win',staked_units:2,profit_units:0.7}},categories:['top_daily'],allowed:['pro','elite','legend','goat']},
  {row:{scheduled_at:'2026-11-03T12:00:00+01:00',tour:'WTA',surface:'clay'},publication:{section:'value',market:'match_winner',price_status:'priced',odds:1.9,result:{outcome:'loss',staked_units:1,profit_units:-1}},categories:['value'],allowed:['rookie','pro','elite','legend','goat']},
  {row:{scheduled_at:'2026-11-05T12:00:00+01:00',tour:'ATP',surface:'hard'},publication:{section:'top_daily',market:'match_winner',price_status:'priced',odds:2,result:{outcome:'void',staked_units:0,profit_units:0}},categories:['top_daily'],allowed:['elite','legend','goat']}
];
const state={feed:{results:fixtures.map(x=>x.row),member_result_rules:{rookie:{},pro:{},elite:{},legend:{},goat:{}}}};
const sandbox={
 state,
 bratislavaBettingDayKey:x=>typeof x==='number'?'2026-11-07':String(x||'').slice(0,10),
 publicationOutcome:p=>({kind:p?.result?.outcome||'pending'}),
 approvedLocalAceResultOdds:()=>NaN,
 statsHaveExcludedMarkets:()=>false,
 resultPublicationMatchesWindow:()=>true,
 localResultMetrics:()=>({wins:0,losses:0,voids:0,profit:0}),
 escapeHtml:x=>String(x??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),
 filteredResults:f=>fixtures.filter(x=>x.row.scheduled_at.slice(0,10)>=f.dateFrom&&x.row.scheduled_at.slice(0,10)<=f.dateTo&&(!f.tour||f.tour===x.row.tour)&&(!f.surface||f.surface===x.row.surface)),
 settledPublishedEntries:(xs,c,f)=>xs.filter(x=>!f.membership||x.allowed.includes(f.membership))
};
vm.createContext(sandbox);
vm.runInContext(app.slice(start,end)+'\nthis.monthly={monthlyMonthEnd,monthlyPerformanceState,monthlyMetricRows,monthlyMetricSummary,renderMonthlyPerformance};',sandbox);
const t=sandbox.monthly,p=t.monthlyPerformanceState();
p.month='2026-11';
assert.equal(t.monthlyMonthEnd('2026-11','2026-11-07'),7);
assert.equal(t.monthlyMonthEnd('2026-10','2026-11-07'),31);
assert.equal(t.monthlyMonthEnd('2026-12','2026-11-07'),0);
assert.equal(t.monthlyMonthEnd('2024-02','2024-03-01'),29);
const elite=t.monthlyMetricSummary(t.monthlyMetricRows('elite'));
const rookie=t.monthlyMetricSummary(t.monthlyMetricRows('rookie'));
assert.equal(elite.all.length,3);
assert.equal(elite.n,2);
assert.ok(Math.abs(elite.profit+.3)<1e-9,'frozen 1u profit remains unchanged despite legacy stake');
assert.equal(elite.voids,1);
assert.equal(rookie.all.length,1);
assert.equal(rookie.profit,-1);
let rendered=t.renderMonthlyPerformance();
assert.ok(rendered.includes('Prehľad všetkých levelov')&&rendered.includes('monthly-tables-pair'));
assert.ok(!rendered.includes('monthly-focused-table'));
p.level='elite';p.view='report';
rendered=t.renderMonthlyPerformance();
for(const token of ['is-report-mode','monthly-focused-table','Kumulatívny profit · ELITE','monthly-profit-area','1. – 7. deň','Režim screenshotu','+0,70 u','-0,30 u','BlinQ · ADMIN / ANALYTIKA']) assert.ok(rendered.includes(token),token);
assert.ok(!rendered.includes('monthly-tables-pair'));
assert.ok(rendered.includes('<th>Spolu</th>') && !rendered.includes('<th>Kumulatívne</th>'), 'daily report total header');
assert.ok(css.includes('content:"Spolu";font-size:11px'), 'mobile report total header');
assert.ok(!css.includes('content:"Kumul. u"'), 'retired mobile header');
assert.ok(css.includes('.monthly-focused-table td:nth-child(n+3){\n  text-align:center!important\n}'), 'profit and total cells centered');
assert.ok(html.split('monthly-report-table=20261113').length===3, 'both JS and CSS cache keys updated');
assert.ok(!rendered.includes('1. – 30. deň'));
// Selected-level screenshot report hides the three specifically removed notes.
assert.ok(!rendered.includes('Overené vyhodnotenia · 1 u / tip'));
assert.ok(!rendered.includes('Profit normalizovaný na 1 u / tip'));
assert.ok(!rendered.includes('Vzorka 3 unikátnych vyhodnotených tipov'));
// SVG uses different strokes and shaded areas on each side of zero.
for(const token of ['monthlyAboveZero','monthlyBelowZero',
  'class="monthly-loss-line" clip-path="url(#monthlyBelowZero)"',
  'class="monthly-profit-line" clip-path="url(#monthlyAboveZero)"',
  'class="monthly-loss-area" clip-path="url(#monthlyBelowZero)"']) {
  assert.ok(rendered.includes(token),'missing negative/positive chart split: '+token);
}
assert.ok(rendered.includes('monthly-negative-point'), 'negative last value must have orange endpoint');
assert.ok(!rendered.includes('title='));
p.fullscreen=true;
rendered=t.renderMonthlyPerformance();
assert.ok(rendered.includes('is-monthly-fullscreen')&&rendered.includes('Zavrieť fullscreen'));
p.view='overview';
rendered=t.renderMonthlyPerformance();
assert.ok(!rendered.includes('is-monthly-fullscreen'));
assert.ok(rendered.includes('Vzorka 3 unikátnych vyhodnotených tipov'), 'overview explanatory note retained');
p.month='2026-12';p.view='report';p.fullscreen=false;
rendered=t.renderMonthlyPerformance();
assert.ok(rendered.includes('Zvolený mesiac ešte nezačal.')&&!rendered.includes('monthly-profit-area'));
p.month='2026-11';delete state.feed.member_result_rules.elite;
assert.ok(!t.renderMonthlyPerformance().includes('is-report-mode'));
assert.ok(app.includes('monthly.fullscreen=!Boolean(monthly.fullscreen)'));
assert.ok(app.includes('monthly.filtersExpanded=advancedFilters.open'));
assert.ok(css.includes('monthly-performance.is-monthly-fullscreen'));
assert.ok(css.includes('--monthly-accent:#2df2ad'));
assert.ok(css.includes('stroke:#f5a24c'), 'negative graph line should be amber');
assert.ok(css.includes('rgba(1,17,13,.87)'), 'fullscreen must preserve see-through dark BlinQ background');
assert.ok(html.includes('monthly-report-glass=20261107'));
assert.ok(html.includes('monthly-loss-line=20261107'));
console.log('Admin monthly BlinQ screenshot report: PASS');
