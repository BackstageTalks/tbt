"""Admin-only Dashboard setting: three scalar cards, no model or visual rewrite."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from tbt.services.admin_storage import validate_ui_config
from tbt.services.dashboard_kpis import (
    ALLOWED_PERIODS, DEFAULT_CARDS, normalize_cards, selected_dashboard_cards,
)
from tbt.services.engine import (
    PERFORMANCE_AUTO_WINDOWS_DAYS, PERFORMANCE_WINDOWS_DAYS, performance_windows,
)

ROOT = Path(__file__).resolve().parents[1]


def _published(now, event, section, odds, correct, profit, days=2):
    started = (now - timedelta(days=days)).isoformat()
    return {
        "event_id": event, "scheduled_at": started,
        "market_publications": [{
            "issued_at": (now - timedelta(days=days + 1)).isoformat(),
            "publication_status": "published", "section": section, "market": "match_winner",
            "selection_id": event, "odds": odds, "price_status": "priced",
            "result": {"correct": correct, "staked_units": 1, "profit_units": profit},
        }],
    }


def _feed_with_all_three_market_categories():
    now = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
    issued = [
        _published(now, "top", "top_daily", 1.8, True, .8),
        _published(now, "value", "value", 2.1, False, -1.0),
        _published(now, "short", "prime", 1.06, True, .06),
    ]
    windows, summary = performance_windows([], issued, now=now)
    return {"dashboard_model_success": {"accuracy": .703},
            "performance_windows": windows, "performance_window_summary": summary}


def test_three_defaults_preserve_existing_public_dashboard():
    ui = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))
    assert ui["dashboard"]["kpi_cards"] == list(DEFAULT_CARDS)
    assert normalize_cards({}) == list(DEFAULT_CARDS)
    assert normalize_cards({"dashboard": {"kpi_cards": [1, {"metric": "roi", "period": "30"}, {}]}}) == [
        DEFAULT_CARDS[0], {"metric": "roi", "period": "30"}, DEFAULT_CARDS[2],
    ]
    assert validate_ui_config(deepcopy(ui)) is not None


def test_selected_three_scalars_use_correct_sources_and_exclude_short_odds_units():
    feed = _feed_with_all_three_market_categories()
    ui = {"dashboard": {"kpi_cards": [
        {"metric": "avg_odds", "period": "7"},
        {"metric": "roi", "period": "7"},
        {"metric": "yield_units", "period": "7"},
    ]}}
    result = selected_dashboard_cards(feed, ui)
    assert [x["metric"] for x in result] == ["avg_odds", "roi", "yield_units"]
    assert abs(result[0]["value"] - 1.8) < 1e-12  # historical TOP only
    assert abs(result[1]["value"] - (-.1)) < 1e-12  # (.8-1.0) / two genuine units
    assert abs(result[2]["value"] - (-.2)) < 1e-12
    assert all(set(x) == {"metric", "period", "value"} for x in result)
    # Immutable Short Odds bet still exists with its individual +0.06u result.
    assert feed["performance_windows"]["7"]["betting"]["sections"]["prime"]["wins"] == 1
    assert feed["performance_windows"]["7"]["betting"]["sections"]["prime"]["profit_units"] == 0


def test_model_selected_window_and_auto_do_not_misrepresent_historical_bets():
    feed = _feed_with_all_three_market_categories()
    feed["performance_windows"]["180"]["model"] = {"accuracy": .763, "n": 38}
    ui = {"dashboard": {"kpi_cards": [
        {"metric": "model_success", "period": "auto"},
        {"metric": "model_success", "period": "180"},
        {"metric": "today_picks", "period": "today"},
    ]}}
    values = selected_dashboard_cards(feed, ui)
    assert values[0]["value"] == .703 and values[1]["value"] == .763
    assert values[2]["value"] is None  # per-account count is calculated from authorized rows
    assert 180 in PERFORMANCE_WINDOWS_DAYS
    assert 180 not in PERFORMANCE_AUTO_WINDOWS_DAYS  # legacy automatic KPI unaffected


def test_new_180_horizon_and_missing_periods_do_not_fabricate_values():
    feed = _feed_with_all_three_market_categories()
    assert "180" in feed["performance_windows"] and "365" in feed["performance_windows"]
    ui = {"dashboard": {"kpi_cards": [
        {"metric": "avg_odds", "period": "today"},
        {"metric": "yield_units", "period": "180"},
        {"metric": "model_success", "period": "365"},
    ]}}
    values = selected_dashboard_cards(feed, ui)
    assert values[0]["value"] is None
    assert abs(values[1]["value"] + .2) < 1e-12
    assert values[2]["value"] is None  # no issued winner-model sample


@pytest.mark.parametrize("bad", [
    [],
    [{"metric": "today_picks", "period": "365"}] * 3,
    [{"metric": "model_success", "period": "today"}] * 3,
    [{"metric": "fake_metric", "period": "30"}] * 3,
    [{"metric": "roi", "period": "30", "arbitrary": "value"}] * 3,
])
def test_admin_publish_rejects_invalid_kpi_slots(bad):
    ui = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))
    ui["dashboard"]["kpi_cards"] = bad
    with pytest.raises(ValueError, match="Dashboard setting"):
        validate_ui_config(ui)


def test_public_markup_unchanged_and_admin_config_is_scoped():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    css = (ROOT / "web/blinq-app.css").read_text(encoding="utf-8")
    api = (ROOT / "api/function_app.py").read_text(encoding="utf-8")
    assert "function renderAdminDashboardSettings()" in app
    assert "data-admin-kpi-index" in app
    assert "Dashboard setting" in app
    assert "const cards=dashboardKpiSettings().map" in app
    assert 'host.innerHTML=cards.map(([icon,label,value,note,trend])=>`<article class="dashboard-kpi"' in app
    assert "state.feed?.dashboard_kpi_cards" in app
    assert "source_feed = visible_feed(read_feed(FEED))" in api
    assert 'data["dashboard_kpi_cards"] = selected_dashboard_cards(source_feed, runtime_ui)' in api
    assert "data, entitlements = filter_feed_for_access(source_feed" in api
    assert "body#blinqPremium.blinq-admin .admin-dashboard-slot" in css
    assert ALLOWED_PERIODS["roi"] == {"3", "7", "14", "30", "180", "365"}
