"""Separate Most Aces TG message mirrors the website tennis-ball indicator."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import telegram_more_aces as more
import telegram_offer_publisher as tg

NOW = datetime(2026,11,8,6,30,tzinfo=timezone.utc)  # 07:30 Bratislava
SCHEDULED = "2026-11-08T15:00:00+00:00"
GENERATED = "2026-11-08T05:10:00+00:00"
CONFIRMED_AT = "2026-11-08T06:20:00+00:00"


def row(*, hint="Alice Smith", hint_id="p1", selected="p2", event="fixture1", start=SCHEDULED):
    return {"market":"aces","event_id":event,"scheduled_at":start,"tour":"ATP",
            "player1":{"id":"p1","name":"Alice Smith"},
            "player2":{"id":"p2","name":"Bob Jones"},
            "aces_superiority_hint":hint,"aces_superiority_player_id":hint_id,
            "selection_id":selected,"price_contract":"player_total_ou",
            "market_line":4.5,"ou_side":"over","odds":1.76,
            "projection_model":"ace-count-projection-v4",
            "projection":6.2,"opponent_projection":3.1,
            "projection_confidence":0.78}


def snapshot(rows=None):
    return {"schema":1,"confirmed_only":True,"betting_day":"2026-11-08",
            "generated_at":CONFIRMED_AT,
            "source_feed_generated_at":GENERATED,
            "ace_picks":[row()] if rows is None else rows}


def site():
    return {"ok":True,"schema":1,"ready":True,"stale":False,
            "betting_day":"2026-11-08","generated_at":GENERATED,
            "visible_counts":{"ace_picks":3}}


def test_website_ball_player_wins_over_opposite_ou_selection():
    # The underlying O/U chosen player can be completely different!
    r=row()
    assert r["selection_id"]=="p2"
    assert more.ball_player(r)==r["player1"]


def test_only_actual_ball_hint_and_no_ambiguous_player():
    assert more.ball_player(row(hint="",hint_id="")) is None
    assert more.ball_player(row(hint="Unrelated",hint_id="")) is None
    assert more.ball_player(row(hint="Bob Jones",hint_id="p1")) is None
    assert more.ball_player(row(hint="Alice Smith",hint_id="p2")) is None
    assert more.ball_player(row() | {"market":"double_faults"}) is None
    assert more.ball_player(row(hint="Álice Smith",hint_id="p1"))["id"]=="p1"


def test_future_betting_day_only_and_same_day():
    rows=[row(event="future"),row(event="past",start="2026-11-08T05:00:00+00:00"),
          row(event="next",start="2026-11-09T03:00:00+00:00")]
    selected=more.offered_rows(snapshot(rows),NOW)
    assert len(selected)==1
    assert selected[0]["selection_id"]=="p1"
    assert selected[0]["name"]=="Alice Smith"


def test_duplicate_ball_identity_fails_closed():
    with pytest.raises(ValueError,match="Duplicate"):
        more.offered_rows(snapshot([row(),row()]),NOW)


@pytest.mark.parametrize("change",[
    {"betting_day":"2026-11-07"},
    {"confirmed_only":False},
    {"generated_at":"2026-11-07T05:10:00+00:00"},
    {"generated_at":"2026-11-08T07:00:00+00:00"},
])
def test_reject_stale_or_unconfirmed_source(change):
    with pytest.raises(ValueError):
        more.offered_rows({**snapshot(),**change},NOW)


@pytest.mark.parametrize("change",[
    {"stale":True},{"ready":False},{"ok":False},
    {"generated_at":"2026-11-08T05:15:00+00:00"},
    {"betting_day":"2026-11-07"},
    {"visible_counts":{"ace_picks":0}},
    {"visible_counts":{"ace_picks":"3"}},
])
def test_reject_website_source_conflicts(change):
    picked=more.offered_rows(snapshot(),NOW)
    with pytest.raises(ValueError):
        more.verify_same_website(snapshot(),{**site(),**change},picked,NOW)


def test_reject_website_parity_without_original_serving_generation():
    picked=more.offered_rows(snapshot(),NOW)
    with pytest.raises(ValueError):
        more.verify_same_website(
            {k:v for k,v in snapshot().items() if k!="source_feed_generated_at"},
            site(),picked,NOW)
    with pytest.raises(ValueError):
        more.verify_same_website(
            {**snapshot(),"source_feed_generated_at":"2026-11-08T05:11:00+00:00"},
            site(),picked,NOW)


def test_same_format_but_only_selected_name_no_bookmaker_ou():
    picked=more.offered_rows(snapshot(),NOW)
    msgs=more.render_messages(picked,NOW,tg.FOOTER)
    assert len(msgs)==1 and msgs[0]["audience"]=="premium"
    message=msgs[0]["text"]
    assert tg.HEADER in message and "08.11.2026" in message
    assert "🎾 VIAC ES" in message
    assert "🎾 | Smith | 16:00 | viac ES | 78.0% | BlinQ štat. kurz 1.59" in message
    assert picked[0]["statistical_more_aces_odds"] == 1.59
    assert picked[0]["statistical_more_aces_price_basis"] == "blinq_user_most_aces_confidence_band_v1"
    assert "Bob" not in message and "Jones" not in message
    assert "4.5" not in message and "1.76" not in message
    assert tg.BRAND_FOOTER in message
    assert "by BlinQ Stat Engine" in message


def test_exact_api_pro_winner_quote_precedes_local_and_never_uses_ou():
    ball=row()
    provider={**row(), "market":"most_aces", "selection_id":"p1",
              "price_contract":"player_superiority", "price_status":"priced_projection",
              "odds_source":"rapidapi", "provider_id":1,
              "captured_at":"2026-11-08T05:30:00+00:00",
              "odds_market_name":"Most Aces", "odds":1.66}
    picked=more.offered_rows(snapshot([ball,provider]),NOW)
    assert len(picked)==1
    assert picked[0]["api_pro_most_aces_odds"]==1.66
    assert picked[0]["statistical_more_aces_odds"] is None
    msg=more.render_messages(picked,NOW,tg.FOOTER)[0]["text"]
    assert "API Pro kurz 1.66" in msg
    assert "BlinQ štat. kurz" not in msg
    assert "1.76" not in msg

    # Another player or another O/U bookmaker contract cannot override the ball.
    provider["selection_id"]="p2"
    picked=more.offered_rows(snapshot([ball,provider]),NOW)
    assert picked[0]["api_pro_most_aces_odds"] is None
    assert picked[0]["statistical_more_aces_odds"]==1.59
    provider["selection_id"]="p1"
    provider["odds_market_name"]="Player Aces Total"
    picked=more.offered_rows(snapshot([ball,provider]),NOW)
    assert picked[0]["api_pro_most_aces_odds"] is None
    assert picked[0]["statistical_more_aces_odds"]==1.59


def test_telegram_reuses_frozen_full_value_odds_not_repriced_ball():
    from tbt.services.most_aces_pricing import freeze_most_aces_price
    ball = row()
    ball["projection_confidence"] = .62  # independently derived ESÁ signal price differs
    independent = {**row(), "market": "most_aces", "selection_id": "p1",
                   "price_contract": "player_superiority",
                   "price_status": "projection_only",
                   "market_line": None, "ou_side": None, "odds": None}
    issued = freeze_most_aces_price(independent)
    assert issued["odds"] == 1.59
    selected = more.offered_rows(snapshot([ball, issued]), NOW)
    assert selected[0]["statistical_more_aces_odds"] == 1.59
    assert "kurz 1.59" in more.render_messages(selected, NOW, tg.FOOTER)[0]["text"]

    # An explicitly claimed frozen local quote must not be replaced with a
    # different, freshly recomputed price after source tampering.
    corrupted = {**issued, "odds": 1.65}
    selected = more.offered_rows(snapshot([ball, corrupted]), NOW)
    assert selected[0]["statistical_more_aces_odds"] is None
    assert "BlinQ štat. kurz" not in more.render_messages(selected, NOW, tg.FOOTER)[0]["text"]


def test_bad_source_fails_closed_without_reusing_over_under_price():
    malformed=row()
    malformed["projection_model"]="unknown"
    picked=more.offered_rows(snapshot([malformed]),NOW)
    assert picked[0]["statistical_more_aces_odds"] is None
    assert "1.76" not in more.render_messages(picked,NOW,tg.FOOTER)[0]["text"]
    assert "štat. kurz" not in more.render_messages(picked,NOW,tg.FOOTER)[0]["text"]


def test_prepare_requires_regular_daily_receipt_and_keeps_private_ledger(tmp_path,monkeypatch):
    state_file=tmp_path/"state.json"
    tg.save(state_file,{"schema":1,"attempts":{
        "2026-11-08:daily:0620":{"status":"sent","message_ids":[760],
                                  "sent_at":NOW.isoformat(),
                                  "rows":[{"event_id":"existing"}]}}})
    monkeypatch.setattr(tg,"snapshot",lambda *_:snapshot())
    monkeypatch.setattr(more,"site_readback",lambda *_:site())
    args=SimpleNamespace(now=NOW.isoformat(),state=str(state_file),
                         output=str(tmp_path/"out"),api_url="https://example.com")
    more.prepare(args)
    state=tg.load(tmp_path/"out"/"state.json")
    assert state["attempts"]["more-aces:2026-11-08"]["status"]=="reserved"
    assert state["attempts"]["more-aces:2026-11-08"]["source"]=="website_aces_superiority_ball_v1"
    assert state["attempts"]["2026-11-08:daily:0620"]["rows"]==[{"event_id":"existing"}]
    assert (tmp_path/"out"/"ready").read_text()=="more-aces:2026-11-08"
    tg.save(state_file,state)
    (tmp_path/"out"/"ready").unlink()
    more.prepare(args)
    assert not (tmp_path/"out"/"ready").exists()


def test_no_send_without_confirmed_daily_or_no_future_website_ball(tmp_path,monkeypatch):
    state_file=tmp_path/"state.json"
    tg.save(state_file,{"schema":1,"attempts":{}})
    monkeypatch.setattr(tg,"snapshot",lambda *_:snapshot([]))
    monkeypatch.setattr(more,"site_readback",lambda *_:site())
    args=SimpleNamespace(now=NOW.isoformat(),state=str(state_file),
                         output=str(tmp_path/"out"),api_url="https://example.com")
    more.prepare(args)
    assert not (tmp_path/"out"/"ready").exists()
    source=tg.load(state_file)
    source["attempts"]["2026-11-08:daily:0620"]={
        "status":"sent","sent_at":NOW.isoformat(),"message_ids":[762]}
    tg.save(state_file,source)
    more.prepare(args)
    assert not (tmp_path/"out"/"ready").exists()


def test_workflow_wires_only_existing_telegram_sender_and_ledger():
    root=Path(__file__).resolve().parents[1]
    job=(root/".github/workflows/telegram-more-aces.yml").read_text()
    daily=(root/".github/workflows/telegram-daily-offer.yml").read_text()
    assert "blinq-telegram-ledger" in job
    assert "telegram_more_aces.py prepare" in job
    assert "telegram_offer_publisher.py send" in job
    assert "telegram_offer_publisher.py mark-sent" in job
    assert "telegram-bot-state" in job and "ls-remote" in job
    assert "telegram-more-aces.yml" in daily
    assert "RAPIDAPI_KEY" not in job and "CDB" not in job
    assert 'group: blinq-telegram-ledger' in job


def test_more_aces_rejects_off_tour_balls_but_keeps_atp_wta():
    rows=[
        row(event="atp")|{"tour":"ATP"},
        row(event="wta")|{"tour":"WTA"},
        row(event="itf")|{"tour":"ITF"},
        row(event="challenger")|{"tour":"Challenger"},
        row(event="wta125")|{"tour":"WTA 125"},
        row(event="unknown")|{"tour":None},
    ]
    result=more.offered_rows(snapshot(rows),NOW)
    assert [r["event_id"] for r in result]==["atp","wta"]
