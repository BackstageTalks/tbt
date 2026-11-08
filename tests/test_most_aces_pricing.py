"""VIAC ES prices are a user-approved, source-labeled range, not API quotes."""
from copy import deepcopy
from datetime import datetime

import pytest

from tbt.services.most_aces_pricing import (
    MIN_PRICE, MAX_PRICE, PRICE_BASIS,
    annotate_most_aces_offer, statistical_most_aces_odds,
    verified_api_pro_most_aces_odds,
)


def row(market="most_aces", **kwargs):
    base = {
        "event_id": "12345", "market": market,
        "scheduled_at": "2026-11-08T17:00:00+00:00",
        "player1": {"id": "11", "name": "A Player"},
        "player2": {"id": "22", "name": "B Player"},
        "selection_id": "11",
        "aces_superiority_hint": "A Player",
        "projection_model": "ace-count-projection-v4",
        "projection": 7.3, "opponent_projection": 3.1,
        "projection_confidence": 0.78,
        "price_contract": "player_superiority",
        "price_status": "projection_only",
        "odds": None, "ou_side": None, "market_line": None,
    }
    base.update(kwargs)
    return base


@pytest.mark.parametrize(("confidence", "expected"), [
    (0.60, 1.70), (0.78, 1.59), (0.93, 1.50),
])
def test_approved_own_statistics_range_from_frozen_confidence(confidence, expected):
    price = statistical_most_aces_odds(row(projection_confidence=confidence))
    assert price == expected and MIN_PRICE <= price <= MAX_PRICE


def test_ball_identity_not_over_under_selected_player():
    over_under = row("aces", selection_id="22", price_contract="player_total_ou",
                     price_status="priced_projection", odds=1.85, market_line=6.5,
                     ou_side="over")
    assert statistical_most_aces_odds(over_under) is None
    assert statistical_most_aces_odds(over_under, ball_player_id="11") == 1.59
    assert statistical_most_aces_odds(over_under, ball_player_id="invalid") is None


@pytest.mark.parametrize("changes", [
    {"market": "aces"},
    {"price_contract": "player_total_ou"},
    {"price_status": "priced_projection", "odds": 1.61},
    {"odds": 1.60},
    {"projection_model": "other"},
    {"selection_id": "no-player"},
    {"projection": 2.0, "opponent_projection": 5.0},
    {"projection_confidence": .59},
    {"projection_confidence": .94},
    {"projection_confidence": float("nan")},
    {"scheduled_at": "2026-11-08T17:00:00"},
    {"event_id": ""},
    {"player2": {"id": "11", "name": "Same ID"}},
])
def test_no_fake_quote_on_unqualified_or_api_priced_contract(changes):
    assert statistical_most_aces_odds(row(**changes)) is None


def test_only_new_current_offer_is_decorated_never_results_or_source():
    yes = row()
    no = row("aces", price_contract="player_total_ou",
             selection_id="22", market_line=5.5, ou_side="over",
             odds=1.65, price_status="priced_projection")
    priced = row(event_id="777",price_status="priced_projection",
                 odds=1.66,provider_id=1,odds_source="rapidapi",
                 captured_at="2026-11-08T06:00:00+00:00")
    derived = row(event_id="333",ace_winner_issued=False,
                  ace_winner_source="issued_aces_signal_only")
    history = [{"event_id": "old", "market_publications": [
        {"market": "most_aces", "odds": None, "issued_at": "2026-11-07T07:00:00Z"}]}]
    feed = {"ace_picks": [yes, no, priced, derived], "results": history}
    before = deepcopy(feed)
    out = annotate_most_aces_offer(feed)
    assert feed == before
    assert out["results"] is history
    assert out["ace_picks"][0]["statistical_more_aces_odds"] == 1.59
    assert out["ace_picks"][0]["statistical_more_aces_price_basis"] == PRICE_BASIS
    assert out["ace_picks"][0]["odds"] is None
    assert "statistical_more_aces_odds" not in out["ace_picks"][1]
    assert "statistical_more_aces_odds" not in out["ace_picks"][2]
    assert out["ace_picks"][2]["odds"] == 1.66
    assert out["ace_picks"][3]["statistical_more_aces_odds"] == 1.59
    assert out["ace_picks"][3]["ace_winner_issued"] is False


def test_api_pro_real_most_aces_quote_wins_but_ou_never_qualifies():
    offered=row(price_status="priced_projection",odds=1.62,provider_id=1,
                odds_source="rapidapi", captured_at="2026-11-08T06:00:00+00:00",
                odds_market_name="Most Aces")
    assert verified_api_pro_most_aces_odds(offered) == 1.62
    assert statistical_most_aces_odds(offered) is None
    for change in (
        {"odds_market_name":"Player Aces Total"},
        {"odds_market_name":"Most Aces First Set"},
        {"odds_source":"propline"},
        {"provider_id":2},
        {"captured_at":"2026-11-08T18:00:00+00:00"},
        {"selection_id":"unknown"},
    ):
        assert verified_api_pro_most_aces_odds({**offered, **change}) is None


def test_not_backfilled_and_not_added_to_results_roi():
    old = {"market": "most_aces", "event_id": "old", "odds": None,
           "price_status": "projection_only"}
    feed = {"results": [{"market_publications": [old]}], "ace_picks": []}
    assert annotate_most_aces_offer(feed)["results"][0]["market_publications"][0] is old


def test_api_and_telegram_utility_use_same_source():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    tg=(root/"scripts/telegram_more_aces.py").read_text()
    api=(root/"api/function_app.py").read_text()
    ui=(root/"web/app.js").read_text()
    assert "statistical_most_aces_odds(row, ball_player_id=identity[1])" in tg
    assert "annotate_most_aces_offer(source_feed)" in api
    assert "blinq_user_most_aces_confidence_band_v1" in ui
    assert "verifiedMostAcesApiProOdds" in ui
    assert "Bl inQ" not in ui
