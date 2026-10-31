"""Offline contract tests for the BlinQ Telegram publisher."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import importlib.util
import json
import hashlib
import os
import sys
import types

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/telegram_offer_publisher.py"
spec = importlib.util.spec_from_file_location("blinq_telegram_offer", SCRIPT)
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)

NOW = datetime(2026, 10, 31, 7, 0, tzinfo=timezone.utc)  # 08:00 Bratislava


def row(identifier, player="A", category="top"):
    start = (NOW + timedelta(hours=4)).isoformat()
    data = dict(event_id=str(identifier), scheduled_at=start,
                player1={"id": "p1", "name": player},
                player2={"id": "p2", "name": "B"},
                winner_id="p1", betting={"selection_id": "p1", "odds": 1.8,
                                           "blinq_probability": 0.7, "expected_value": 0.25})
    if category == "aces":
        data.update(market="aces", projection=8.3, opponent_projection=5.4,
                    projection_confidence=0.72)
        del data["betting"]
        data["selection_id"] = "p1"
    return data


def settings(**kwargs):
    c = dict(enabled=True, sections={"top": True, "value": True, "aces": True},
             schedule={"enabled": True, "time": "08:00", "weekdays": list(range(7))},
             max_per_section=7, layout="combined", free_top_pick=True,
             show_probability=True, show_odds=True)
    return dict(c, **kwargs)


def offer():
    return dict(confirmed_only=True, betting_day="2026-10-31",
                generated_at=NOW.isoformat(),
                top_daily_picks=[row(i, f"Player Surname{i}") for i in range(1, 6)],
                value_picks=[row(42, "Value")],
                ace_picks=[row(51, "Server", "aces"), row(52, "DF", "aces") | {"market": "double_faults"}])



def test_telegram_omits_ev_everywhere_including_value_and_full_daily_message():
    cfg=settings()
    top=tg.fmt(row(88,"Sinner"),"top",cfg,index=1)
    value=tg.fmt(row(89,"Hijikata"),"value",cfg,index=4)
    value_long=tg.fmt(row(90,"Alexander ExtraordinaryLongSurname"),"value",cfg,index=5)
    assert top.endswith(" | 1.80")
    assert value.endswith(" | 1.80")
    assert value_long.endswith(" | 1.80")
    assert all("EV" not in line for line in (top,value,value_long))
    assert all("\n" not in line for line in (top,value,value_long))
    combined=tg.messages(offer(),cfg,NOW)
    assert len(combined)==2
    assert all("EV" not in message["text"] for message in combined)
    assert "6️⃣ Value" in combined[0]["text"]


def test_aces_prediction_contracts_and_mobile_compaction():
    cfg=settings()
    count=row(90,"Daniil Medvedev","aces")
    count.update(price_status="projection_only")
    unpriced=tg.fmt(count,"aces",cfg,index=6)
    assert "Medvedev | " in unpriced
    assert "najviac es" in unpriced
    assert "aces 8.3" not in unpriced
    assert unpriced.endswith(" | 0" ) is False

    superiority=dict(count, price_contract="player_superiority",price_status="priced_projection",
                     odds=2.0)
    priced=tg.fmt(superiority,"aces",cfg,index=6)
    assert "najviac es | 2.00" in priced
    assert "72.0%" not in priced  # the optional confidence was dropped to fit mobile
    assert len(priced)<=44

    over=dict(count,price_contract="player_total_ou",price_status="priced_projection",
              market_line=8.5,ou_side="over",model_probability=0.65,odds=1.9)
    text=tg.fmt(over,"aces",cfg,index=2)
    assert "Over 8.5 es" in text
    assert "8.3" not in text
    assert "72.0%" not in text  # model O/U probability differs from most-aces confidence
    assert "EV" not in text
    bad=dict(over)
    bad.pop("market_line")
    try:
        tg.fmt(bad,"aces",cfg)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid O/U contract rendered as valid pick")


def test_daily_queue_is_durable_idempotent_and_full_offer_override(tmp_path, monkeypatch):
    from types import SimpleNamespace
    state_path=tmp_path/"state.json"
    args=SimpleNamespace(now=NOW.isoformat(),state=str(state_path))
    tg.queue_daily(args)
    queued=tg.load(state_path)
    ident=tg._daily_id(NOW)
    assert queued["attempts"][ident]["status"]=="queued"
    tg.queue_daily(args)
    assert tg.load(state_path)==queued

    disabled=settings()
    disabled.update(enabled=False,max_per_section=1,layout="separate",
                    sections={"top":False,"value":False,"aces":False},
                    free_top_pick=False)
    monkeypatch.setattr(tg,"config",lambda *_:disabled)
    monkeypatch.setattr(tg,"snapshot",lambda *_:offer())
    out=tmp_path/"prepared"
    tg.prepare(SimpleNamespace(now=NOW.isoformat(),state=str(state_path),
                               output=str(out),config_url="https://unit.invalid/api/v1/ui-config",
                               daily=True))
    msgs=tg.load(out/"messages.json")
    assert [x["audience"] for x in msgs]==["premium","free"]
    premium=msgs[0]["text"]
    assert premium.index("1️⃣ Surname1")<premium.index("6️⃣ Value")<premium.index("7️⃣ Server")
    assert "🆓" in msgs[1]["text"]
    result=tg.load(out/"state.json")
    assert result["attempts"][ident]["status"]=="reserved"
    assert len(result["attempts"][ident]["rows"])==8
    tg.queue_daily(SimpleNamespace(now=NOW.isoformat(),state=str(out/"state.json")))
    assert tg.load(out/"state.json")["attempts"][ident]["status"]=="reserved"

def test_one_time_format_reissue_preserves_exact_previous_picks_and_dedup(tmp_path, monkeypatch):
    from types import SimpleNamespace
    confirmed=offer()
    cfg=settings(enabled=False)
    base_messages=tg.messages(confirmed,settings(),NOW)
    original=[]
    for section,items in (("top",confirmed["top_daily_picks"]),
                          ("value",confirmed["value_picks"]),
                          ("aces",[confirmed["ace_picks"][0]])):
        original.extend(tg.result_reference(row,section) for row in items)
    free_id=base_messages[1]["free_event_id"]
    free_row=next(row for row in confirmed["top_daily_picks"] if row["event_id"]==free_id)
    original.append(tg.result_reference(free_row,"free"))
    sent_id=tg._daily_id(NOW)
    prior={"status":"sent","message_ids":[702,703],"rows":original}
    state={"schema":1,"attempts":{sent_id:prior},"free_picks":{tg.day(NOW):free_id}}
    state_file=tmp_path/"private.json"
    tg.save(state_file,state)
    monkeypatch.setattr(tg,"config",lambda *_:cfg)
    monkeypatch.setattr(tg,"snapshot",lambda *_:confirmed)
    args=SimpleNamespace(now=NOW.isoformat(),state=str(state_file),
                         output=str(tmp_path/"repost"),config_url="https://unit.invalid/api/v1/ui-config",
                         daily=False,preview_format=True)
    tg.prepare(args)
    rendered=tg.load(tmp_path/"repost"/"messages.json")
    assert [m["audience"] for m in rendered]==["premium","free"]
    assert all("EV" not in m["text"] for m in rendered)
    assert "najviac es" in rendered[0]["text"]
    staged=tg.load(tmp_path/"repost"/"state.json")
    assert staged["attempts"][sent_id]==prior
    repost_id=tg.day(NOW)+":repost:format-v2-no-ev"
    assert staged["reposts"][repost_id]["status"]=="reserved"
    assert staged["reposts"][repost_id]["rows"]==[]
    tg.save(tmp_path/"repost"/"receipt.json",[704,705])
    tg.mark_sent(SimpleNamespace(output=str(tmp_path/"repost")))
    sent=tg.load(tmp_path/"repost"/"state.json")
    assert sent["reposts"][repost_id]["message_ids"]==[704,705]
    assert sent["reposts"][repost_id]["status"]=="sent"
    assert sent["attempts"][sent_id]==prior
    args.state=str(tmp_path/"repost"/"state.json")
    args.output=str(tmp_path/"repeat")
    tg.prepare(args)
    assert not (tmp_path/"repeat"/"ready").exists()


def test_classic_format_and_deterministic_free_pick():
    first = tg.messages(offer(), settings(), NOW)
    second = tg.messages(offer(), settings(), NOW)
    assert first == second
    assert [x["audience"] for x in first] == ["premium", "free"]
    assert first[0]["text"].startswith("🎾 BlinQ | Tennis Intelligence")
    assert "Data Betting" not in first[0]["text"]
    assert "1️⃣ Surname1 | " in first[0]["text"]
    assert " | " in first[0]["text"]
    assert "🎾 TOP Picks | BlinQ" not in first[0]["text"]
    assert "💎 VALUE Picks | BlinQ" not in first[0]["text"]
    assert "🎯 ESÁ | BlinQ" not in first[0]["text"]
    premium = first[0]["text"]
    assert premium.index("1️⃣ Surname1") < premium.index("5️⃣ Surname5")
    assert premium.index("5️⃣ Surname5") < premium.index("6️⃣ Value")
    assert premium.index("6️⃣ Value") < premium.index("7️⃣ Server")
    assert premium.count("📅") == 1
    assert "🆓 Surname" in first[1]["text"]
    assert first[1]["text"].count("🆓") == 1
    assert "najviac es" in first[0]["text"]
    assert "aces 8.3" not in first[0]["text"]
    assert "esá" not in first[0]["text"]
    assert "Double Fault" not in first[0]["text"]
    assert all("Analytical preview only" in x["text"] for x in first)
    assert all(x["text"].endswith("by BlinQ Stat Engine") for x in first)
    assert all(tg.telegram_link_entities(x["text"]) for x in first)


def test_free_only_does_not_show_other_premium_rows():
    cfg = settings(sections={"top": False, "value": False, "aces": False})
    messages = tg.messages(offer(), cfg, NOW)
    assert len(messages) == 1 and messages[0]["audience"] == "free"
    assert "🎾 TOP Picks" not in messages[0]["text"]
    assert "VALUE Picks" not in messages[0]["text"]


def test_stale_unconfirmed_and_started_are_blocked():
    stale = offer()
    stale["betting_day"] = "2026-10-30"
    try:
        tg.messages(stale, settings(), NOW)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Stale snapshot accepted")
    expired = offer()
    expired["top_daily_picks"][0]["scheduled_at"] = (NOW - timedelta(minutes=1)).isoformat()
    m = tg.messages(expired, settings(sections={"top": True, "value": False, "aces": False}, free_top_pick=False), NOW)
    assert "Surname1" not in m[0]["text"]


def test_due_window_and_manual_request():
    cfg = settings()
    assert tg.due(cfg, NOW) == "schedule:2026-10-31"
    assert tg.due(cfg, NOW + timedelta(hours=2)) is None
    cfg["schedule"]["enabled"] = False
    cfg["manual_request"] = {"id": "abcdef123456", "created_at": NOW.isoformat()}
    assert tg.due(cfg, NOW) == "manual:abcdef123456"
    assert tg.due(cfg, NOW + timedelta(minutes=91)) is None


def test_scheduled_2330_survives_midnight_betting_day():
    now = datetime(2026, 10, 31, 22, 30, tzinfo=timezone.utc)
    cfg = settings()
    cfg["schedule"]["time"] = "23:30"
    cfg["schedule"]["weekdays"] = [5]  # Saturday Oct 31
    assert tg.due(cfg, now) == "schedule:2026-10-31"


def test_snapshot_checksum_guard(tmp_path, monkeypatch):
    d = tmp_path
    snap = offer()
    def fake_run(args, **kwargs):
        return None
    monkeypatch.setattr(tg.subprocess, "run", fake_run)
    # The manifest is fetched first, then the snapshot. Fake both in advance.
    raw = json.dumps(snap).encode()
    (d / "daily_offer_snapshot.json").write_bytes(raw)
    (d / "_tbt_bundle_manifest.json").write_text(json.dumps({"files": {"daily_offer_snapshot.json": {
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}}}))
    assert tg.snapshot(d)["confirmed_only"] is True
    snap["confirmed_only"] = False
    (d / "daily_offer_snapshot.json").write_text(json.dumps(snap))
    try:
        tg.snapshot(d)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Unconfirmed offer accepted")


def test_telegram_routes_free_to_optional_free_chat(monkeypatch, tmp_path):
    monkeypatch.setenv("TGB", "fake-secret")
    monkeypatch.setenv("TGCH", "-100111")
    monkeypatch.setenv("TGCH_FREE", "-100222")
    tmp_path.joinpath("ready").write_text("reservation")
    tg.save(tmp_path / "messages.json", [
        {"audience": "premium", "text": "VIP"},
        {"audience": "free", "text": "FREE"}])
    seen = []
    outgoing = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, *_): return b'{"ok":true,"result":{"message_id":123}}'
    def fake_open(req, **kwargs):
        values = tg.urllib.parse.parse_qs(req.data.decode())
        seen.append(values["chat_id"][0])
        outgoing.append(values)
        return Response()
    monkeypatch.setattr(tg.urllib.request, "urlopen", fake_open)
    tg.send(types.SimpleNamespace(output=str(tmp_path)))
    assert seen == ["-100111", "-100222"]
    assert all("entities" not in x for x in outgoing)  # legacy unbranded messages still work

def test_compact_separate_mode_order_without_category_headings():
    out = tg.messages(offer(), settings(layout="separate", free_top_pick=False), NOW)
    assert len(out) == 3
    for message,pick in zip(out,("Surname1","Value","Server")):
        assert message["audience"] == "premium"
        assert "1️⃣ " + pick in message["text"]
        assert "🎾 TOP Picks" not in message["text"]
        assert "💎 VALUE Picks" not in message["text"]
        assert "🎯 ESÁ" not in message["text"]


def test_telegram_footer_text_link_is_clickable_and_utf16_safe():
    # Telegram offsets are UTF-16 code units (emojis are surrogate pairs).
    body = "🎾 BlinQ | Tennis Intelligence\n1️⃣ Test\n" + tg.branded_footer(
        "ℹ️ Analytical preview only\n🧠 by BackstageTalks Data Engine")
    assert body.endswith("ℹ️ Analytical preview only\nby BlinQ Stat Engine")
    entities = tg.telegram_link_entities(body)
    assert len(entities) == 1
    link = entities[0]
    assert link["url"] == "https://agreeable-sky-011a7fe10.7.azurestaticapps.net/follow-the-data/"
    encoded = body.encode("utf-16-le")
    start = link["offset"] * 2
    end = (link["offset"] + link["length"]) * 2
    assert encoded[start:end].decode("utf-16-le") == "BlinQ Stat Engine"


def test_telegram_send_post_contains_real_link_entities(monkeypatch, tmp_path):
    monkeypatch.setenv("TGB", "test-secret")
    monkeypatch.setenv("TGCH", "-100111")
    (tmp_path / "ready").write_text("reservation")
    tg.save(tmp_path / "messages.json", [
        {"audience": "premium", "text": "🎾\n" + tg.branded_footer()}])
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, *_): return b'{"ok":true,"result":{"message_id":700}}'
    def fake_open(req, **kwargs):
        seen.append(tg.urllib.parse.parse_qs(req.data.decode()))
        return Response()
    monkeypatch.setattr(tg.urllib.request, "urlopen", fake_open)
    tg.send(types.SimpleNamespace(output=str(tmp_path)))
    assert len(seen) == 1
    posted_entities = json.loads(seen[0]["entities"][0])
    assert posted_entities == tg.telegram_link_entities(seen[0]["text"][0])
    assert "parse_mode" not in seen[0]  # untrusted players never parsed as HTML



def test_full_offer_has_no_hidden_top_value_aces_cap_and_paginate():
    sample=offer()
    sample["top_daily_picks"]=[row(i,f"Top Surname{i}") for i in range(1,75)]
    sample["value_picks"]=[row(100+i,f"Value Person{i}") for i in range(1,27)]
    sample["ace_picks"]=[row(200+i,f"Aces Server{i}","aces") for i in range(1,28)]
    cfg=settings(max_per_section=0,free_top_pick=False)
    out=tg.messages(sample,cfg,NOW)
    assert len(out)>=2
    assert all(item["audience"]=="premium" for item in out)
    assert all(len(item["text"].encode("utf-16-le"))//2<=4096 for item in out)
    lines="\n".join(x["text"] for x in out)
    for ident in ("Surname1 |", "Surname74 |", "Person1 |", "Person26 |", "Server1 |", "Server27 |"):
        assert lines.count(ident)==1
    assert lines.index("Surname74 |")<lines.index("Person1 |")<lines.index("Server1 |")
    assert lines.count("📅") == len(out)


def test_full_offer_reserves_every_exact_publication_for_daily_results(tmp_path, monkeypatch):
    from types import SimpleNamespace
    sample=offer()
    sample["top_daily_picks"]=[row(i,f"Top Player{i}") for i in range(1,18)]
    sample["value_picks"]=[row(100+i,f"Value Person{i}") for i in range(1,6)]
    sample["ace_picks"]=[row(200+i,f"Aces Server{i}","aces") for i in range(1,4)]
    cfg=settings(max_per_section=0,free_top_pick=False)
    cfg["schedule"]["enabled"]=False
    cfg["manual_request"]={"id":"fullsend001","created_at":NOW.isoformat()}
    monkeypatch.setattr(tg,"config",lambda *_: cfg)
    monkeypatch.setattr(tg,"snapshot",lambda *_:sample)
    out=tmp_path/"out"
    tg.prepare(SimpleNamespace(now=NOW.isoformat(),state=str(tmp_path/"state.json"),
                               output=str(out),config_url="https://test.invalid/api/v1/ui-config"))
    state=tg.load(out/"state.json")
    attempts=list(state["attempts"].values())
    assert len(attempts)==1
    selected=attempts[0]["rows"]
    assert len(selected)==25
    assert [sum(x["channel"]==section for x in selected) for section in ("top","value","aces")]==[17,5,3]
    assert len(tg.load(out/"messages.json"))>=1
