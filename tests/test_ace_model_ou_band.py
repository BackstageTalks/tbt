"""Local model-only Aces envelope is a visual hint, never a bookmaker quote."""

from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required")
def test_model_only_aces_envelope_is_strictly_more_than_one_ace_each_way():
    root = Path(__file__).resolve().parents[1]
    js = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
const startAuth=source.indexOf('  function authenticLocalAceProjection(');
const endAuth=source.indexOf('  function authenticMarketSectionRow(',startAuth);
const start=source.indexOf('  function aceDfResultKpiOdds(');
const end=source.indexOf('  function dailyHubRow(',start);
assert(startAuth>0&&endAuth>startAuth&&start>0&&end>start);
const context={firstFinite:x=>x==null?NaN:Number(x),
  hubNumberHtml:(value,label)=>value+' | '+label,
  lcopy:(_en,sk)=>sk,
  escapeHtml:value=>String(value)};
vm.createContext(context);
vm.runInContext(source.slice(startAuth,endAuth),context);
vm.runInContext(source.slice(start,end),context);
const template={
  event_id:'model-aces-1',market:'aces',selection_id:'hurkacz',
  player1:{id:'musetti',name:'Musetti'},player2:{id:'hurkacz',name:'Hurkacz'},
  scheduled_at:'2026-11-02T13:00:00Z',odds:null,
  price_status:'projection_only',projection_model:'ace-count-projection-v4',
  projection:10.9,opponent_projection:5.2,projection_confidence:0.89,
};
assert.equal(context.localAceOuModelBand(template),'O 9.5 / U 12.5');
assert.equal(context.localAceOuModelBand({...template,projection:12.57}),'O 11.5 / U 14.5');
assert.equal(context.localAceOuModelBand({...template,projection:10.5}),'O 8.5 / U 12.5');
assert.equal(context.localAceOuModelBand({...template,projection:1.4}),'U 2.5');
assert.equal(context.localAceOuModelBand({...template,projection:-1}),null);
assert.equal(context.localAceOuModelBand({...template,projection_confidence:.4}),null);
assert.equal(context.localAceOuModelBand({...template,selection_id:'wrong'}),null);
assert.equal(context.localAceOuModelBand({...template,odds:2}),null);
const display=context.projectionOddsHtml(template);
assert(display.includes('O 9.5 / U 12.5'));
assert(display.includes('MODELOVÉ PÁSMO'));
assert(display.includes('Bez O/U kurzu'));
assert(!display.includes('1.80'), 'No fictional bookmaker price for local O/U envelope');
const offered={...template,price_status:'priced_projection',
  odds_contract_version:'ace_df_real_api_v1',price_contract:'player_total_ou',
  provider_id:2,odds_source:'propline',odds_bookmaker:'Book',
  market_line:10.5,ou_side:'over',odds:1.91,
  captured_at:'2026-11-02T09:00:00Z'};
assert.equal(context.localAceOuModelBand(offered),null);
const actual=context.projectionOddsHtml(offered);
assert(actual.includes('1.91')&&!actual.includes('MODELOVÉ PÁSMO'));
console.log('Local Aces O/U band and real-quote precedence: PASS');
"""
    result=subprocess.run(["node","-e",js],cwd=root,text=True,capture_output=True,timeout=25)
    assert result.returncode==0, result.stdout+result.stderr
    assert "PASS" in result.stdout
