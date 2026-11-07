"""Regression: issued Aces leader marker is independent of the O/U result."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required")
def test_results_aces_ball_requires_original_leader_and_verified_actual_superiority():
    js = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const src=fs.readFileSync('web/app.js','utf8');
const begin=src.indexOf('  function aceLeaderHintHtml(');
const end=src.indexOf('  function hubNumberHtml(',begin);
const renderStart=src.indexOf('  function renderResults(){');
const renderEnd=src.indexOf('  function openResultsRange(',renderStart);
assert(begin>=0&&end>begin&&renderStart>=0&&renderEnd>renderStart);
const sandbox={};
vm.createContext(sandbox);
vm.runInContext(src.slice(begin,end),sandbox);
const a={id:'a',name:'Hurkacz'},b={id:'b',name:'Musetti'};
const pub={
  market:'aces',selection_id:'a',projection_subject:'Hurkacz',
  price_contract:'player_total_ou',ou_side:'over',market_line:10.5,
  result:{status:'miss',correct:false,actual_count:9,opponent_actual_count:5}
};
const mark=(row,player)=>sandbox.aceSettledLeaderBallHtml(row,player,player.name);
assert(mark(pub,a).includes('ace-leader-ball'),'leader succeeded even when Over lost');
assert.equal(mark(pub,b),'','never mark opponent');
assert.equal(mark({...pub,result:{...pub.result,correct:true}},a).includes('ace-leader-ball'),true,'O/U WIN independent of leader');
for(const [actual,other] of [[5,9],[5,5]]) {
  assert.equal(mark({...pub,result:{...pub.result,correct:true,actual_count:actual,opponent_actual_count:other}},a),'','incorrect leader/tie');
}
for(const result of [
  {...pub.result,opponent_actual_count:null},
  {...pub.result,actual_count:null},
  {...pub.result,opponent_actual_count:undefined},
  {...pub.result,actual_count:'not known'},
  {...pub.result,actual_count:9.5},
  {...pub.result,status:'retired'}
])assert.equal(mark({...pub,result},a),'','unknown/invalid/interrupted');
assert.equal(mark({...pub,result:null},a),'','missing settlement');
assert.equal(mark({...pub,market:'double_faults'},a),'','not an Aces publication');
assert.equal(mark({...pub,selection_id:'b'},a),'','wrong frozen selection');
assert.equal(mark({...pub,projection_subject:'Musetti'},a),'','conflicting issued leader');
assert.equal(mark({...pub,issued_snapshot:{projection:{projection_subject:'Musetti'}}},a),'','frozen snapshot supersedes later row');
assert(mark({...pub,result:{...pub.result,status:'void'}},a).includes('ace-leader-ball'),'O/U line push does not erase correct leader');
// Prediction still labels the pre-match projected leader independently.
assert(sandbox.aceLeaderHintHtml(pub,a,a.name).includes('ace-leader-ball'));
const results=src.slice(renderStart,renderEnd);
assert(results.includes('aceSettledLeaderBallHtml(publication,p1,p1Name)'));
assert(results.includes('aceSettledLeaderBallHtml(publication,p2,p2Name)'));
assert(!results.includes('aceLeaderHintHtml(r,p1,p1Name)'));
assert(!results.includes('aceLeaderHintHtml(r,p2,p2Name)'));
assert(results.includes('publicationOutcome(publication)'));
// No O/U settlement, local Aces pricing, ROI or source archive writes in the helper.
const helper=src.slice(src.indexOf('  function aceSettledLeaderBallHtml('),end);
for(const forbidden of ['market_line','ou_side','result.correct','profit_units','statistical_ace_odds','fetch(']) {
 assert(!helper.includes(forbidden),'leader marker must stay independent: '+forbidden);
}
console.log('ACES leader result marker: PASS');
"""
    run = subprocess.run(["node", "-e", js], cwd=ROOT, text=True,
                         capture_output=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS" in run.stdout
