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

def test_free_aces_settlement_gates_results_but_never_inflates_elite_roi(tmp_path,monkeypatch,capsys):
    top=sent("top","match-top")
    free_top=sent("free","match-top")
    free_aces=sent("aces","match-aces")
    free_aces["channel"]="free"  # exact second FREE selection, still an ACE contract
    state={"schema":1,"attempts":{DAY+":daily:0620":{
        "status":"sent","message_ids":[701,702],"rows":[top,free_top,free_aces]}}}
    path=tmp_path/"state.json";tg.save(path,state)
    monkeypatch.setattr(tg,"config",lambda *_:{"enabled":True,"results_enabled":True})
    monkeypatch.setattr(r,"website_results",lambda *_:[])
    archival=[settled(top,True)]
    monkeypatch.setattr(r,"archive",lambda *_:list(archival))
    args=SimpleNamespace(now=NOW.isoformat(),config_url="unused",api_url="unused",
                         state=str(path),output=str(tmp_path/"result"),external_tick=False)
    assert len(r.extract_sent(state,DAY))==3
    r.prepare(args)
    assert "issued_picks_not_all_settled" in capsys.readouterr().out
    assert not (tmp_path/"result"/"ready").exists()
    archival.append(settled(free_aces,False))
    r.prepare(args)
    assert (tmp_path/"result"/"ready").exists()
    out=tg.load(tmp_path/"result"/"messages.json")
    assert len(out)==1 and out[0]["audience"]=="elite"
    assert "ROI +80.0%" in out[0]["text"]  # count TOP once, exclude both FREE rows


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
    # This test exercises the pending gate, with no same-contract website row.
    monkeypatch.setattr(r,"website_results",lambda *_:[])
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
    assert ("✅ WIN 2 | ❌ LOSS 1\n"
            "🟪 VOID 1 | ⏳ PENDING 1\n"
            "🎯 Úspešnosť 66.7%\n"
            "💰 Zisk +0.60u | 📈 ROI +20.0%") in message
    assert "📊 Denný súhrn" not in message
    assert "TOP · WIN" not in message
    assert "VALUE · WIN" not in message
    assert "ACES · WIN" not in message
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
    assert body.count(" | 1.80 | +0.80u ✅")==len(samples)
    assert "WIN 149" in posts[-1]["text"]
    assert sum(item["counts"]["won"] for item in posts)==149
    assert "ROI +80.0%" in posts[-1]["text"]

def test_elite_preview_is_clearly_synthetic_and_uses_the_real_formatter():
    from telegram_elite_results_preview import preview
    text=preview()
    assert "🧪 TEST – simulované výsledky, nie skutočné vyhodnotenie" in text
    assert "🅃 Hanfmann | 1.66 | +0.66u ✅" in text
    assert "🄰 Zverev | 2.00 | -1.00u ❌" in text
    assert "🟪 VOID" in text and "⏳" in text
    assert "Zisk +0.16u" in text and "ROI +2.3%" in text
    assert "ℹ️ Analytical preview by BlinQ Stat Engine" in text
    assert tg.telegram_link_entities(text)[0]["url"]==tg.BRAND_URL


def test_current_damm_junior_result_name_is_preserved():
    sample=sent("top","damm-20261101")
    sample["name"]="Martin Damm Jr."
    combined=r.combined_daily_report([sample],[],DAY,tg.branded_footer())
    assert combined and "🅃 Damm junior |" in combined[0]["text"]
    legacy=r.report_rows([sample],[],"top",DAY,tg.branded_footer())
    assert "Damm junior |" in legacy["text"]
    assert sample["name"]=="Martin Damm Jr."
    assert r.evaluate(sample,[])["status"]=="pending"



def test_confirmed_ou_reissue_supersedes_legacy_aces_without_double_count():
    legacy=sent("aces","event-old")
    replacement=sent("aces","event-new")
    replacement.update(market_line=7.5,projection_direction="over",
                       publication_key="ace:player-total:over:7.5")
    top=sent("top","top-original")
    original={"status":"sent","rows":[top,legacy],"message_ids":[725,726]}
    update={"status":"sent","rows":[top,replacement],"message_ids":[727,728],
            "supersedes_daily":True}
    state={"attempts":{DAY+":daily:0620":original},
           "reposts":{DAY+":repost:aces-player-ou-20261102-v1":update}}
    active=r.extract_sent(state,DAY)
    assert [item["event_id"] for item in active]==["top-original","event-new"]
    assert legacy not in active
    assert original["rows"]==[top,legacy]  # immutable original audit
    state["reposts"][DAY+":repost:aces-player-ou-20261102-v1"]["status"]="reserved"
    assert r.extract_sent(state,DAY)==[top,legacy]



def test_historical_recovery_guard_does_not_expand_ordinary_worker_window():
    historic="2026-11-03"
    now=datetime(2026,11,7,12,tzinfo=timezone.utc)
    row={**sent("aces","nov3-a"),"scheduled_at":"2026-11-03T12:30:00+00:00"}
    ledger={"attempts":{historic+":daily:0620":{
        "status":"sent","message_ids":[730,731],
        "sent_at":"2026-11-03T05:33:27+00:00",
        "rows":[{**row,"event_id":str(i)} for i in range(9)] +
               [{**sent("top",str(i)),"scheduled_at":"2026-11-03T12:30:00+00:00"}
                for i in range(9,11)] +
               [{**sent("value","11"),"scheduled_at":"2026-11-03T12:30:00+00:00"}] +
               [{**sent("free","9"),"scheduled_at":"2026-11-03T12:30:00+00:00"}],
    }}}
    assert r.unreported_day(ledger,now) is None
    assert r.approved_historical_results_day(ledger,historic)==historic
    for invalid in ("2026-11-02","2026-11-04",""):
        if not invalid:
            continue
        import pytest
        with pytest.raises(RuntimeError,match="Unapproved"):
            r.approved_historical_results_day(ledger,invalid)
    ledger["attempts"]["results:"+historic]={"status":"reserved"}
    assert r.approved_historical_results_day(ledger,historic) is None
    del ledger["attempts"]["results:"+historic]
    ledger["attempts"][historic+":daily:0620"]["message_ids"]=[99,100]
    import pytest
    with pytest.raises(RuntimeError,match="immutable"):
        r.approved_historical_results_day(ledger,historic)


def test_nov3_send_from_durable_archive_only_preserves_issued_quotes(tmp_path,monkeypatch):
    import pytest
    historic="2026-11-03"
    now="2026-11-07T12:00:00+00:00"
    first=[{**sent("top","t1",1.75),"scheduled_at":"2026-11-03T12:30:00+00:00"},
           {**sent("top","t2",1.85),"scheduled_at":"2026-11-03T12:30:00+00:00"},
           {**sent("value","v1",2.05),"scheduled_at":"2026-11-03T12:30:00+00:00"}]
    aces=[{**sent("aces","a"+str(i),1.70),"scheduled_at":"2026-11-03T12:30:00+00:00"}
          for i in range(9)]
    free={**first[0],"channel":"free"}
    premium=first+aces
    rows=premium+[free]
    grades=[True,False,False,True,True,True,True,True,False,False,False,None]
    archived=[settled(ref,correct=grade,void=grade is None)
              for ref,grade in zip(premium,grades)]
    ledger={"schema":1,"attempts":{historic+":daily:0620":{
        "status":"sent","message_ids":[730,731],
        "sent_at":"2026-11-03T05:33:27+00:00","rows":rows}}}
    state_path=tmp_path/"ledger.json"
    tg.save(state_path,ledger)
    monkeypatch.setattr(tg,"config",lambda *_:{"enabled":False,"results_enabled":False})
    calls=[]
    def archived_readback(url,day):
        calls.append(day)
        return archived
    monkeypatch.setattr(r,"archive",archived_readback)
    args=SimpleNamespace(now=now,config_url="unused",api_url="unused",
                         state=str(state_path),output=str(tmp_path/"send"),
                         elite_auto=True,historical_day=historic)
    assert r.unreported_day(ledger,datetime.fromisoformat(now)) is None
    r.prepare(args)
    result=tg.load(tmp_path/"send"/"state.json")
    assert result["attempts"]["results:"+historic]["counts"]=={
        "won":6,"lost":5,"void":1,"pending":0}
    assert result["attempts"]["results:"+historic]["reserved_at"]==now
    assert calls==[historic]
    assert tg.load(state_path)==ledger
    assert [x["odds"] for x in rows]==[x["odds"] for x in premium]+[free["odds"]]
    assert (tmp_path/"send"/"ready").is_file()
    # Any mismatched outcome is fail-closed; it cannot reserve an altered score.
    archived[0]=settled(premium[0],correct=False)
    args.output=str(tmp_path/"disagree")
    with pytest.raises(RuntimeError,match="scorecard differs"):
        r.prepare(args)
    assert not (tmp_path/"disagree"/"ready").exists()
    tg.save(state_path,result)
    args.output=str(tmp_path/"repeat")
    r.prepare(args)
    assert not (tmp_path/"repeat"/"ready").exists()

def test_site_exact_source_recovers_original_aces_without_repricing(tmp_path,monkeypatch,capsys):
    """A website result with identical frozen O/U is safe for TG reporting."""
    now=datetime(2026,11,7,21,46,tzinfo=timezone.utc)
    row={**sent("aces","match-30",1.67),
         "scheduled_at":"2026-11-07T15:00:00+00:00",
         "publication_key":"local-aces-ou-v1:match-30:p1:over:4.5",
         "price_basis":tg.PRICE_BASIS}
    state={"schema":1,"attempts":{"2026-11-07:daily:0620":{
        "status":"sent","message_ids":[740,741],
        "sent_at":"2026-11-07T06:54:00+00:00","rows":[row]}}}
    state_path=tmp_path/"state.json"
    tg.save(state_path,state)
    site=[{**settled(row,True,odds=1.79),
           "scheduled_at":row["scheduled_at"],
           "result":{"correct":True,"void":False,
                     "actual_count":8,
                     "runtime_source":"match_status_snapshot"}}]
    monkeypatch.setattr(tg,"config",lambda *_:{"enabled":True,"results_enabled":True})
    monkeypatch.setattr(r,"archive",lambda *_:[])
    monkeypatch.setattr(r,"website_results",lambda *_:site)
    args=SimpleNamespace(now=now.isoformat(),config_url="unused",
                         api_url="unused",state=str(state_path),
                         output=str(tmp_path/"out"),elite_auto=True,historical_day="")
    r.prepare(args)
    result=tg.load(tmp_path/"out"/"state.json")
    assert result["attempts"]["results:2026-11-07"]["status"]=="reserved"
    assert result["attempts"]["results:2026-11-07"]["counts"]=={
        "won":1,"lost":0,"void":0,"pending":0}
    # Website's different price must NEVER replace the issued quote or
    # generate monetary returns from a different quote.
    text=tg.load(tmp_path/"out"/"messages.json")[0]["text"]
    assert "1.67" in text and "1.79" not in text
    assert "ROI" in text
    assert "exact_fallbacks" in capsys.readouterr().out


def test_site_fallback_rejects_wrong_contract_or_unverified_grade():
    ace=sent("aces","match-3",1.68)
    source={**settled(ace,True), "scheduled_at":ace["scheduled_at"]}
    for change in ({"market_line":6.5},
                   {"projection_direction":"under"},
                   {"publication_key":"other"},
                   {"selection_id":"opponent"},
                   {"market":"match_winner"},
                   {"scheduled_at":"2026-10-31T13:40:00+00:00"},
                   {"result":{"correct":True,"void":False,
                              "runtime_source":"model_prediction"}}):
        candidate={**source,**change}
        merged,count=r.exact_website_fallback([ace],[],[candidate])
        assert count==0 and r.evaluate(ace,merged)["status"]=="pending"


def test_site_fallback_never_overwrites_conflicting_verified_archive():
    row=sent("aces","match-1",1.64)
    archived=settled(row,False)|{"scheduled_at":row["scheduled_at"]}
    site=settled(row,True)|{"scheduled_at":row["scheduled_at"]}
    import pytest
    with pytest.raises(RuntimeError,match="conflict"):
        r.exact_website_fallback([row],[archived],[site])


def test_site_fallback_prioritizes_archive_and_deduplicates_free_mirror():
    top=sent("top","m-1",1.85)
    free=sent("free","m-1",1.85)
    receipt=settled(top,True)|{"scheduled_at":top["scheduled_at"]}
    merged,recovered=r.exact_website_fallback([top,free],[receipt],[receipt])
    assert recovered==0 and len(merged)==1
    assert r.evaluate(top,merged)["status"]=="won"
    assert r.evaluate(free,merged)["status"]=="won"


def test_nov9_postponed_only_the_explicit_missing_original_aces_contract(tmp_path,monkeypatch):
    day="2026-11-09"
    start="2026-11-09T12:00:00+00:00"
    top=sent("top","17516947",1.719424)
    top.update(selection_id="300293",publication_key="top_daily:match_winner:2026-11-09:17516947:300293",scheduled_at=start)
    value=sent("value","17520307",1.819672)
    value.update(selection_id="195414",publication_key="value:match_winner:2026-11-09:17520307:195414",scheduled_at=start)
    def ace(event,selection,side,line,odds):
        item=sent("aces",event,odds)
        item.update(selection_id=selection,scheduled_at=start,market_line=line,
                    projection_direction=side,
                    publication_key=f"local-aces-ou-v1:{event}:{selection}:{side}:{line:.1f}")
        return item
    wright=ace("17520979","484870","over",3.5,1.8)
    wright["name"]="Michael Wright"
    gojo=ace("17520223","124916","over",7.5,1.62)
    mena=ace("17516100","38180","over",2.5,1.7)
    free=sent("free","17516947",1.719424)
    free.update(selection_id="300293",publication_key=top["publication_key"],scheduled_at=start)
    issued=[top,value,wright,gojo,mena,free]
    state={"schema":1,"attempts":{day+":daily:0620":{
        "status":"sent","message_ids":[749,750],
        "sha256":"72c17bc8125a7b270351d81b5884f6a16af321acc941ef332a7c675435035b41",
        "rows":issued}}}
    path=tmp_path/"ledger.json";tg.save(path,state)
    monkeypatch.setattr(tg,"config",lambda *_:{"enabled":False,"results_enabled":False})
    archived=[settled(top,True),settled(value,False),
              settled(gojo,True),settled(mena,True)]
    monkeypatch.setattr(r,"archive",lambda *_:archived)
    monkeypatch.setattr(r,"website_results",lambda *_:[])
    args=SimpleNamespace(now="2026-11-10T08:00:00+00:00",
                         config_url="none",api_url="none",
                         state=str(path),output=str(tmp_path/"report"),
                         elite_auto=True,historical_day="2026-11-09",
                         postpone_unverifiable_20261109=True)
    r.prepare(args)
    posted=tg.load(tmp_path/"report"/"messages.json")
    assert len(posted)==1 and posted[0]["audience"]=="elite"
    message=posted[0]["text"]
    assert "Wright" in message and "POSTPONED" in message
    assert "WIN 3" in message and "LOSS 1" in message
    assert "POSTPONED 1" in message and "PENDING 0" in message
    reserved=tg.load(tmp_path/"report"/"state.json")["attempts"]["results:"+day]
    assert reserved["status"]=="reserved"
    assert reserved["counts"]=={"won":3,"lost":1,"void":0,"pending":0,"postponed":1}
    assert tg.load(path)==state  # not a direct archive or ledger mutation
    # A second run may never create a second send reservation.
    tg.save(path,tg.load(tmp_path/"report"/"state.json"))
    (tmp_path/"report"/"ready").unlink()
    r.prepare(args)
    assert not (tmp_path/"report"/"ready").exists()
