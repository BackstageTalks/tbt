"""Stable ACES display prices: deterministic per selection and isolated from source odds."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_ace_display_prices_are_stable_bounded_and_do_not_mutate_source():
    js = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const app = fs.readFileSync('web/app.js', 'utf8');
const start = app.indexOf('  function aceDfResultKpiOdds(');
const end = app.indexOf('  function dailyHubRow(', start);
assert(start > 0 && end > start, 'ACES pricing helper must be available');
const sandbox = {
  authenticLiveProjection: row => row.price_status === 'priced_projection' &&
    row.provider_id > 0 && !!row.captured_at && Number(row.odds) >= 1.5,
  firstFinite: value => value == null ? NaN : Number(value),
  hubNumberHtml: (value, label) => value + ' ' + label,
  lcopy: (_en, sk) => sk,
  escapeHtml: value => value,
  aceDfLegacyResultDisplayOdds: () => NaN
};
vm.createContext(sandbox);
vm.runInContext(app.slice(start, end), sandbox);
const row = {
  event_id: 'ace-1', market: 'aces', selection_id: 'player-1',
  scheduled_at: '2026-11-01T16:00:00Z', odds: 2.00,
  price_status: 'priced_projection', provider_id: 2,
  captured_at: '2026-11-01T08:00:00Z'
};
const original = JSON.stringify(row);
const value = sandbox.stableAceDisplayOdds(row);
sandbox.normalizeFeedAceOdds({ace_picks:[row],results:[]});
assert.equal(row.statistical_ace_odds, undefined);
assert(Number.isInteger(Math.round(value * 100)));
assert(value >= 1.60 && value <= 1.80, 'ACES display range');
assert.equal(value, sandbox.stableAceDisplayOdds({...row}));
assert.equal(sandbox.stableAceDisplayOdds({...row, market: 'games'}).toString(), 'NaN');
assert.equal(row.odds, 2.00, 'underlying provider quote unchanged');
assert.equal(row.odds, JSON.parse(original).odds, 'original provider price unchanged');
assert(sandbox.projectionOddsHtml(row).includes('Bez O/U kurzu'));

// A provider-backed PropLine quote must NOT be overwritten by working odds.
const real = {
  ...row, odds: 2.125, odds_contract_version: 'ace_df_real_api_v1',
  odds_source: 'propline', odds_bookmaker: 'bookA',
  price_contract: 'player_total_ou', market_line: 7.5, ou_side: 'over'
};
sandbox.normalizeFeedAceOdds({ace_picks:[real],results:[]});
assert.equal(real.statistical_ace_odds,undefined);
assert.equal(sandbox.verifiedAceProviderOdds(real),2.125);
assert(sandbox.projectionOddsHtml(real).includes('2.13'));
    
// Reproduction: 1 Nov Basel / Vienna / Chennai Aces picks retained 2.00
// as a provider-labelled price on the site, while Telegram showed 1.60-1.80.
const novemberPicks = [
  ['17377323', '158912', '2026-11-01T14:30:00Z', 1.72],
  ['17377322', '275923', '2026-11-01T13:00:00Z', 1.74],
  ['17453662', '130690', '2026-11-01T08:30:00Z', 1.78]
];
for(const [event_id,selection_id,scheduled_at,telegramOdds] of novemberPicks){
  const pick = {...real, event_id, selection_id, scheduled_at, odds:2.00};
  assert(Number.isNaN(sandbox.verifiedAceProviderOdds(pick)), '2.00 must never be considered a verified ACES provider price');
  const expected=sandbox.stableAceDisplayOdds(pick);
  assert.equal(expected,telegramOdds,'Must reproduce frozen Telegram pick identity odds');
  sandbox.normalizeFeedAceOdds({ace_picks:[pick],results:[]});
  assert.equal(pick.statistical_ace_odds,undefined);
  assert(expected>=1.60&&expected<=1.80);
  assert(sandbox.projectionOddsHtml(pick).includes('Bez O/U kurzu'));
  assert(!sandbox.projectionOddsHtml(pick).includes('2.00'));
  assert.equal(pick.odds,2.00,'provider price/provenance must remain frozen');
  const results={event_id,scheduled_at,market_publications:[{...pick,statistical_ace_odds:undefined}]};
  sandbox.normalizeFeedAceOdds({ace_picks:[],results:[results]});
  assert.equal(results.market_publications[0].statistical_ace_odds,expected);
  assert.equal(sandbox.aceDfResultKpiOdds(results.market_publications[0]),expected);
  const future={...pick,statistical_ace_odds:undefined,scheduled_at:'2026-11-02T13:00:00Z'};
  sandbox.normalizeFeedAceOdds({ace_picks:[future],results:[]});
  assert.equal(future.statistical_ace_odds,undefined,'No future quote without an O/U contract');
  assert(sandbox.projectionOddsHtml(future).includes('Bez O/U kurzu'));
  assert(!sandbox.projectionOddsHtml(future).includes('2.00'));
  const nextYear={...pick,statistical_ace_odds:undefined,scheduled_at:'2027-05-02T13:00:00Z'};
  sandbox.normalizeFeedAceOdds({ace_picks:[nextYear],results:[]});
  assert.equal(nextYear.statistical_ace_odds,undefined,'Future Aces count insight remains unpriced');
  assert(sandbox.projectionOddsHtml(nextYear).includes('Bez O/U kurzu'));
  const futureResults={
    event_id,scheduled_at:nextYear.scheduled_at,
    market_publications:[{...nextYear,statistical_ace_odds:undefined}]
  };
  sandbox.normalizeFeedAceOdds({ace_picks:[],results:[futureResults]});
  assert.equal(futureResults.market_publications[0].statistical_ace_odds,expected);
}

const unverified = {...real, odds_bookmaker: ''};
sandbox.normalizeFeedAceOdds({ace_picks:[unverified],results:[]});
assert.equal(unverified.statistical_ace_odds,undefined);
assert(sandbox.projectionOddsHtml(unverified).includes('Bez O/U kurzu'));
const result = {
  event_id:'ace-1',scheduled_at:row.scheduled_at,
  market_publications:[{
    market:'aces',selection_id:'player-1',odds:2.0,
    price_status:'priced_projection',result:{status:'win',profit_units:1.0}
  }]
};
sandbox.normalizeFeedAceOdds({ace_picks:[],results:[result]});
assert.equal(result.market_publications[0].statistical_ace_odds,value);
assert.equal(sandbox.aceDfResultKpiOdds(result.market_publications[0]),value);
assert.equal(result.market_publications[0].odds,2.0);

const realResult = {
  event_id:'ace-1', scheduled_at:row.scheduled_at,
  market_publications:[{
    ...real, market:'aces', selection_id:'player-1', issued_at:row.scheduled_at
  }]
};
sandbox.normalizeFeedAceOdds({ace_picks:[],results:[realResult]});
assert.equal(realResult.market_publications[0].statistical_ace_odds,undefined);
assert.equal(sandbox.aceDfResultKpiOdds(realResult.market_publications[0]),2.125);
assert.equal(realResult.market_publications[0].odds,2.125);
const historical = {
  event_id:'old-ace', scheduled_at:'2026-10-31T18:00:00Z',
  market_publications:[{
    market:'aces',selection_id:'player-1',odds:2.0,
    issued_at:'2026-10-31T12:00:00Z',price_status:'priced_projection'
  }]
};
sandbox.normalizeFeedAceOdds({ace_picks:[],results:[historical]});
assert.equal(historical.market_publications[0].statistical_ace_odds,undefined);
assert(sandbox.projectionOddsHtml({...row, market: 'double_faults'}).includes('2.00'));
assert(sandbox.projectionOddsHtml({...row, market: 'aces', price_status: 'projection_only'}).includes('Bez O/U kurzu'));
const values = new Set();
for(let i=0;i<200;i++){
  const v = sandbox.stableAceDisplayOdds({
    ...row, event_id:'ace-'+i, scheduled_at:'2026-11-'+String(i%28+1).padStart(2,'0')+'T16:00:00Z'
  });
  assert(v >= 1.60 && v <= 1.80);
  values.add(v);
}
assert(values.size > 10, 'values should vary among different picks');
console.log('stable ACES display: PASS');
"""
    run = subprocess.run(
        ["node", "-e", js], cwd=ROOT, text=True, capture_output=True, timeout=20
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS" in run.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required")
def test_ace_ball_is_inline_only_for_projected_ace_leader():
    js = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const app=fs.readFileSync('web/app.js','utf8');
const helperStart=app.indexOf('  function aceLeaderHintHtml(');
const helperEnd=app.indexOf('  function hubNumberHtml(',helperStart);
const matchStart=app.indexOf('  function dailyHubMatch(');
const matchEnd=app.indexOf('  function recentFormData(',matchStart);
assert(helperStart>0&&helperEnd>helperStart&&matchStart>0&&matchEnd>matchStart);
const cx={
  escapeHtml:x=>String(x),
  sideAvatarHtml:()=>'',flagIconHtml:()=>'',firstFinite:()=>null,
};
vm.createContext(cx);
vm.runInContext(app.slice(helperStart,helperEnd)+app.slice(matchStart,matchEnd),cx);
const row={
  market:'aces',
  aces_superiority_hint:'Beta',
  projection_subject:'Beta',selection_id:'22',
  player1:{id:'11',name:'Alpha'},
  player2:{id:'22',name:'Beta'}
};
const html=cx.dailyHubMatch(row);
assert.equal((html.match(/ace-leader-ball/g)||[]).length,1);
assert(html.includes('Alpha</b></span>'));
assert(html.includes('Beta</b><svg class="ace-leader-ball"'));
assert(html.includes('aria-hidden="true"'));
assert(!html.includes('Viac es'));
assert(!html.includes('title="Viac'));
assert.equal((cx.dailyHubMatch({...row,market:'games'}).match(/ace-leader-ball/g)||[]).length,0);
assert.equal((cx.dailyHubMatch({...row,aces_superiority_hint:'Unknown',projection_subject:'Unknown'}).match(/ace-leader-ball/g)||[]).length,0);
assert.equal((cx.dailyHubMatch({...row,aces_superiority_hint:'Alpha'}).match(/ace-leader-ball/g)||[]).length,1);
// No inline hint remains in the pick cell or beneath the detail grid.
const ace=app.slice(app.indexOf('  function aceProjectionDetailHtml('),app.indexOf('  function openAceProjection('));
assert(ace.includes('aceLeaderHintHtml(row,row?.player1,d.selectedName)'));
assert(!ace.includes('aceLeaderHintHtml(row)}'));
const cells=app.slice(app.indexOf("if(sourceTab==='ace'||sourceTab==='double_faults')"),app.indexOf("const probability=marketProbability(row)"));
assert(!cells.includes('aceLeaderHintHtml'));
const card=app.slice(app.indexOf('  function marketPreviewCard('),app.indexOf('  function ',app.indexOf('  function marketPreviewCard(')+7));
assert(card.includes('aceLeaderHintHtml(row,p1,p1Name)'));
assert(card.includes('aceLeaderHintHtml(row,p2,p2Name)'));
assert(!card.includes('aceLeaderHintHtml(row)'));
console.log('ACES white ball display: PASS');
"""
    run = subprocess.run(["node", "-e", js], cwd=ROOT, text=True,
                         capture_output=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS" in run.stdout
