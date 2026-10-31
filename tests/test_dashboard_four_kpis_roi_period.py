"""Fourth dashboard KPI, old Azure config compatibility and ROI period."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from tbt.services.admin_storage import validate_ui_config
from tbt.services.dashboard_kpis import DEFAULT_CARDS, normalize_cards, selected_dashboard_cards

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


def test_legacy_three_slots_are_extended_without_resetting_selection():
    legacy = [
        {"metric": "today_picks", "period": "today"},
        {"metric": "winner_roi", "period": "7"},
        {"metric": "auto_success", "period": "auto"},
    ]
    result = normalize_cards({"dashboard": {"kpi_cards": legacy}})
    assert len(result) == len(DEFAULT_CARDS) == 4
    assert result[:3] == legacy
    assert result[3] == {"metric": "results_roi", "period": "30"}
    assert normalize_cards({}) == list(DEFAULT_CARDS)
    ui = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))
    assert ui["dashboard"]["kpi_cards"] == list(DEFAULT_CARDS)
    assert validate_ui_config(deepcopy(ui)) is not None
    ui["dashboard"]["kpi_cards"] = legacy
    assert validate_ui_config(ui) is not None


def test_fourth_roi_uses_real_settled_bet_and_exposes_auto_window():
    when = NOW - timedelta(days=2)
    feed = {"results": [{
        "event_id": "roi-window-4",
        "scheduled_at": when.isoformat(),
        "market_publications": [{
            "issued_at": (when - timedelta(hours=1)).isoformat(),
            "section": "top_daily", "market": "match_winner",
            "selection_id": "player-a", "odds": 2.2, "price_status": "priced",
            "result": {"correct": True, "staked_units": 1, "profit_units": 1.2},
        }],
    }]}
    cfg = {"dashboard": {"kpi_cards": [
        {"metric": "today_picks", "period": "today"},
        {"metric": "model_success", "period": "auto"},
        {"metric": "avg_odds", "period": "today"},
        {"metric": "results_roi", "period": "30"},
    ]}}
    selected = selected_dashboard_cards(feed, cfg, now=NOW)
    assert len(selected) == 4
    assert selected[3] == {"metric": "results_roi", "period": "30", "value": 1.2}
    cfg["dashboard"]["kpi_cards"][3] = {"metric": "auto_roi", "period": "auto"}
    auto = selected_dashboard_cards(feed, cfg, now=NOW)[3]
    assert auto["value"] == 1.2
    assert auto["selected_period"] in {"3", "7", "14", "30", "180", "365", "all"}
    assert auto["selected_source"] == "results_roi"
    assert auto["sample"] == 1


def test_mobile_and_desktop_tiles_show_selected_roi_period():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    css = (ROOT / "web/blinq-app.css").read_text(encoding="utf-8")
    mobile = (ROOT / "web/blinq-mobile-visual.css").read_text(encoding="utf-8")
    cascade = (ROOT / "web/blinq-mobile-unified-cards.css").read_text(encoding="utf-8")
    assert "{metric:'results_roi',period:'30'}" in app
    assert "dashboardKpiDefaults.length" in app
    assert "snapshot?.selected_period" in app
    assert "effectivePeriod" in app
    assert "Za '+effectivePeriod+' dní" in app
    assert "Obdobie ROI:" in app
    assert "grid-template-columns:repeat(4,minmax(0,1fr))!important" in css
    assert "grid-template-columns:repeat(2,minmax(0,1fr))!important" in mobile
    assert "body#blinqPremium#blinqPremium#blinqPremium:not(.blinq-admin) #dashboardKpis" in cascade
    assert "max-width:1100px" in cascade
    assert '#dashboardKpis[data-kpi-count="4"]' in cascade
    assert '.bqm-enabled:not(.blinq-admin)' in cascade


def test_optional_fourth_kpi_card_and_roi_caption_settings():
    baseline = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))
    assert baseline["dashboard"]["fourth_card_enabled"] is True
    assert baseline["dashboard"]["show_roi_period"] is True
    baseline["dashboard"]["fourth_card_enabled"] = False
    assert validate_ui_config(deepcopy(baseline)) is not None
    selected = selected_dashboard_cards({}, baseline, now=NOW)
    assert len(selected) == 3
    assert len(normalize_cards(baseline)) == 4
    baseline["dashboard"]["fourth_card_enabled"] = True
    assert len(selected_dashboard_cards({}, baseline, now=NOW)) == 4
    for field in ("fourth_card_enabled", "show_roi_period"):
        baseline["dashboard"][field] = "false"
        try:
            validate_ui_config(deepcopy(baseline))
        except ValueError as exc:
            assert "Dashboard setting" in str(exc)
        else:
            raise AssertionError(f"Invalid dashboard toggle accepted: {field}")
        baseline["dashboard"][field] = True
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    assert 'data-admin-kpi-toggle="fourth_card_enabled"' in app
    assert 'data-admin-kpi-period-index="${index}"' in app
    assert "host.dataset.kpiCount" in app
    assert "captionSettings[index]" in app
    assert "dashboardKpiCaptionSettings()" in app
    assert "effectivePeriod==='today'" in app
    assert "Zobraziť obdobie pod kartou" in app
    assert 'class="admin-dashboard-period-field"' in app
    assert 'class="admin-kpi-period-toggle"' in app
    last = (ROOT / "web/blinq-mobile-unified-cards.css").read_text(encoding="utf-8")
    assert 'data-kpi-count="3"' in last
    assert 'grid-template-columns:repeat(3,minmax(0,1fr))!important' in last


def test_period_caption_is_configured_separately_per_card():
    ui = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))
    assert ui["dashboard"]["kpi_period_visibility"] == [False, False, False, True]
    for flags in ([True, False, True, False], [False] * 4, [True] * 4):
        ui["dashboard"]["kpi_period_visibility"] = flags
        assert validate_ui_config(deepcopy(ui)) is not None
    for flags in ([], [True] * 3, [True] * 5, [True, 0, False, True], "true"):
        ui["dashboard"]["kpi_period_visibility"] = flags
        try:
            validate_ui_config(deepcopy(ui))
        except ValueError as exc:
            assert "period visibility" in str(exc)
        else:
            raise AssertionError(f"Invalid caption visibility accepted: {flags!r}")
