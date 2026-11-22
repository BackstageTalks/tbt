"""TOP-only 60% / 30% policy regressions; all provider calls are mocks."""
from datetime import datetime, timezone

from test_market_selection import _OddsProvider, row
from tbt.services.entitlements import _daily_rows
from tbt.services.market_selection import enrich_current_betting_day_odds, select_market_sections


def test_top_30pct_depth_with_adjusted_model_at_least_60pct():
    good = row("top-030", .84, 1.60, 2.60, depth=.30, surface1=5, surface2=5)
    low_model = row("top-p599", .832, 1.60, 2.60, depth=.30, surface1=5, surface2=5)
    low_depth = row("top-029", .99, 1.60, 2.60, depth=.29, surface1=5, surface2=5)
    low_surface = row("top-surface4", .99, 1.60, 2.60, depth=.30, surface1=4, surface2=5)
    low_quote = row("top-odds149", .99, 1.49, 2.60, depth=.30, surface1=5, surface2=5)
    result = select_market_sections([good, low_model, low_depth, low_surface, low_quote])
    assert [p["event_id"] for p in result["top_daily_picks"]] == ["top-030"]
    assert result["top_daily_picks"][0]["probability"] > .60
    assert result["top_daily_picks"][0]["selection_tier"] == "sports_0.60"
    assert [p["event_id"] for p in _daily_rows(result)] == ["top-030"]
    assert result["market_selection"]["selection_counts"]["top_daily_shortfall"] == 2
    counts = result["market_selection"]["top_rejection_counts"]
    assert counts["probability_below_fixed_floor"] >= 1
    assert counts["insufficient_data_depth"] >= 1
    assert counts["insufficient_surface_history"] >= 1
    assert counts["missing_or_low_odds"] >= 1


def test_value_and_acca_stay_at_50pct_data_depth():
    rows = [
        row("top-only-shallow", .90, 1.90, 2.00, depth=.30, surface1=5, surface2=5),
        row("value-050", .90, 1.90, 2.00, depth=.50, surface1=5, surface2=5),
        row("acca-030", .90, 1.30, 3.10, depth=.30, surface1=5, surface2=5),
        row("acca-050", .90, 1.30, 3.10, depth=.50, surface1=5, surface2=5),
    ]
    result = select_market_sections(rows)
    assert {r["event_id"] for r in result["top_daily_picks"]} == {"top-only-shallow"}
    assert [r["event_id"] for r in result["value_picks"]] == ["value-050"]
    assert [r["event_id"] for r in result["prime_picks"]] == ["acca-050"]
    meta = result["market_selection"]
    assert meta["prime_rule"]["min_data_depth"] == .50
    assert meta["value_rule"]["min_data_depth"] == .50
    assert meta["top_daily_rule"]["min_data_depth"] == .30


def test_top_only_quote_discovery_respects_competition_surface_and_prestart():
    valid = row("valid-top", .86, 1.60, 2.60, depth=.30, surface1=5, surface2=5)
    itf = row("itf-unapproved", .86, 1.60, 2.60, depth=.30, surface1=5, surface2=5)
    itf["competition"] = "ITF Men"
    insufficient_surface = row("surface4", .86, 1.60, 2.60, depth=.30, surface1=4, surface2=5)
    insufficient_depth = row("depth29", .90, 1.60, 2.60, depth=.29, surface1=5, surface2=5)
    for card in (valid, itf, insufficient_surface, insufficient_depth):
        card.pop("betting")
        card.pop("match_winner_market")
    provider = _OddsProvider()
    _, report = enrich_current_betting_day_odds(
        provider, [valid, itf, insufficient_surface, insufficient_depth],
        now=datetime(2026, 9, 7, 8, tzinfo=timezone.utc))
    assert provider.called == [("valid-top", 1)]
    assert report["candidate_gate"]["top_only_lane"]["approved_competitions_only"] is True
    assert report["provider_call_attempts"] == 1


def test_historical_v25_publications_keep_65pct_serving_floor():
    def item(name, probability):
        return {"event_id": name, "odds": 1.60, "blinq_probability": probability,
                "scheduled_at": "2026-09-07T12:00:00+00:00"}
    old = {"top_daily_picks": [item("low", .61), item("old", .66)],
           "value_picks": [],
           "market_selection": {"top_daily_rule": {"policy": "sports_tiered_top5_65_v25"}}}
    new = {**old, "market_selection": {"top_daily_rule": {"policy": "sports_tiered_top5_60_v26"}}}
    assert [x["event_id"] for x in _daily_rows(old)] == ["old"]
    assert [x["event_id"] for x in _daily_rows(new)] == ["low", "old"]
