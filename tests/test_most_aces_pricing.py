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
    assert "statistical_most_aces_odds(" in tg and "ball_player_id=identity[1]" in tg
    assert "annotate_most_aces_offer(source_feed)" in api
    assert "blinq_user_most_aces_confidence_band_v1" in ui
    assert "verifiedMostAcesApiProOdds" in ui
    assert "Bl inQ" not in ui


def test_owner_local_most_aces_is_frozen_full_value_with_readback():
    from tbt.services.most_aces_pricing import (
        freeze_most_aces_price, verified_frozen_local_most_aces_odds,
        LOCAL_CONTRACT_VERSION,
    )
    from tbt.services.engine import _projection_price_units, _betting_metrics
    original = row()
    frozen = freeze_most_aces_price(original)
    assert original["odds"] is None and original["price_status"] == "projection_only"
    assert frozen["odds"] == 1.59 and frozen["price_status"] == "priced_projection"
    assert frozen["price_basis"] == PRICE_BASIS
    assert frozen["odds_source"] == "blinq_statistical"
    assert frozen["odds_contract_version"] == LOCAL_CONTRACT_VERSION
    assert frozen["provider_id"] is None and frozen["captured_at"] is None
    assert verified_frozen_local_most_aces_odds(frozen) == 1.59
    publication = {**frozen, "section": "ace_winner", "issued_at": "2026-11-08T10:00:00+00:00"}
    assert _projection_price_units(publication, True)["profit_units"] == pytest.approx(0.59)
    assert _projection_price_units(publication, False)["profit_units"] == -1.0
    publication["result"] = {
        "status": "hit", "correct": True, "staked_units": 1.0,
        "return_units": 1.59, "profit_units": 0.59,
    }
    report = _betting_metrics([(frozen, publication)])
    assert report["n"] == 1 and report["staked_units"] == 1.0
    assert report["avg_odds"] == 1.59 and report["roi"] == pytest.approx(0.59)


def test_api_precedes_local_and_old_issued_rows_never_change():
    from tbt.services.most_aces_pricing import (
        freeze_most_aces_price, verified_frozen_local_most_aces_odds,
    )
    priced = row(price_status="priced_projection", odds=1.73, provider_id=1,
                 odds_source="rapidapi", captured_at="2026-11-08T06:00:00+00:00",
                 odds_market_name="Most Aces")
    assert freeze_most_aces_price(priced) == priced
    invalid = row(price_status="priced_projection", odds=2.0,
                  odds_source="mystery", provider_id=8)
    assert freeze_most_aces_price(invalid) == invalid
    signal = row(ace_winner_issued=False,
                 ace_winner_source="issued_aces_signal_only")
    assert freeze_most_aces_price(signal) == signal
    original = row(price_status="projection_only", odds=None)
    original["issued_at"] = "2026-11-07T06:00:00+00:00"
    # Never retroactively price a prior-day published, originally unpriced bet.
    assert freeze_most_aces_price(original) == original
    assert verified_frozen_local_most_aces_odds(original) is None
    tampered = freeze_most_aces_price(row())
    tampered["odds"] = 1.65
    assert verified_frozen_local_most_aces_odds(tampered) is None


def test_live_results_grade_1u_local_quote_and_equal_aces_refund():
    from tbt.services.most_aces_pricing import freeze_most_aces_price
    from tbt.services.match_status import (
        deployed_priced_projection, _grade_runtime_projection,
    )
    base = freeze_most_aces_price(row())
    feed = {"generated_at": "2026-11-08T09:00:00+00:00"}
    published = deployed_priced_projection(base, feed)
    assert published is not None and published["section"] == "ace_winner"
    assert published["odds"] == 1.59 and published["issued_at"] == feed["generated_at"]
    status = {
        "status": "win",
        "provider_home_id": "11", "provider_away_id": "22",
        "projection_stats_p1_id": "11", "projection_stats_p2_id": "22",
        "projection_stats": {"p1_aces": 8, "p2_aces": 3},
    }
    win = _grade_runtime_projection(base, published, status)
    assert win["result"]["status"] == "hit"
    assert win["result"]["staked_units"] == 1.0
    assert win["result"]["profit_units"] == pytest.approx(0.59)
    status["projection_stats"]["p1_aces"] = 1
    loss = _grade_runtime_projection(base, published, status)
    assert loss["result"]["profit_units"] == -1.0
    status["projection_stats"]["p1_aces"] = 3
    tie = _grade_runtime_projection(base, published, status)
    assert tie["result"]["status"] == "void"
    assert tie["result"]["profit_units"] == 0.0
    assert deployed_priced_projection(base, {"generated_at": "2026-11-08T18:00:00+00:00"}) is None


def test_freeze_is_only_for_most_aces_not_aces_over_under():
    from tbt.services.most_aces_pricing import freeze_most_aces_price
    player_total = row("aces", price_contract="player_total_ou",
                       price_status="priced_projection", odds=1.81,
                       ou_side="over", market_line=6.5)
    assert freeze_most_aces_price(player_total) == player_total
    assert freeze_most_aces_price(row()) == freeze_most_aces_price(row())
