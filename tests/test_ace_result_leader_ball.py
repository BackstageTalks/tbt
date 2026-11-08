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
const mark=(row,player,other)=>sandbox.aceSettledLeaderBallHtml(row,player,player.name,other);
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
  {...pub.result,status:'retired'},
  {...pub.result,status:'hit',reason:'retired_after_ou_decided'},
  {...pub.result,status:'hit',reason:'retired_after_ou_decided',retirement_line_decided:true},
  {...pub.result,status:'hit',reason:'retired_after_ou_decided',retirement_line_decided:true,runtime_source:'unverified'},
  {...pub.result,status:'retired',reason:'retired_after_ou_decided',retirement_line_decided:true,runtime_source:'match_status_snapshot'},
  {...pub.result,status:'hit',reason:'retired_after_ou_decided',retirement_line_decided:true,runtime_source:'match_status_snapshot',void:true}
])assert.equal(mark({...pub,result},a),'','unknown/invalid/interrupted');
assert.equal(mark({...pub,result:null},a),'','missing settlement');
assert.equal(mark({...pub,market:'double_faults'},a),'','not an Aces publication');
assert.equal(mark({...pub,selection_id:'b'},a),'','wrong frozen selection');
assert.equal(mark({...pub,projection_subject:'Musetti'},a),'','conflicting issued leader');
assert.equal(mark({...pub,issued_snapshot:{projection:{projection_subject:'Musetti'}}},a),'','frozen snapshot supersedes later row');
assert(mark({...pub,result:{...pub.result,status:'void'}},a).includes('ace-leader-ball'),'O/U line push does not erase correct leader');
assert(mark({...pub,result:{...pub.result,status:'void',void:true}},a).includes('ace-leader-ball'),'legacy void flag on O/U push does not hide successful leader');
// Real regression shape: original Mayo selection uses an issued provider ID
// that no longer matches the presentation profile IDs on the Results row.
const mayo={id:'display-mayo',name:'Aidan Mayo'};
const andrade={id:'display-andrade',name:'Andres Andrade'};
const legacy={...pub,selection_id:'issued-mayo',projection_subject:'Aidan Mayo',
  result:{status:'hit',correct:true,actual_count:5,opponent_actual_count:0}};
assert(mark(legacy,mayo,andrade).includes('ace-leader-ball'),
  'Aidan Mayo 5-0: frozen leader must survive display ID drift');
assert.equal(mark(legacy,andrade,mayo),'','never mark the actual losing player');
assert.equal(mark({...legacy,result:{...legacy.result,actual_count:0,opponent_actual_count:5}},mayo,andrade),'',
  'same selection but opponent had more Aces');
assert.equal(mark({...legacy,result:{...legacy.result,opponent_actual_count:null}},mayo,andrade),'',
  'no original opponent source count');
assert.equal(mark({...legacy,selection_id:andrade.id},mayo,andrade),'',
  'explicit opponent selection ID overrides matching display name');
assert.equal(mark({...legacy,projection_subject:'Andres Andrade'},mayo,andrade),'',
  'conflicting original selection name');
assert.equal(mark({...legacy,projection_subject:''},mayo,andrade),'',
  'no proof of original named leader with mismatched ID');
assert.equal(mark({...legacy,issued_snapshot:{projection:{projection_subject:'Andres Andrade'}}},mayo,andrade),'',
  'frozen conflicting snapshot takes precedence');
assert.equal(mark({...legacy,aces_superiority_player_id:andrade.id},mayo,andrade).includes('ace-leader-ball'),true,
  'auxiliary hint ID cannot override verified issued subject');
// Identity recovery is not permissible without the opponent to prove uniqueness.
assert.equal(mark(legacy,mayo),'');
// The real Nov 7 Telegram bridge stores "Aidan Mayo Over 4.5 Aces" as
// publication.selection, without any projection_subject. The previous fix
// never parsed this frozen field, so old ID namespaces still lost the ball.
const frozenOU={...legacy,projection_subject:undefined,selection:'Aidan Mayo Over 4.5 Aces',
  price_contract:'player_total_ou',ou_side:'over',market_line:4.5};
assert(mark(frozenOU,mayo,andrade).includes('ace-leader-ball'),
  'frozen issued Aces Over 4.5 record must label Mayo, even with presentation ID drift');
// The authentic Mayo match was RETIRED; Over 4.5 was irrevocably decided
// when the verified player had five Aces. A 'retired_after_ou_decided' reason
// must not suppress the correctly settled 5:0 Aces leader.
const decidedOnRetirement={...frozenOU,result:{
  ...frozenOU.result,status:'hit',correct:true,void:false,
  reason:'retired_after_ou_decided',retirement_line_decided:true,
  runtime_source:'match_status_snapshot'
}};
assert(mark(decidedOnRetirement,mayo,andrade).includes('ace-leader-ball'),
  'Mayo decided Over on retirement and verified 5:0 must get leader ball');
assert.equal(mark(decidedOnRetirement,andrade,mayo),'','no opponent ball');
for(const invalid of [
  {...decidedOnRetirement.result,retirement_line_decided:false},
  {...decidedOnRetirement.result,runtime_source:undefined},
  {...decidedOnRetirement.result,reason:'retired'},
  {...decidedOnRetirement.result,status:'retired'},
  {...decidedOnRetirement.result,void:true},
  {...decidedOnRetirement.result,opponent_actual_count:null},
  {...decidedOnRetirement.result,actual_count:undefined},
  {...decidedOnRetirement.result,actual_count:0,opponent_actual_count:5},
])assert.equal(mark({...decidedOnRetirement,result:invalid},mayo,andrade),'',
  'retirement needs exact verified decided counts');

assert.equal(mark(frozenOU,andrade,mayo),'','must not label Andrade instead');
for(const incorrect of [
  {...frozenOU,market_line:5.5},
  {...frozenOU,ou_side:'under'},
  {...frozenOU,selection:'Andres Andrade Over 4.5 Aces'},
  {...frozenOU,selection:'Aidan Mayo Over 4.5 Double Faults'},
  {...frozenOU,projection_subject:'Andres Andrade'},
  {...frozenOU,selection_id:andrade.id},
]){
  assert.equal(mark(incorrect,mayo,andrade),'','contract mismatch cannot label a different bet');
}
assert.equal(mark({...frozenOU,result:{...frozenOU.result,opponent_actual_count:null}},mayo,andrade),'',
  'a missing opponent count must not be fabricated as zero');
const mostAces={...frozenOU,market:'most_aces',selection:'Aidan Mayo',
  price_contract:'player_superiority',ou_side:null,market_line:null,
  issued_at:'2026-11-07T07:00:00Z'};
assert(mark(mostAces,mayo,andrade).includes('ace-leader-ball'),'settled Most Aces win gets ball');
assert.equal(mark({...mostAces,result:{...mostAces.result,correct:false}},mayo,andrade),'',
  'Most Aces loss never gets leader win ball');
assert.equal(mark({...mostAces,result:{...mostAces.result,actual_count:5,opponent_actual_count:5}},mayo,andrade),'',
  'Most Aces tie never gets ball');
assert.equal(mark({...mostAces,result:{...mostAces.result,status:'void'}},mayo,andrade),'',
  'void Most Aces never gets ball');
assert.equal(mark({...mostAces,result:{...mostAces.result,opponent_actual_count:null}},mayo,andrade),'',
  'incomplete Most Aces source cannot be scored');
// Results must not render null/missing opponent statistics as zero.
const textBegin=src.indexOf('  function projectionResultUnitLabel(');
const textEnd=src.indexOf('  function resultCategoryLabel(',textBegin);
assert(textBegin>0&&textEnd>textBegin);
sandbox.lcopy=(en,sk)=>sk;
vm.runInContext(src.slice(textBegin,textEnd),sandbox);
assert.equal(sandbox.projectionResultActualText(frozenOU),'5 esá · súper 0 esá');
assert.equal(sandbox.projectionResultActualText({...frozenOU,result:{...frozenOU.result,opponent_actual_count:null}}),'5 esá · súper —');
assert.equal(sandbox.projectionResultActualText({...frozenOU,result:{...frozenOU.result,actual_count:null}}),'—');

// Prediction still labels the pre-match projected leader independently.
assert(sandbox.aceLeaderHintHtml(pub,a,a.name).includes('ace-leader-ball'));
const results=src.slice(renderStart,renderEnd);
assert(results.includes('aceSettledLeaderBallHtml(publication,p1,p1Name,p2)'));
assert(results.includes('aceSettledLeaderBallHtml(publication,p2,p2Name,p1)'));
assert(!results.includes('aceLeaderHintHtml(r,p1,p1Name)'));
assert(!results.includes('aceLeaderHintHtml(r,p2,p2Name)'));
assert(results.includes('publicationOutcome(publication)'));
// No O/U settlement, local Aces pricing, ROI or source archive writes in the helper.
const helper=src.slice(src.indexOf('  function aceSettledLeaderBallHtml('),end);
for(const forbidden of ['profit_units','statistical_ace_odds','fetch(', 'result.profit_units=']) {
 assert(!helper.includes(forbidden),'leader marker must stay independent: '+forbidden);
}
console.log('ACES leader result marker: PASS');
"""
    run = subprocess.run(["node", "-e", js], cwd=ROOT, text=True,
                         capture_output=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS" in run.stdout


def test_worker_only_site_parity_preserves_native_retired_aces_evidence():
    """Auditable web-source evidence: never infer retirement approval from status hit alone."""
    from tbt.services.telegram_site_parity import site_day_projection

    feed = {"results": [{
        "event_id": "17427331", "betting_day": "2026-11-07",
        "scheduled_at": "2026-11-07T18:30:00+00:00",
        "player1": {"id": "309157", "name": "Aidan Mayo"},
        "player2": {"id": "168420", "name": "Andres Andrade"},
        "market_publications": [{
            "section": "ace", "market": "aces",
            "publication_status": "published",
            "selection": "Aidan Mayo Over 4.5 Aces",
            "selection_id": "309157",
            "publication_key": "local-aces-ou-v1:17427331:309157:over:4.5",
            "issued_at": "2026-11-07T06:46:28+00:00",
            "result": {
                "status": "hit", "correct": True, "void": False,
                "reason": "retired_after_ou_decided",
                "retirement_line_decided": True,
                "actual_count": 5, "opponent_actual_count": 0,
                "runtime_source": "match_status_snapshot",
            },
        }],
    }]}
    output = site_day_projection(feed, "2026-11-07")
    assert output["member_render_verified"] is False
    assert output["provider_requests"] == 0
    assert len(output["rows"]) == 1
    result = output["rows"][0]["result"]
    assert result["reason"] == "retired_after_ou_decided"
    assert result["retirement_line_decided"] is True
    assert result["actual_count"] == 5
    assert result["opponent_actual_count"] == 0
