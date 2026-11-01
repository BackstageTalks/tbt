'use strict';
// Execute the exact web/app.js pricing helper against the three issued Telegram
// identities. Reusable on the checked-out source and on the CDN-downloaded JS.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2] || 'web/app.js', 'utf8');
const start = source.indexOf('  function stableAceDisplayOdds(');
const end = source.indexOf('  function projectionOddsHtml(', start);
assert(start >= 0 && end > start, 'Missing ACES price normalization from served app.js');
const sandbox = {verifiedAceProviderOdds: row =>
  row.market === 'aces' && row.price_status === 'priced_projection' ? Number(row.odds) : NaN};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end), sandbox);

const actualDay = [
  {name:'Vacherot', event_id:'17377323', selection_id:'158912', scheduled_at:'2026-11-01T14:30:00Z', expected:1.72},
  {name:'Alcaraz', event_id:'17377322', selection_id:'275923', scheduled_at:'2026-11-01T13:00:00Z', expected:1.74},
  {name:'Okamura', event_id:'17453662', selection_id:'130690', scheduled_at:'2026-11-01T08:30:00Z', expected:1.78}
];
for (const {name, event_id, selection_id, scheduled_at, expected} of actualDay) {
  const row = {market:'aces', event_id, selection_id, scheduled_at, odds:2.0,
    price_status:'priced_projection', odds_contract_version:'ace_df_real_api_v1',
    odds_source:'propline', provider_id:2, odds_bookmaker:'PrizePicks',
    captured_at:'2026-11-01T06:11:00Z'};
  assert.equal(sandbox.stableAceDisplayOdds(row), expected, name + ' shared Telegram identity');
  sandbox.normalizeFeedAceOdds({ace_picks:[row], results:[]});
  assert.equal(row.statistical_ace_odds, expected, name + ' visible web display');
  assert.equal(row.odds, 2.0, name + ' frozen source unchanged');
  for (const scheduled_at of ['2026-11-02T14:30:00Z', '2027-05-02T14:30:00Z']) {
    const future = {...row, scheduled_at, statistical_ace_odds:undefined};
    sandbox.normalizeFeedAceOdds({ace_picks:[future], results:[]});
    assert.equal(future.statistical_ace_odds, expected, name + ' permanent 2.00 fallback');
    assert.equal(future.odds, 2.0, name + ' future raw price unchanged');
  }
  const genuine = {...row, odds:2.125, statistical_ace_odds:undefined};
  sandbox.normalizeFeedAceOdds({ace_picks:[genuine], results:[]});
  assert.equal(genuine.statistical_ace_odds, undefined, name + ' independently verified non-placeholder provider quote preserved');
  process.stdout.write(name + ' ' + expected.toFixed(2) + ' PASS\\n');
}
