"""Native Results CAS repair of originally sent daily Telegram Aces.

No mock winner-only grading: tests exercise the existing live-status grader.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"api"))
from tbt.services import telegram_daily_aces_reconcile as bridge

NOW=datetime(2026,11,7,21,30,tzinfo=timezone.utc)
DAY="2026-11-07"
ISSUED="2026-11-07T06:53:50+00:00"
START="2026-11-07T10:00:00+00:00"

@pytest.fixture
def scene(monkeypatch):
    source={"event_id":"m1","scheduled_at":START,"betting_day":DAY,
            "player1":{"id":"p1","name":"P One"},
            "player2":{"id":"p2","name":"P Two"},
            "tour":"ATP"}
    status={"status":"win","checked_at":"2026-11-07T12:10:00+00:00",
            "provider_status":"finished ended",
            "provider_home_id":"p1","provider_away_id":"p2",
            "projection_stats_p1_id":"p1","projection_stats_p2_id":"p2",
            "projection_stats":{"p1_aces":8,"p2_aces":3}}
    ref={"channel":"aces","section":"ace","market":"aces",
         "event_id":"m1","selection_id":"p1",
         "scheduled_at":START,
         "name":"P One","market_line":5.5,
         "projection_direction":"over",
         "publication_key":"local-aces-ou-v1:m1:p1:over:5.5",
         "odds":1.7,"price_basis":"local_aces_statistical_v1",
         "projection":7.4}
    receipt={"status":"sent","sent_at":ISSUED,
             "message_ids":[740,741],"rows":[ref]}
    feed={"ace_picks":[source]}
    snapshot={"statuses":{"m1":status}}
    archived=[]
    monkeypatch.setattr(bridge,"load_settled_results_archive",
                        lambda:deepcopy(archived))
    def save(rows):
        archived.extend(deepcopy(rows))
        return {"verified":True,"added":len(rows),"updated":0}
    monkeypatch.setattr(bridge,"save_settled_results_archive",save)
    return receipt,feed,snapshot,archived

def test_true_original_aces_native_cas_dry_run_commit_and_idempotence(scene):
    receipt,feed,snapshot,archived=scene
    planned=bridge.reconcile(DAY,receipt,feed,snapshot,now=NOW)
    assert planned["status"]=="dry_run"
    assert planned["net_new_aces"]==1
    assert planned["provider_requests"]==0
    assert archived==[]
    with pytest.raises(ValueError,match="Dry-run"):
        bridge.reconcile(DAY,receipt,feed,snapshot,dry_run=False,
                         expected_digest="invalid",now=NOW)
    confirmed=bridge.reconcile(DAY,receipt,feed,snapshot,dry_run=False,
                               expected_digest=planned["digest"],now=NOW)
    assert confirmed["status"]=="verified"
    assert confirmed["readback_new_aces"]==1
    assert len(archived)==1
    pub=archived[0]["market_publications"][0]
    assert pub["publication_key"]==receipt["rows"][0]["publication_key"]
    assert pub["market_line"]==5.5 and pub["odds"]==1.7
    assert pub["result"]["actual_count"]==8
    assert pub["result"]["correct"] is True
    assert pub["result"]["profit_units"]==pytest.approx(.7)
    again=bridge.reconcile(DAY,receipt,feed,snapshot,now=NOW)
    assert again["net_new_aces"]==0 and again["already_verified"]==1

def test_unfinished_game_or_wrong_provider_players_never_written(scene):
    receipt,feed,snapshot,archived=scene
    for mutation in (
        {"status":"live"},
        {"provider_status":"inprogress 2nd set"},
        {"provider_away_id":"someone_else"},
        {"projection_stats_p1_id":"wrong"},
        {"projection_stats":{"total_sets":2}},
    ):
        data=deepcopy(snapshot)
        data["statuses"]["m1"].update(mutation)
        result=bridge.reconcile(DAY,receipt,feed,data,now=NOW)
        assert result["net_new_aces"]==0
        assert result["pending_evidence"]==1
        assert archived==[]

def test_retirement_is_void_unless_over_line_already_crossed(scene):
    receipt,feed,snapshot,archived=scene
    status=snapshot["statuses"]["m1"]
    status["status"]="retired"
    status["provider_status"]="finished retired"
    status["projection_stats"]["p1_aces"]=4
    preview=bridge.reconcile(DAY,receipt,feed,snapshot,now=NOW)
    assert preview["net_new_aces"]==1
    bridge.reconcile(DAY,receipt,feed,snapshot,dry_run=False,
                     expected_digest=preview["digest"],now=NOW)
    pub=archived[0]["market_publications"][0]
    assert pub["result"]["void"] is True
    assert pub["result"]["staked_units"]==0
    archived.clear()
    status["projection_stats"]["p1_aces"]=8
    preview=bridge.reconcile(DAY,receipt,feed,snapshot,now=NOW)
    bridge.reconcile(DAY,receipt,feed,snapshot,dry_run=False,
                     expected_digest=preview["digest"],now=NOW)
    pub=archived[0]["market_publications"][0]
    assert pub["result"]["correct"] is True
    assert pub["result"]["retirement_line_decided"] is True

@pytest.mark.parametrize("change",[
    {"selection_id":"p3"},
    {"market_line":6.5},
    {"publication_key":"local-aces-ou-v1:m1:p2:over:5.5"},
    {"price_basis":"provider_unverified"},
    {"odds":2.0},
    {"scheduled_at":"2026-11-07T05:00:00+00:00"},
])
def test_invalid_immutable_original_fails_closed(scene,change):
    receipt,feed,snapshot,archived=scene
    receipt["rows"][0].update(change)
    with pytest.raises(ValueError):
        bridge.reconcile(DAY,receipt,feed,snapshot,now=NOW)
    assert archived==[]

def test_changed_snapshot_invalidates_dry_run_digest(scene):
    receipt,feed,snapshot,archived=scene
    planned=bridge.reconcile(DAY,receipt,feed,snapshot,now=NOW)
    snapshot["statuses"]["m1"]["projection_stats"]["p1_aces"]=2
    with pytest.raises(ValueError,match="Dry-run"):
        bridge.reconcile(DAY,receipt,feed,snapshot,dry_run=False,
                         expected_digest=planned["digest"],now=NOW)
    assert archived==[]

def test_same_event_wrong_roster_is_not_usable_as_source(scene):
    receipt,feed,snapshot,archived=scene
    feed["ace_picks"][0]["player1"]["id"]="other"
    report=bridge.reconcile(DAY,receipt,feed,snapshot,now=NOW)
    assert report["net_new_aces"]==0 and report["pending_evidence"]==1

def test_inconsistent_existing_archived_original_blocks_all_writes(scene):
    receipt,feed,snapshot,archived=scene
    preview=bridge.reconcile(DAY,receipt,feed,snapshot,now=NOW)
    bridge.reconcile(DAY,receipt,feed,snapshot,dry_run=False,
                     expected_digest=preview["digest"],now=NOW)
    archived[0]["market_publications"][0]["result"]["correct"]=False
    with pytest.raises(ValueError,match="Conflicting"):
        bridge.reconcile(DAY,receipt,feed,snapshot,now=NOW)


def test_confirmed_issued_rollover_supplies_source_after_daily_feed_rotates(scene):
    receipt,feed,snapshot,archived=scene
    original=deepcopy(feed["ace_picks"][0])
    feed["ace_picks"]=[]
    snapshot["rollover_issued_rows"]=[{
        "confirmed_only":True,"betting_day":DAY,
        "section":"ace_picks","row":original,
    }]
    planned=bridge.reconcile(DAY,receipt,feed,snapshot,now=NOW)
    assert planned["net_new_aces"]==1
    committed=bridge.reconcile(
        DAY,receipt,feed,snapshot,dry_run=False,
        expected_digest=planned["digest"],now=NOW)
    assert committed["readback_new_aces"]==1
    assert archived[0]["market_publications"][0]["result"]["correct"] is True


@pytest.mark.parametrize("change", [
    {"confirmed_only":False},
    {"betting_day":"2026-11-06"},
    {"section":"value_picks"},
])
def test_unverified_or_wrong_day_rollover_does_not_supply_source(scene,change):
    receipt,feed,snapshot,archived=scene
    original=deepcopy(feed["ace_picks"][0])
    feed["ace_picks"]=[]
    source={"confirmed_only":True,"betting_day":DAY,
            "section":"ace_picks","row":original}
    source.update(change)
    snapshot["rollover_issued_rows"]=[source]
    report=bridge.reconcile(DAY,receipt,feed,snapshot,now=NOW)
    assert report["net_new_aces"]==0
    assert report["pending_evidence"]==1
    assert archived==[]
