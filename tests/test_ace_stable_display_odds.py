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
assert.equal(row.statistical_ace_odds, value);
assert(Number.isInteger(Math.round(value * 100)));
assert(value >= 1.60 && value <= 1.80, 'ACES display range');
assert.equal(value, sandbox.stableAceDisplayOdds({...row}));
assert.equal(sandbox.stableAceDisplayOdds({...row, market: 'games'}).toString(), 'NaN');
assert.equal(row.odds, 2.00, 'underlying provider quote unchanged');
assert.equal(row.odds, JSON.parse(original).odds, 'original provider price unchanged');
assert(sandbox.projectionOddsHtml(row).includes(value.toFixed(2)));
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
assert(sandbox.projectionOddsHtml({...row, market: 'aces', price_status: 'projection_only'}).includes(value.toFixed(2)));
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
