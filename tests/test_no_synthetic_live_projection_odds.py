"""Real provider odds first; model-qualified local ACES only when needed."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web/app.js").read_text(encoding="utf-8")
PIPE = (ROOT / "scripts/pipeline.py").read_text(encoding="utf-8")


def test_live_cards_require_exact_api_odds_and_never_use_results_placeholder():
    live = APP[APP.index("function projectionOddsHtml("):
               APP.index("function dailyHubRow(")]
    contract = APP[APP.index("function authenticLiveProjection("):
                   APP.index("function dailyHubRow(")]
    assert "row?.price_status==='priced_projection'" in contract
    assert "Number.isFinite(odds)&&odds>=1.50" in contract
    assert "Boolean(row?.captured_at)" in contract
    assert "authenticMarketSectionRow(row,key)" in contract
    assert "function authenticLocalAceProjection(row)" in contract
    assert "row?.projection_model!=='ace-count-projection-v4'" in contract
    assert "aceDfLegacyResultDisplayOdds" not in live
    assert "hubNumberHtml('N/A',reason)" in live


def test_actual_api_price_requirement_is_enforced_before_issuing_bets():
    live = PIPE[PIPE.index("# Market-first publication is strict:"):
                PIPE.index("# Ten per independent category")]
    assert 'row.get("price_status") == "priced_projection"' in live
    assert 'and provider > 0 and bool(row.get("captured_at"))' in live
    assert 'and 1.50 <= odds < float("inf")' in live
    assert 'row.get("odds_contract_version") == "ace_df_real_api_v1"' in live
    assert 'source = str(row.get("odds_source") or "").strip().lower()' in live
    assert '(source == "rapidapi" and provider == 1)' in live
    assert 'source == "propline"' in live
    assert 'and provider == 2' in live
    assert 'and bool(row.get("odds_bookmaker"))' in live
    assert "publishable_api_price(row) or eligible_local_ace_projection(row)" in live
    assert "verified_ace_odds(row) is not None" in live
    assert "sg_picks = [row for row in sg_picks if publishable_api_price(row)]" in live


def test_local_aces_admission_is_isolated_from_other_public_projection_markets():
    import shutil
    import subprocess
    import pytest

    if shutil.which("node") is None:
        pytest.skip("Node.js required")
    script = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const app=fs.readFileSync('web/app.js','utf8');
const start=app.indexOf('  function authenticLocalAceProjection(');
const end=app.indexOf('  function marketProbability(',start);
assert(start>0&&end>start);
const ace={
  event_id:'a100',scheduled_at:'2026-11-02T12:00:00Z',
  market:'aces',price_status:'projection_only',odds:null,
  projection_model:'ace-count-projection-v4',
  player1:{id:'11'},player2:{id:'22'},selection_id:'11',
  projection:8.6,opponent_projection:3.2,projection_confidence:0.77
};
const df={...ace,market:'double_faults'};
const sg={...ace,market:'games'};
const stale={...ace,scheduled_at:'2026-10-31T12:00:00Z'};
const invalid={...ace,selection_id:'third-player'};
const context={
  state:{feed:{ace_picks:[ace,df,stale,invalid],sg_picks:[sg]}},
  stableAceDisplayOdds:()=>1.67,
  authenticLiveProjection:r=>r.price_status==='priced_projection'&&Number(r.odds)>1.5,
};
vm.createContext(context);
vm.runInContext(app.slice(start,end),context);
assert.equal(context.marketRows('ace').length,1);
assert.equal(context.marketRows('sg').length,0);
assert.equal(context.marketRows('ace')[0].event_id,'a100');
assert.equal(context.authenticLocalAceProjection({...ace,odds:2}),false);
assert.equal(context.authenticLocalAceProjection({...ace,projection_confidence:0.4}),false);
console.log('ACES-only local market rows: PASS');
"""
    run = subprocess.run(["node", "-e", script], cwd=ROOT, text=True,
                         capture_output=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS" in run.stdout
