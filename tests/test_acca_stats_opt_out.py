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


def _ui(exclude: bool) -> dict:
    return {"dashboard": {
        "daily_hub": {"tabs": {"prime": {"enabled": True, "exclude_from_stats": exclude}}},
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
    assert [card["value"] for card in cards] == [None, None, None]
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
    with pytest.raises(ValueError, match="ACCA exclude_from_stats"):
        validate_ui_config(ui)


def test_admin_ui_statistics_toggle_only_filters_metrics_not_results_table():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    assert 'data-admin-acca-exclude-stats' in app
    assert 'tabs.prime.exclude_from_stats=Boolean(t.checked)' in app
    assert 'function accaExcludedFromStats()' in app
    assert 'const metricEntries=accaExcludedFromStats()?settledPublishedEntries(rows,category,filters,true):entries;' in app
    assert 'const filters=state.resultsFilters||{},rows=filteredResults(filters),category=filters.category||\'all\',entries=settledPublishedEntries(rows,category,filters);' in app
    assert ".filter(p=>!statsOnly||!accaExcludedFromStats()" in app
