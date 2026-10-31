"""Global ACCA STATS exclusion is independent of public visibility and immutable Results."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from tbt.services.admin_storage import validate_ui_config
from tbt.services.dashboard_kpis import selected_dashboard_cards

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def _pub(section: str, *, won: bool, selection: str, odds: float) -> dict:
    return {
        "section": section, "issued_at": "2026-10-23T09:00:00Z",
        "market": "match_winner", "selection_id": selection,
        "price_status": "priced", "odds": odds,
        "result": {"correct": won, "staked_units": 1,
                   "profit_units": odds - 1 if won else -1},
    }


def _ui(exclude: bool, *, enabled: bool = True, tab: str = "prime") -> dict:
    return {"dashboard": {
        "daily_hub": {"tabs": {tab: {"enabled": enabled, "exclude_from_stats": exclude}}},
        "kpi_cards": [
            {"metric": "results_success", "period": "all"},
            {"metric": "results_avg_odds", "period": "all"},
            {"metric": "results_yield_units", "period": "all"},
        ],
    }}


def test_acca_stats_toggle_preserves_historical_publications_and_other_markets():
    # The same event/selection is in TOP and ACCA. After excluding ACCA,
    # deduplication must still keep TOP even when the ACCA copy is older.
    top = _pub("top_daily", won=False, selection="a", odds=2.0)
    top["issued_at"] = "2026-10-23T10:00:00Z"
    acca = _pub("prime", won=True, selection="a", odds=1.08)
    value = _pub("value", won=True, selection="b", odds=1.80)
    feed = {"results": [
        {"event_id": "same-match", "scheduled_at": NOW.isoformat(),
         "market_publications": [acca, top]},
        {"event_id": "value-match", "scheduled_at": NOW.isoformat(),
         "market_publications": [value]},
    ]}
    snapshot = deepcopy(feed)
    enabled = selected_dashboard_cards(feed, _ui(False), now=NOW)
    disabled = selected_dashboard_cards(feed, _ui(True), now=NOW)
    assert enabled[0]["value"] == 1.0  # ACCA wins tie when it is enabled
    assert disabled[0]["value"] == .5  # TOP loss and VALUE win remain
    assert enabled[1]["value"] == pytest.approx((1.08 + 1.8) / 2)
    assert disabled[1]["value"] == pytest.approx((2.0 + 1.8) / 2)
    assert disabled[2]["value"] == pytest.approx(-.2)
    assert feed == snapshot  # no archive mutation or result deletion


def test_acca_only_returns_empty_stats_not_deleted_results():
    feed = {"results": [{
        "event_id": "short", "scheduled_at": NOW.isoformat(),
        "market_publications": [_pub("prime", won=True, selection="a", odds=1.11)],
    }]}
    cards = selected_dashboard_cards(feed, _ui(True), now=NOW)
    assert [card["value"] for card in cards] == [None, None, None, None]
    assert len(feed["results"][0]["market_publications"]) == 1
    assert selected_dashboard_cards(feed, _ui(False), now=NOW)[0]["value"] == 1


def test_legacy_defaults_on_and_admin_validation_rejects_invalid_types():
    ui = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))
    prime = ui["dashboard"]["daily_hub"]["tabs"]["prime"]
    assert prime["exclude_from_stats"] is False
    assert validate_ui_config(deepcopy(ui))
    prime["exclude_from_stats"] = True
    assert validate_ui_config(deepcopy(ui))
    prime["exclude_from_stats"] = "true"
    with pytest.raises(ValueError, match="prime exclude_from_stats"):
        validate_ui_config(ui)


def test_admin_ui_statistics_toggle_only_filters_metrics_not_results_table():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    assert 'data-admin-market-exclude-stats' in app
    assert 'cfg.exclude_from_stats=Boolean(t.checked)' in app
    assert 'function statsExcludedSections()' in app
    assert 'const metricEntries=statsHaveExcludedMarkets()?settledPublishedEntries(rows,category,filters,true):entries;' in app
    assert "const excluded=statsOnly?statsExcludedSections():null;" in app
    assert ".filter(p=>!excluded||!excluded.has(resultPublicationStatsSection(p)))" in app
    assert 'const filters=state.resultsFilters||{},rows=filteredResults(filters),category=filters.category||\'all\',entries=settledPublishedEntries(rows,category,filters);' in app


def test_global_acca_off_blocks_stats_flow_even_when_standalone_opt_out_is_unchecked():
    # ACCA ON + exclude OFF counts an ACCA entry. Turning the global category
    # OFF must stop its contribution to every Results-based KPI automatically.
    acca = _pub("prime", won=True, selection="a", odds=1.08)
    top = _pub("top_daily", won=False, selection="a", odds=2.00)
    top["issued_at"] = "2026-10-23T10:00:00Z"
    value = _pub("value", won=True, selection="b", odds=1.80)
    feed = {"results": [
        {"event_id": "same", "scheduled_at": NOW.isoformat(),
         "market_publications": [acca, top]},
        {"event_id": "another", "scheduled_at": NOW.isoformat(),
         "market_publications": [value]},
    ]}
    original = deepcopy(feed)
    normal = selected_dashboard_cards(feed, _ui(False, enabled=True), now=NOW)
    global_off = selected_dashboard_cards(feed, _ui(False, enabled=False), now=NOW)
    explicit_off = selected_dashboard_cards(feed, _ui(True, enabled=True), now=NOW)
    assert normal[0]["value"] == 1.0
    assert [c["value"] for c in global_off] == [c["value"] for c in explicit_off]
    assert global_off[0]["value"] == .5
    assert global_off[1]["value"] == pytest.approx(1.9)
    assert global_off[2]["value"] == pytest.approx(-.2)
    assert feed == original  # Keeps ACCA publications in historical Results.


def test_global_acca_off_does_not_hide_non_acca_publications_in_the_same_match():
    feed = {"results": [{
        "event_id": "same", "scheduled_at": NOW.isoformat(),
        "market_publications": [
            _pub("prime", won=True, selection="a", odds=1.05),
            _pub("top_daily", won=False, selection="a", odds=2.0),
        ],
    }]}
    cards = selected_dashboard_cards(feed, _ui(False, enabled=False), now=NOW)
    assert cards[0]["value"] == 0
    assert cards[1]["value"] == 2.0
    assert len(feed["results"][0]["market_publications"]) == 2


def test_global_acca_off_is_a_server_and_client_stats_gate_not_a_visibility_only_flag():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    from tbt.services import dashboard_kpis
    from inspect import getsource
    assert "cfg?.enabled===false||cfg?.exclude_from_stats===true" in app
    server = getsource(dashboard_kpis._excluded_stats_sections)
    assert 'tabs[tab_id].get("enabled") is False' in server
    assert 'tabs[tab_id].get("exclude_from_stats") is True' in server
    assert "ACCA aktívna" in app
    assert "záložka aj prísun ACCA zápasov do STATS" in app


ALL_STATS_TABS = {
    "daily": "top_daily", "prime": "prime", "value": "value",
    "ace": "ace", "double_faults": "double_faults", "doubles": "doubles",
    "games": "games", "sets": "sets",
}


@pytest.mark.parametrize("tab,section", ALL_STATS_TABS.items())
def test_all_eight_markets_can_be_independently_excluded_from_stats(tab, section):
    # A win from the requested market and a loss from a different market.
    # Disabling a source must preserve the other source and the archived feed.
    other_section = "value" if section != "value" else "top_daily"
    feed = {"results": [
        {"event_id": "chosen", "scheduled_at": NOW.isoformat(),
         "market_publications": [_pub(section, won=True, selection="a", odds=1.50)]},
        {"event_id": "other", "scheduled_at": NOW.isoformat(),
         "market_publications": [_pub(other_section, won=False, selection="b", odds=2.0)]},
    ]}
    before = deepcopy(feed)
    included = selected_dashboard_cards(feed, _ui(False, tab=tab), now=NOW)
    excluded = selected_dashboard_cards(feed, _ui(True, tab=tab), now=NOW)
    global_off = selected_dashboard_cards(feed, _ui(False, enabled=False, tab=tab), now=NOW)
    assert included[0]["value"] == 0.5
    assert excluded[0]["value"] == global_off[0]["value"] == 0
    assert excluded[1]["value"] == global_off[1]["value"] == 2.0
    assert excluded[2]["value"] == global_off[2]["value"] == -1
    assert feed == before


@pytest.mark.parametrize("tab", ALL_STATS_TABS)
def test_validation_accepts_boolean_stats_flags_for_every_market(tab):
    ui = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))
    assert ui["dashboard"]["daily_hub"]["tabs"][tab]["exclude_from_stats"] is False
    ui["dashboard"]["daily_hub"]["tabs"][tab]["exclude_from_stats"] = True
    assert validate_ui_config(deepcopy(ui))
    ui["dashboard"]["daily_hub"]["tabs"][tab]["exclude_from_stats"] = "true"
    with pytest.raises(ValueError, match=f"{tab} exclude_from_stats"):
        validate_ui_config(ui)


def test_derived_all_tab_is_not_an_independent_stats_source():
    ui = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))
    ui["dashboard"]["daily_hub"]["tabs"]["see_all"]["exclude_from_stats"] = True
    with pytest.raises(ValueError, match="Unsupported STATS exclusion category"):
        validate_ui_config(ui)


def test_multi_market_opt_out_precedes_cross_section_deduplication():
    # Value is the oldest result from a match, then TOP; excluding VALUE
    # must count TOP. Excluding both must return an empty sample.
    value = _pub("value", won=True, selection="a", odds=1.20)
    top = _pub("top_daily", won=False, selection="a", odds=2.0)
    top["issued_at"] = "2026-10-23T10:00:00Z"
    feed = {"results": [{
        "event_id": "shared", "scheduled_at": NOW.isoformat(),
        "market_publications": [value, top],
    }]}
    ui = _ui(True, tab="value")
    assert selected_dashboard_cards(feed, ui, now=NOW)[0]["value"] == 0
    ui["dashboard"]["daily_hub"]["tabs"]["daily"] = {
        "enabled": True, "exclude_from_stats": True
    }
    assert selected_dashboard_cards(feed, ui, now=NOW)[0]["value"] is None
    assert len(feed["results"][0]["market_publications"]) == 2


def test_stats_opt_out_is_only_for_stats_and_not_visibility_or_betting_history():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    from tbt.services.dashboard_kpis import _STATS_TAB_TO_SECTION
    assert _STATS_TAB_TO_SECTION == ALL_STATS_TABS
    for tab in ALL_STATS_TABS:
        assert f"'{tab}':" in app or f"{tab}:" in app
    assert "statsToggle=statsSource" in app
    assert "admin-market-stats-toggle" in app
    assert "statsOnly?statsExcludedSections():null" in app
    assert "const entries=settledPublishedEntries(rows,category,filters);" in app
    assert "const metricEntries=statsHaveExcludedMarkets()?" in app
    assert "statsHaveExcludedMarkets()?null:todayPublishedPickCount()" in app
