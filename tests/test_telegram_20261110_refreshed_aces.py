"""One-shot verified November 10 ESÁ/VIAC ES update protects original receipts."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import telegram_20261110_refreshed_aces as task
import telegram_offer_publisher as tg
import telegram_daily_results as results


NOW="2026-11-10T11:00:00+00:00"
ORIGINAL_SCHEDULE="2026-11-10T15:00:00+00:00"


def state():
    original=[]
    for i in range(8):
        original.append({
            "event_id":f"e{i}", "selection_id":f"s{i}",
            "channel":"aces","market":"aces","section":"ace",
            "publication_key":f"old{i}","market_line":3.5,
            "projection_direction":"over", "odds":1.7,
            "scheduled_at":ORIGINAL_SCHEDULE,
        })
    return {"schema":1, "attempts":{
        task.ORIGINAL_KEY:{
            "status":"sent","message_ids":task.ORIGINAL_IDS,
            "sha256":task.ORIGINAL_SHA,
            "source_feed_generated_at":"2026-11-10T05:01:00+00:00",
            "rows":[*original,
                    {"channel":"top","event_id":"t1","selection_id":"st",
                     "scheduled_at":ORIGINAL_SCHEDULE},
                    {"channel":"top","event_id":"t2","selection_id":"su",
                     "scheduled_at":ORIGINAL_SCHEDULE},
                    {"channel":"value","event_id":"v1","selection_id":"sv",
                     "scheduled_at":ORIGINAL_SCHEDULE},
                    {"channel":"free","event_id":"t1","selection_id":"st",
                     "scheduled_at":ORIGINAL_SCHEDULE}]
        },
        task.ORIGINAL_MORE_KEY:{
            "status":"sent","message_ids":task.ORIGINAL_MORE_IDS,
            "sha256":task.ORIGINAL_MORE_SHA,
            "rows":[{"event_id":f"e{i}","selection_id":f"s{i}"} for i in range(8)],
        },
    }, "reposts":{}}


def candidate(event="new1", tour="ATP", tournament="Main Tour"):
    return {"market":"aces","tour":tour,"tournament":tournament,
            "event_id":event,"selection_id":"S",
            "scheduled_at":"2026-11-10T16:00:00+00:00",
            "aces_superiority_hint":"Ace Player",
            "aces_superiority_player_id":"S",
            "player1":{"id":"S","name":"Ace Player"},
            "player2":{"id":"O","name":"Opponent"}}


def snapshot(rows=None):
    return {"schema":1,"confirmed_only":True,
            "betting_day":task.DAY,"generated_at":"2026-11-10T10:00:00+00:00",
            "source_feed_generated_at":"2026-11-10T09:59:00+00:00",
            "ace_picks":rows if rows is not None else [candidate()]}


def site():
    return {"ok":True,"schema":1,"ready":True,"stale":False,
            "betting_day":task.DAY,"generated_at":"2026-11-10T09:59:00+00:00",
            "visible_counts":{"ace_picks":1},
            "offer_authority_keys":{"aces":["h:new1"]}}


def test_one_shot_new_aces_and_ball_are_from_exact_live_website(tmp_path, monkeypatch):
    initial=state()
    ledger=tmp_path/"ledger.json";tg.save(ledger,initial)
    monkeypatch.setattr(task.tg,"snapshot",lambda *_:snapshot())
    monkeypatch.setattr(task.more,"site_readback",lambda *_:site())
    monkeypatch.setattr(task,"row_authority_key",lambda row,*_:"h:"+row["event_id"])
    monkeypatch.setattr(task.tg,"select_groups",lambda *_:{"aces":[candidate()]})
    monkeypatch.setattr(task.tg,"result_reference",lambda row,*_:{
        "event_id":row["event_id"],"selection_id":row["selection_id"],
        "section":"ace","channel":"aces","market":"aces","publication_key":"fresh",
        "market_line":4.5,"projection_direction":"over",
        "odds":1.70,"scheduled_at":row["scheduled_at"]})
    monkeypatch.setattr(task.more,"offered_rows",lambda *_:[
        {"event_id":"new1","selection_id":"S",
         "scheduled_at":"2026-11-10T16:00:00+00:00","name":"Ace Player"}])
    monkeypatch.setattr(task.tg,"messages",lambda *_:[{"audience":"premium","text":"ACES test"}])
    monkeypatch.setattr(task.more,"render_messages",lambda *_:[{"audience":"premium","text":"VIAC ES test"}])
    args=type("Args",(),dict(state=str(ledger),output=str(tmp_path/"out"),
                             api_url="https://example.org",now=NOW))
    task.prepare(args)
    assert (tmp_path/"out"/"ready").read_text()==task.UPDATE_KEY
    msgs=tg.load(tmp_path/"out"/"messages.json")
    assert len(msgs)==2 and all("AKTUALIZOVANÁ PONUKA" in x["text"] for x in msgs)
    updated=tg.load(tmp_path/"out"/"state.json")
    attempt=updated["attempts"][task.UPDATE_KEY]
    assert attempt["status"]=="reserved" and len(attempt["rows"])==1
    assert attempt["counts"]=={"aces":1,"more_aces":1,"net_new_issued_aces":1}
    assert attempt["paid_provider_requests"]==0 and attempt["cdb_writes"]==0
    assert updated["attempts"][task.ORIGINAL_KEY]==initial["attempts"][task.ORIGINAL_KEY]
    assert updated["attempts"][task.ORIGINAL_MORE_KEY]==initial["attempts"][task.ORIGINAL_MORE_KEY]
    assert tg.load(ledger)==initial
    tg.save(ledger,updated)
    (tmp_path/"out"/"ready").unlink()
    task.prepare(args)
    assert not (tmp_path/"out"/"ready").exists()


def test_excluded_venues_stale_website_and_original_receipts_fail_closed():
    old=state()
    _,old_attempt,original,_=task.checked_original(old)
    altered=deepcopy(old)
    altered["attempts"][task.ORIGINAL_KEY]["sha256"]="changed"
    with pytest.raises(RuntimeError,match="receipts"):
        task.checked_original(altered)
    with pytest.raises(RuntimeError,match="website"):
        task.require_website(snapshot(),{"ok":False},
                             datetime.fromisoformat(NOW),old_attempt)
    with pytest.raises(RuntimeError,match="No newly confirmed"):
        task.require_website({
            **snapshot(),
            "source_feed_generated_at":old_attempt["source_feed_generated_at"]
        },site(),datetime.fromisoformat(NOW),old_attempt)
    assert task.main_tour_aces(candidate("c","ATP","Challenger Open")) is False
    assert task.main_tour_aces(candidate("w","WTA","WTA 125")) is False


def test_new_issued_refs_are_included_in_results_without_erasing_original():
    s=state()
    first=s["attempts"][task.ORIGINAL_KEY]["rows"][0]
    novel={**first,"event_id":"new1","selection_id":"S",
           "publication_key":"fresh"}
    s["attempts"][task.UPDATE_KEY]={"status":"sent","message_ids":[789,790],
                                    "rows":[first,novel]}
    items=results.extract_sent(s,task.DAY)
    identities=[(x["event_id"],x["selection_id"]) for x in items]
    assert identities.count(("e0","s0"))==1
    assert identities.count(("new1","S"))==1
    assert len([x for x in items if x["channel"]=="aces"])==9


def test_explicit_one_shot_trigger_uses_private_ledger_and_production_readback():
    wf=(Path(__file__).resolve().parents[1]/
        ".github/workflows/telegram-20261110-refreshed-aces.yml").read_text()
    assert "group: blinq-telegram-ledger" in wf
    assert "telegram-20261110-refreshed-aces-request.json" in wf
    assert "scripts/telegram_20261110_refreshed_aces.py prepare" in wf
    assert "provider_requests == 0" in wf and "cdb_writes == false" in wf
    assert "git diff-tree" in wf and "scripts/telegram_offer_publisher.py mark-sent" in wf
