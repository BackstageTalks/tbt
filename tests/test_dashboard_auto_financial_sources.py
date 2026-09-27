"""Automatic KPI best-window selection and independent winner/Results finance."""
from datetime import datetime, timedelta, timezone

import pytest

from tbt.services.dashboard_kpis import ALLOWED_PERIODS, published_results_metrics, selected_dashboard_cards

NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


def issued(event, section, market, odds, profit, *, days=1,
           correct=True, status="hit", price_status="priced", family=None):
    row = {
        "event_id": event,
        "scheduled_at": (NOW - timedelta(days=days)).isoformat(),
        "market_publications": [{
            "issued_at": (NOW - timedelta(days=days, hours=3)).isoformat(),
            "market": market, "section": section, "odds": odds,
            "price_status": price_status, "selection_id": event,
            "result": {
                "correct": correct, "status": status,
                "staked_units": 1 if price_status in {"priced", "priced_projection"} else 0,
                "profit_units": profit,
            },
        }],
    }
    if family:
        row["prediction_family"] = family
    return row


def sample():
    rows = [
        issued("singles-win", "top_daily", "match_winner", 2.0, 1.0),
        issued("singles-loss", "value", "match_winner", 1.8, -1.0, correct=False),
        issued("doubles-win", "doubles", "match_winner", 3.0, 2.0, family="doubles"),
        issued("ace-win", "ace", "aces", 2.2, 1.2, price_status="priced_projection"),
        issued("unpriced-stats", "games", "games", None, 0, price_status="projection_only"),
        issued("short-odds", "prime", "match_winner", 1.05, .05),
        issued("retired-refund", "top_daily", "match_winner", 1.5, -1.0,
               correct=False, status="retired"),
        issued("old-loss", "value", "match_winner", 2.0, -1.0,
               days=10, correct=False),
    ]
    # Distinct old historical model/betting KPI windows allow direct verification
    # that the automatic best choice is per-metric, not one shared winning day.
    windows = {str(day): {
        "model": {"n": 40, "accuracy": {3:.62, 7:.67, 14:.75, 30:.70, 180:.69, 365:.72}[day]},
        "betting": {
            "overall": {
                "n": day, "staked_units": 4.0, "roi": {3:.50, 7:.40, 14:.30, 30:.20, 180:.10, 365:.05}[day],
                "profit_units": {3:2.0, 7:2.4, 14:3.0, 30:3.5, 180:4.2, 365:5.1}[day],
            },
            "sections": {"top_daily": {
                "n": 5, "avg_odds": {3:1.7, 7:1.75, 14:1.76, 30:1.9, 180:1.85, 365:1.8}[day]
            }},
        },
    } for day in (3,7,14,30,180,365)}
    return {"results": rows, "performance_windows": windows,
            "dashboard_model_success": {"accuracy": .95}}


def cards(*settings):
    return {"dashboard": {"kpi_cards": [
        {"metric": metric, "period": period} for metric,period in settings
    ]}}


def test_winner_roi_yield_differ_from_all_results_and_ignore_refunds():
    feed = sample()
    winner = published_results_metrics(feed, "3", "winners", now=NOW)
    overall = published_results_metrics(feed, "3", "all", now=NOW)
    assert winner["staked_units"] == 2
    assert winner["profit_units"] == 0
    assert winner["roi"] == 0
    assert overall["staked_units"] == 4
    assert overall["profit_units"] == pytest.approx(3.2)
    assert overall["roi"] == pytest.approx(.8)
    assert overall["sample"] > winner["sample"]
    configured = cards(("winner_roi", "3"), ("results_roi", "3"),
                       ("results_yield_units", "3"))
    value = selected_dashboard_cards(feed, configured, now=NOW)
    assert [x["value"] for x in value] == pytest.approx([0, .8, 3.2])
    assert all(set(x) == {"metric", "period", "value"} for x in value)


def test_auto_maximizes_each_metric_instead_of_reusing_model_auto_period():
    feed = sample()
    selected = selected_dashboard_cards(feed, cards(
        ("model_success", "auto"), ("roi", "auto"), ("yield_units", "auto")
    ), now=NOW)
    assert [(x["value"], x["selected_period"]) for x in selected] == [
        (.75, "14"), (.50, "3"), (5.1, "365"),
    ]
    assert [x["sample"] for x in selected] == [40, 3, 365]
    avg = selected_dashboard_cards(feed, cards(
        ("avg_odds", "auto"), ("results_roi", "auto"),
        ("winner_yield_units", "auto")
    ), now=NOW)
    assert avg[0]["value"] == pytest.approx(1.9)
    assert avg[0]["selected_period"] == "30"
    assert avg[1]["value"] == pytest.approx(.8)
    assert avg[1]["selected_period"] in {"3", "7"}
    assert avg[2]["value"] == pytest.approx(0)
    assert avg[2]["selected_period"] in {"3", "7"}


def test_auto_excludes_empty_windows_and_tracks_full_results_period():
    feed = sample()
    feed["results"].append(issued("old-big-win", "value", "match_winner",
                                  10.0, 9.0, days=400))
    values = selected_dashboard_cards(feed, cards(
        ("results_yield_units", "auto"), ("results_success", "auto"),
        ("winner_roi", "365")
    ), now=NOW)
    assert values[0]["selected_period"] == "all"
    assert values[0]["value"] == pytest.approx(11.2)
    assert values[1]["value"] is not None
    assert values[2]["value"] is not None
    assert ALLOWED_PERIODS["results_yield_units"] == {
        "auto", "all", "3", "7", "14", "30", "180", "365"
    }
    no_data = selected_dashboard_cards(
        {"results": [], "performance_windows": {}},
        cards(("winner_roi","auto"),("results_roi","auto"),("avg_odds","auto")),
        now=NOW,
    )
    assert [item["value"] for item in no_data] == [None]*3
    assert all(item["selected_period"] is None for item in no_data)
