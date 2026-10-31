"""Telegram previous betting-day report: offline, read-only and immutable."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import telegram_daily_results as r
import telegram_offer_publisher as tg

NOW=datetime(2026,11,1,6,0,tzinfo=timezone.utc)  # Nov 1, 07:00 in Bratislava
DAY="2026-10-31"

def sent(category="top", event="match-1", odds=1.80, market=None):
    market=market or ("aces" if category=="aces" else "match_winner")
    return {
      "channel":category,
      "event_id":event,
      "section":{"top":"top_daily","value":"value","aces":"ace","free":"top_daily"}[category],
      "market":market,
      "selection_id":"p1",
      "scheduled_at":"2026-10-31T12:30:00+00:00",
      "name":"Test Surname",
      "odds":odds,
      "publication_key":"marketline-4.5" if category=="aces" else "",
      "market_line":4.5 if category=="aces" else None,
      "projection_direction":"over" if category=="aces" else "",
    }

def settled(row, correct=True, void=False, odds=None, price_status="priced_projection"):
    return {k:row.get(k) for k in (
      "event_id","section","market","selection_id","publication_key",
      "market_line","projection_direction",
    )} | {
      "odds":row.get("odds") if odds is None else odds,
      "price_status":price_status,
      "result":{"correct":correct,"void":void,"runtime_source":"match_status_snapshot"},
    }

def test_previous_betting_day_in_bratislava():
    assert r.previous_day(NOW)==DAY
    try:r.previous_day(datetime(2026,11,1,3,0,tzinfo=timezone.utc))
    except RuntimeError:pass
    else:raise AssertionError("Unclosed betting day accepted")

def test_results_format_matches_old_summary_with_pending():
    won=sent()
    lost=sent("value","match-2",2.05)
    pending=sent("aces","match-3",None)
    rows=[won,lost,pending]
    archive=[settled(won,True),settled(lost,False)]
    top=r.report_rows(rows,archive,"top",DAY,tg.FOOTER)
    value=r.report_rows(rows,archive,"value",DAY,tg.FOOTER)
    aces=r.report_rows(rows,archive,"aces",DAY,tg.FOOTER)
    assert "📊 Results | BlinQ TOP" in top["text"]
    assert "BlinQ | Tennis Intelligence" in top["text"]
    assert "📅 31.10.26" in top["text"]
    assert "1️⃣ ✅ Surname | 13:30 | 1.80 | +0.80u" in top["text"]
    assert "✅1 ❌0 ➖0 ⏳0 | +0.80u | ROI +80.0%" in top["text"]
    assert "❌ Surname" in value["text"]
    assert "⏳" in aces["text"] and "Pending" in aces["text"]
    assert "ROI —" in aces["text"]

def test_projection_only_result_works_without_fabricated_roi():
    pick=sent("aces","match-3",None)
    archived=settled(pick,True,price_status="projection_only")
    result=r.evaluate(pick,[archived])
    assert result["status"]=="won" and result["units"] is None and result["stake"]==0
    text=r.report_rows([pick],[archived],"aces",DAY,tg.FOOTER)["text"]
    assert "✅1" in text and "ROI —" in text and "Neocenené projekcie" in text

def test_mismatched_identity_market_line_and_odds_do_not_settle_money():
    pick=sent("aces","match-3",1.80)
    other=settled(pick,True) | {"market_line":6.5}
    assert r.evaluate(pick,[other])["status"]=="pending"
    correct=settled(pick,True,odds=1.95)
    out=r.evaluate(pick,[correct])
    assert out["status"]=="won" and out["units"] is None

def test_free_and_premium_channel_results_separate():
    top=sent()
    free=sent("free")
    assert r.report_rows([top,free],[settled(top,True)],"free",DAY,tg.FOOTER)["audience"]=="free"
    assert r.report_rows([top,free],[settled(top,True)],"top",DAY,tg.FOOTER)["audience"]=="premium"

def test_ledger_requires_confirmed_receipts_and_dedup():
    item=sent()
    state={"attempts":{
      DAY+":schedule:"+DAY:{"status":"sent","message_ids":[11],"rows":[item]},
      DAY+":manual:again":{"status":"sent","message_ids":[15],"rows":[item]},
      DAY+":manual:unsent":{"status":"reserved","rows":[sent("value","match-2")]},
    }}
    extracted=r.extract_sent(state,DAY)
    assert extracted==[item]
    assert r.extract_sent({"attempts":{DAY+":schedule:"+DAY:{"status":"reserved","rows":[item]}}},DAY)==[]

def test_prepare_results_is_idempotently_reserved_without_provider_calls(tmp_path,monkeypatch):
    item=sent()
    state={"schema":1,"attempts":{DAY+":scheduled:"+DAY:{"status":"sent","rows":[item],
                                                  "message_ids":[123],"sent_at":NOW.isoformat()}}}
    path=tmp_path/"state.json";tg.save(path,state)
    monkeypatch.setattr(tg,"config",lambda url:{"enabled":True,"results_enabled":True})
    monkeypatch.setattr(r,"archive",lambda url,day:[settled(item,True)])
    args=SimpleNamespace(now=NOW.isoformat(),config_url="unused",api_url="unused",
                         state=str(path),output=str(tmp_path/"out"),external_tick=True)
    r.prepare(args)
    out=tg.load(tmp_path/"out"/"state.json")
    assert out["attempts"]["results:"+DAY]["status"]=="reserved"
    messages=tg.load(tmp_path/"out"/"messages.json")
    assert len(messages)==1 and "ROI +80.0%" in messages[0]["text"]
    # Once the reservation is committed, repeated cron ticks do not re-post.
    tg.save(path,out)
    (tmp_path/"out"/"ready").unlink()
    r.prepare(args)
    assert not (tmp_path/"out"/"ready").exists()


def test_results_use_aces_label_and_linkable_stat_engine_footer():
    sample=sent("aces","match-aces",None)
    footer=tg.branded_footer("ℹ️ Analytical preview only\n🧠 by BackstageTalks Data Engine")
    text=r.report_rows([sample],[],"aces",DAY,footer)["text"]
    assert "📊 Results | BlinQ ACES" in text
    assert text.endswith("by BlinQ Stat Engine")
    assert tg.telegram_link_entities(text)[0]["url"].endswith("/follow-the-data/")
