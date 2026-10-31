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
    assert messages[0]["audience"]=="elite"
    assert "🆓 FREE" not in messages[0]["text"]
    # Once the reservation is committed, repeated cron ticks do not re-post.
    tg.save(path,out)
    (tmp_path/"out"/"ready").unlink()
    r.prepare(args)
    assert not (tmp_path/"out"/"ready").exists()




def test_settle_current_day_immediately_after_last_result_without_waiting_for_0600(tmp_path,monkeypatch,capsys):
    # 31 Oct 19:00 Bratislava: result is eligible the same evening.
    now=datetime(2026,10,31,18,0,tzinfo=timezone.utc)
    rows=[sent("top","top-1"),sent("value","value-1"),sent("aces","aces-1"),
          sent("free","top-1")]
    state={"schema":1,"attempts":{DAY+":daily:0620":{
        "status":"sent","rows":rows,"message_ids":[701,702]}}}
    path=tmp_path/"ledger.json";tg.save(path,state)
    monkeypatch.setattr(tg,"config",lambda *_:{"enabled":True,"results_enabled":True})
    available=[settled(rows[0],True),settled(rows[1],False)]
    calls=[]
    def get_archive(url,day):
        calls.append(day)
        return list(available)
    monkeypatch.setattr(r,"archive",get_archive)
    args=SimpleNamespace(now=now.isoformat(),config_url="none",api_url="none",
                         state=str(path),output=str(tmp_path/"out"),external_tick=False)
    # First reconciliation sees only two settled market decisions: no TG send.
    r.prepare(args)
    waiting=capsys.readouterr().out
    assert "issued_picks_not_all_settled" in waiting
    assert not (tmp_path/"out"/"ready").exists()
    assert tg.load(path)==state  # no premature reservation, ledger unchanged
    # Final match finished, but Aces stats are still pending: still no send.
    available.append(settled(rows[2],True,price_status="projection_only"))
    r.prepare(args)
    out=capsys.readouterr().out
    assert "reserved" in out
    assert (tmp_path/"out"/"ready").exists()
    posted=tg.load(tmp_path/"out"/"messages.json")
    assert len(posted)==1 and posted[0]["audience"]=="elite"
    assert "ROI" in posted[0]["text"] and "⏳ PENDING" in posted[0]["text"]
    assert "PENDING 0" in posted[0]["text"]
    assert all(x==DAY for x in calls)
    # Newly reserved result cannot be published a second time.
    tg.save(path,tg.load(tmp_path/"out"/"state.json"))
    (tmp_path/"out"/"ready").unlink()
    r.prepare(args)
    assert not (tmp_path/"out"/"ready").exists()


def test_current_day_prefers_unsettled_yesterday_only_when_published(tmp_path,monkeypatch):
    today="2026-11-01"
    now=datetime(2026,11,1,8,0,tzinfo=timezone.utc)  # after 06:00 local
    old=sent()
    current=dict(old,event_id="new-1",scheduled_at="2026-11-01T09:30:00+00:00")
    ledger={"attempts":{
      DAY+":daily:0620":{"status":"sent","message_ids":[1],"rows":[old]},
      today+":daily:0620":{"status":"sent","message_ids":[2],"rows":[current]}}}
    assert r.unreported_day(ledger,now)==DAY
    ledger["attempts"]["results:"+DAY]={"status":"sent","message_ids":[3]}
    assert r.unreported_day(ledger,now)==today
    ledger["attempts"]["results:"+today]={"status":"reserved"}
    assert r.unreported_day(ledger,now) is None


def test_missing_provider_result_never_grades_pending_as_loss():
    samples=[sent("top","a"),sent("aces","b")]
    first=settled(samples[0],False)
    assert not r.all_settled(samples,[first])
    assert r.evaluate(samples[1],[first])["status"]=="pending"
    assert r.all_settled(samples,[first,settled(samples[1],True)])


def test_explicit_elite_automation_ignores_legacy_disabled_admin_switches(tmp_path,monkeypatch):
    target=sent()
    state={"schema":1,"attempts":{DAY+":daily:0620":{
        "status":"sent","rows":[target],"message_ids":[717]}}}
    path=tmp_path/"state.json"
    tg.save(path,state)
    monkeypatch.setattr(tg,"config",lambda *_:{"enabled":False,"results_enabled":False})
    monkeypatch.setattr(r,"archive",lambda *_:[settled(target,True)])
    args=SimpleNamespace(now=NOW.isoformat(),config_url="unused",api_url="unused",
                         state=str(path),output=str(tmp_path/"old"),external_tick=False)
    r.prepare(args)
    assert not (tmp_path/"old"/"ready").exists()
    args.elite_auto=True
    args.output=str(tmp_path/"elite")
    r.prepare(args)
    assert (tmp_path/"elite"/"ready").is_file()
    messages=tg.load(tmp_path/"elite"/"messages.json")
    assert len(messages)==1 and messages[0]["audience"]=="elite"
    assert "ROI +80.0%" in messages[0]["text"]

def test_results_use_aces_label_and_linkable_stat_engine_footer():
    sample=sent("aces","match-aces",None)
    footer=tg.branded_footer("ℹ️ Analytical preview only\n🧠 by BackstageTalks Data Engine")
    text=r.report_rows([sample],[],"aces",DAY,footer)["text"]
    assert "📊 Results | BlinQ ACES" in text
    assert text.endswith("by BlinQ Stat Engine")
    assert tg.telegram_link_entities(text)[0]["url"].endswith("/follow-the-data/")



def test_combined_scorecard_daily_win_loss_void_pending_and_roi():
    win=sent("top","winner-1",1.80)
    loss=sent("value","loser-1",2.05)
    void=sent("top","void-1",1.65)
    pending=sent("aces","pending-1",None)
    aces_win=sent("aces","aces-winner-1",1.80)
    archived=[settled(win,True),settled(loss,False),settled(void,True,void=True),
              settled(aces_win,True)]
    posts=r.combined_daily_report([win,void,loss,pending,aces_win],archived,DAY,
                                   tg.branded_footer())
    assert len(posts)==1
    out=posts[0]
    assert out["audience"]=="premium"
    assert out["counts"]=={"won":2,"lost":1,"void":1,"pending":1}
    assert out["priced_decisions"]==3
    assert abs(out["profit_units"]-0.6)<1e-9
    message=out["text"]
    assert message.count("📅")==0  # date lives inside the Results title
    assert "WIN 2 | ❌ LOSS 1 | 🟪 VOID 1 | ⏳ PENDING 1" in message
    assert "Úspešnosť 66.7%" in message
    assert "Zisk +0.60u" in message
    assert "ROI +20.0%" in message
    assert "TOP · WIN 1 | LOSS 0 | VOID 1" in message
    assert "VALUE · WIN 0 | LOSS 1" in message
    assert "ACES · WIN 1 | LOSS 0 | VOID 0 | PENDING 1" in message
    assert "by BlinQ Stat Engine" in message
    assert tg.telegram_link_entities(message)[0]["url"] == tg.BRAND_URL
    assert "🅃 Surname | 1.80 | +0.80u ✅" in message
    assert "🅅 Surname | 2.05 | -1.00u ❌" in message
    assert "🅃 Surname | 1.65 | +0.00u 🟪 VOID" in message
    assert "🄰 Surname | — | — ⏳" in message
    assert "🄰 Surname | 1.80 | +0.80u ✅" in message
    assert all(icon not in message for icon in tg.NUMBER_EMOJIS)
    assert "13:30" not in message  # no match time in compact ELITE results




def test_elite_seven_picks_with_postponed_and_purple_void_are_not_fabricated():
    names=("Hanfmann","Virtanen","Gray","Hijikata","Fritz","Medvedev","Zverev")
    sections=("top","top","top","value","aces","aces","aces")
    prices=(1.66,1.67,1.67,1.83,2.00,2.00,2.00)
    rows=[]
    for i,(name,section,price) in enumerate(zip(names,sections,prices),1):
        entry=sent(section,f"fixture-{i}",price)
        entry["name"]=name
        rows.append(entry)
    archive_rows=[settled(row,correct=outcome) for row,outcome in zip(rows,(True,True,False,True,False,True,False))]
    report=r.combined_daily_report(rows,archive_rows,DAY,tg.branded_footer())
    assert len(report)==1
    body=report[0]["text"]
    expected=(
        "🅃 Hanfmann | 1.66 | +0.66u ✅",
        "🅃 Virtanen | 1.67 | +0.67u ✅",
        "🅃 Gray | 1.67 | -1.00u ❌",
        "🅅 Hijikata | 1.83 | +0.83u ✅",
        "🄰 Fritz | 2.00 | -1.00u ❌",
        "🄰 Medvedev | 2.00 | +1.00u ✅",
        "🄰 Zverev | 2.00 | -1.00u ❌",
    )
    assert all(entry in body for entry in expected)
    assert all(body.index(first)<body.index(second) for first,second in zip(expected,expected[1:]))
    assert report[0]["counts"]=={"won":4,"lost":3,"void":0,"pending":0}
    assert "Zisk +0.16u" in body and "ROI +2.3%" in body
    assert tg.telegram_link_entities(body)[0]["url"]==tg.BRAND_URL

    # Explicit verified VOID is neutral for units/ROI, not an invented loss.
    void_rows=list(archive_rows)
    void_rows[4]=settled(rows[4],void=True,correct=None)
    void_post=r.combined_daily_report(rows,void_rows,DAY,tg.branded_footer())[0]
    assert "🄰 Fritz | 2.00 | +0.00u 🟪 VOID" in void_post["text"]
    assert void_post["counts"]=={"won":4,"lost":2,"void":1,"pending":0}
    assert void_post["priced_decisions"]==6

    # A postponed match has no verified settlement: remain pending/hourglass.
    # Automatic ELITE delivery must wait; it cannot infer a VOID from a delay.
    postponed=list(void_rows[:-1])
    waiting=r.combined_daily_report(rows,postponed,DAY,tg.branded_footer())[0]
    assert "🄰 Zverev | 2.00 | — ⏳" in waiting["text"]
    assert waiting["counts"]=={"won":4,"lost":1,"void":1,"pending":1}
    assert not r.all_settled(rows,postponed)


def test_result_count_does_not_double_count_free_pick():
    top=sent("top","same-event",1.8)
    free=sent("free","same-event",1.8)
    posts=r.combined_daily_report([top,free],[settled(top,True)],DAY,tg.branded_footer())
    assert len(posts)==1
    assert posts[0]["counts"]["won"]==1
    assert posts[0]["profit_units"]==.8


def test_all_issued_results_are_preserved_when_telegram_message_spills():
    samples=[sent("top","match-"+str(i),1.8) for i in range(1,150)]
    for ix, entry in enumerate(samples):
        entry["name"]="Player Surname"+str(ix+1)
    archive_rows=[settled(sample,True) for sample in samples]
    posts=r.combined_daily_report(samples,archive_rows,DAY,tg.branded_footer())
    assert len(posts)>1
    assert all(len(item["text"].encode("utf-16-le"))//2<=4096 for item in posts)
    body="\n".join(item["text"] for item in posts)
    assert body.count("Surname | 1.80 | +0.80u ✅")==len(samples)
    assert "WIN 149" in posts[-1]["text"]
    assert sum(item["counts"]["won"] for item in posts)==149
    assert "ROI +80.0%" in posts[-1]["text"]
