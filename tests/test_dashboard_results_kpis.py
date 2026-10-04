"""Dashboard Results KPI scalars use the exact public Results W/L and real quote sample."""
from datetime import datetime, timedelta, timezone

import pytest

from tbt.services.dashboard_kpis import (
    ALLOWED_PERIODS, published_results_metrics, selected_dashboard_cards,
)
from tbt.services.admin_storage import validate_ui_config
from copy import deepcopy
import json
from pathlib import Path

NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)

def test_auto_kpi_uses_latest_runtime_results_not_pre_overlay_sample():
    from tbt.services.match_status import runtime_settled_results
    loss=row('old','top_daily','match_winner',False,2,'priced',days=1)
    current={"event_id":"new","scheduled_at":NOW.isoformat(),"winner_id":"a","player1":{"id":"a","name":"A"},"player2":{"id":"b","name":"B"},"odds":2,"betting":{"selection_id":"a","market":"match_winner","odds":2}}
    feed={"results":[loss],"top_daily_picks":[current]}
    config={"dashboard":{"kpi_cards":[{"metric":"today_picks","period":"today"},{"metric":"results_success","period":"auto"},{"metric":"avg_odds","period":"today"}]}}
    assert selected_dashboard_cards(feed,config,now=NOW)[1]['value']==0
    feed['results']=runtime_settled_results(feed,{'new':{'status':'win','checked_at':NOW.isoformat()}})
    value=selected_dashboard_cards(feed,config,now=NOW)[1]
    assert value['value']==.5 and value['sample']==2

def test_dashboard_counts_runtime_settlements_and_top200_like_results():
    runtime = {"event_id":"runtime", "market_publications":[{"section":"top_daily", "market":"match_winner", "selection_id":"a", "result":{"correct":True,"runtime_source":"match_status_snapshot"}}]}
    top = {"event_id":"top", "market_publications":[{"section":"top200", "market":"match_winner", "selection_id":"b", "issued_at":"2026-09-20T12:00:00Z", "result":{"correct":False}}]}
    unissued = {"event_id":"draft", "market_publications":[{"section":"top_daily", "selection_id":"c", "result":{"correct":True}}]}
    feed={"results":[runtime,top,unissued]}
    stats=published_results_metrics(feed,"all",now=NOW)
    assert (stats["sample"],stats["wins"],stats["losses"])==(2,1,1)
    cards=selected_dashboard_cards(feed,{"dashboard":{"kpi_cards":[{"metric":"today_picks","period":"today"},{"metric":"results_success","period":"auto"},{"metric":"avg_odds","period":"today"}]}},now=NOW)
    assert cards[1]["value"]==.5 and cards[1]["sample"]==2
ROOT = Path(__file__).resolve().parents[1]


def row(event, section, market, correct, odds, status, *, days=1,
        result_status="hit", selection=None):
    scheduled = NOW - timedelta(days=days)
    return {
        "event_id": event,
        "scheduled_at": scheduled.isoformat(),
        "market_publications": [{
            "issued_at": (scheduled - timedelta(hours=6)).isoformat(),
            "section": section, "market": market,
            "selection_id": selection or f"pick-{event}",
            "price_status": status, "odds": odds,
            "result": {"correct": correct, "status": result_status,
                       "staked_units": 1, "profit_units": -1 if not correct else .8},
        }],
    }


def sample_feed():
    rows = [
        row("top-win", "top_daily", "match_winner", True, 1.8, "priced"),
        row("value-loss", "value", "match_winner", False, 2.1, "priced"),
        row("prime-win", "prime", "match_winner", True, 1.06, "priced"),
        # All these projections affect the Results record even without a quote.
        row("ace", "ace", "aces", True, None, "projection_only"),
        row("df", "double_faults", "double_faults", False, None, "projection_only"),
        row("sets", "sets", "sets", True, 1.92, "priced_projection"),
        row("games", "games", "games", True, None, "projection_only"),
        row("doubles", "doubles", "match_winner", False, 2.4, "priced"),
        # A stale False result on a refunded retirement never counts as a loss.
        row("retired", "top_daily", "match_winner", False, 2.0, "priced",
            result_status="retired"),
        # A TOP publication repeated in Short Odds and SEE ALL is one all-category bet.
        row("top-win", "prime", "match_winner", True, 1.8, "priced"),
        # Older than three days, but within the seven-day and all-time windows.
        row("old-top-loss", "top_daily", "match_winner", False, 2.0, "priced", days=5),
    ]
    # Make duplicate issued later so the original TOP record wins all-category dedupe.
    rows[9]["market_publications"][0]["issued_at"] = NOW.isoformat()
    return {
        "results": rows,
        "performance_windows": {"3": {"betting": {"overall": {
            "hit_rate": .99, "avg_odds": 99, "staked_units": 100,
        }}}},
    }


def test_all_results_include_unpriced_stats_and_refunds_are_neutral():
    feed = sample_feed()
    three = published_results_metrics(feed, "3", now=NOW)
    assert (three["wins"], three["losses"], three["sample"]) == (5, 3, 8)
    assert three["hit_rate"] == 5 / 8
    assert three["odds_sample"] == 5
    assert three["avg_odds"] == pytest.approx(1.856)
    top = published_results_metrics(feed, "3", "top_daily", now=NOW)
    assert (top["wins"], top["losses"], top["sample"]) == (1, 0, 1)
    assert top["hit_rate"] == 1
    seven = published_results_metrics(feed, "7", now=NOW)
    assert (seven["wins"], seven["losses"], seven["sample"]) == (5, 4, 9)
    assert published_results_metrics(feed, "all", now=NOW) == seven
    assert published_results_metrics(feed, "7", "top_daily", now=NOW)["hit_rate"] == .5


def test_three_public_scalars_from_results_while_existing_financial_window_unchanged():
    feed = sample_feed()
    ui = {"dashboard": {"kpi_cards": [
        {"metric": "results_success", "period": "3"},
        {"metric": "results_top_success", "period": "7"},
        {"metric": "results_avg_odds", "period": "3"},
    ]}}
    served = selected_dashboard_cards(feed, ui, now=NOW)
    assert served == [
        {"metric": "results_success", "period": "3", "value": 5 / 8},
        {"metric": "results_top_success", "period": "7", "value": .5},
        {"metric": "results_avg_odds", "period": "3", "value": pytest.approx(1.856)},
    ]
    assert feed["performance_windows"]["3"]["betting"]["overall"]["hit_rate"] == .99


def test_all_time_selector_no_data_and_reject_incompatible_periods():
    ui = json.loads((ROOT / "web/ui-config.json").read_text())
    ui["dashboard"]["kpi_cards"] = [
        {"metric": "results_success", "period": "all"},
        {"metric": "results_top_success", "period": "180"},
        {"metric": "results_avg_odds", "period": "365"},
    ]
    assert validate_ui_config(deepcopy(ui)) is not None
    assert ALLOWED_PERIODS["results_success"] == {"auto", "all", "3", "7", "14", "30", "180", "365"}
    assert [row["value"] for row in selected_dashboard_cards({}, ui, now=NOW)] == [None] * 3
    ui["dashboard"]["kpi_cards"][0]["period"] = "today"
    with pytest.raises(ValueError, match="Dashboard setting"):
        validate_ui_config(ui)
    with pytest.raises(ValueError):
        published_results_metrics(sample_feed(), "30", now=NOW.replace(tzinfo=None))

