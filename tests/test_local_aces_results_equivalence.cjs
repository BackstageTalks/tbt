const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
const start=source.indexOf('  function approvedLocalAceResultOdds(publication){');
const end=source.indexOf('  function resultVisibleOdds(publication){',start);
assert(start>0&&end>start,'Approved local Aces function must be present');
const context={
  verifiedAceProviderOdds:p=>p.odds_contract_version==='ace_df_real_api_v1'&&p.captured_at?Number(p.odds):NaN,
  Date,Number,String,Math
};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
const odds=context.approvedLocalAceResultOdds;
const frozen={market:'aces',price_contract:'player_total_ou',ou_side:'over',market_line:4.5,
  selection_id:'270414',issued_at:'2026-11-02T09:27:00Z',price_status:'projection_only',
  statistical_ace_odds:1.79};
assert.equal(odds(frozen),1.79);
assert.equal(odds({...frozen,price_status:'priced_projection',price_basis:'local_aces_statistical_v1',odds:1.79}),1.79);
assert(Number.isNaN(odds({...frozen,issued_at:'2026-10-31T09:27:00Z'})));
assert(Number.isNaN(odds({...frozen,market_line:null})));
assert(Number.isNaN(odds({...frozen,price_contract:'player_superiority'})));
assert(Number.isNaN(odds({...frozen,odds_contract_version:'ace_df_real_api_v1',captured_at:'2026-11-02T08:00:00Z',odds:1.78})));
for(const section of [
  source.slice(source.indexOf('function localResultMetrics('),source.indexOf('function resultLiveMaxOddsHtml(')),
  source.slice(source.indexOf('function monthlyFinancialRecord('),source.indexOf('function renderMonthlyPerformance('))
])assert(section.includes('approvedLocalAceResultOdds(publication)'));
assert(source.includes('const approvedLocalQuote=approvedLocalAceResultOdds(publication)'));

const gradedStart=source.indexOf('  function localResultMetrics(rows,category,filters=null){');
const gradedEnd=source.indexOf('  function resultLiveMaxOddsHtml(',gradedStart);
assert(gradedStart>0&&gradedEnd>gradedStart,'Results aggregate function missing');
context.settledPublishedEntries=(rows)=>rows.map(publication=>({publication}));
context.statsHaveExcludedMarkets=()=>false;
context.publicationOutcome=p=>({kind:p.result?.correct===true?'win':p.result?.correct===false?'loss':'void'});
context.aceDfResultKpiOdds=p=>NaN;
vm.runInContext(source.slice(gradedStart,gradedEnd),context);
const aceWin={...frozen,result:{correct:true},statistical_ace_odds:1.79};
const aceLoss={...frozen,selection_id:'289146',statistical_ace_odds:1.73,result:{correct:false}};
const winnerWin={market:'match_winner',section:'top_daily',price_status:'priced',
  odds:1.98,result:{correct:true,staked_units:1,profit_units:.98}};
const winnerLoss={market:'match_winner',section:'top_daily',price_status:'priced',
  odds:1.75,result:{correct:false,staked_units:1,profit_units:-1}};
const all=context.localResultMetrics([aceWin,aceLoss,winnerWin,winnerLoss],'all',{membership:'elite'});
assert.equal(all.wins,2);
assert.equal(all.losses,2);
assert.equal(all.sample,4);
assert.equal(all.unitSample,4);
assert(Math.abs(all.profit+.23)<1e-9);
assert(Math.abs(all.roi+.0575)<1e-9);
assert(Math.abs(all.avgOdds-1.8125)<1e-9);
const aceOnly=context.localResultMetrics([aceWin,aceLoss],'ace',{membership:'elite'});
assert.equal(aceOnly.unitSample,2);
assert(Math.abs(aceOnly.profit+.21)<1e-9);
const monthlyStart=source.indexOf('  function monthlyFinancialRecord(publication');
const monthlyEnd=source.indexOf('  function renderMonthlyPerformance(){',monthlyStart);
assert(monthlyStart>0&&monthlyEnd>monthlyStart);
vm.runInContext(source.slice(monthlyStart,monthlyEnd),context);
assert(Math.abs(context.monthlyFinancialRecord(aceWin).profit-.79)<1e-9);
assert.equal(context.monthlyFinancialRecord(aceLoss).profit,-1);

console.log('Local Aces Results/ELITE/monthly numeric parity: PASS');
