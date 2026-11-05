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
console.log('Local Aces Results, membership and monthly quote contract: PASS');
