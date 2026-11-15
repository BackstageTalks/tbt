"""Request-local KPI scan memo: parity, scope and repeated window work."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
import tbt.services.dashboard_kpis as kpis


NOW = datetime(2026, 11, 15, 9, tzinfo=timezone.utc)


def _row(event, days, section, correct, *, selection=None, issued_offset=2):
    scheduled = NOW - timedelta(days=days)
    return {
        "event_id": event,
        "scheduled_at": scheduled.isoformat(),
        "market_publications": [{
            "issued_at": (scheduled - timedelta(hours=issued_offset)).isoformat(),
            "section": section,
            "market": "match_winner",
            "selection_id": selection or event,
            "odds": 1.9,
            "price_status": "priced",
            "result": {"correct": correct, "staked_units": 1,
                       "profit_units": .9 if correct else -1},
        }],
    }


def _feed():
    # Duplicate issuance, two Results sections, a void, an older window,
    # and an unissued publication that must not affect any KPI.
    rows = [
        _row("top", 1, "top_daily", True),
        _row("top", 1, "prime", False, issued_offset=1),
        _row("value", 2, "value", False),
        _row("older", 70, "top_daily", True),
        _row("void", 1, "top_daily", False),
        _row("unissued", 1, "top_daily", True),
    ]
    rows[4]["market_publications"][0]["result"]["status"] = "void"
    rows[5]["market_publications"][0].pop("issued_at")
    return {"results": rows}


@pytest.mark.parametrize("category", ["all", "top_daily", "winners"])
def test_rolling_kpi_memo_matches_independent_uncached_evaluation(category):
    feed = _feed()
    original = deepcopy(feed)
    cache = {}
    for period in ["3", "7", "14", "30", "180", "365", "all"]:
        baseline = kpis.published_results_metrics(feed, period, category, now=NOW)
        optimized = kpis.published_results_metrics(
            feed, period, category, now=NOW, _scan_cache=cache,
        )
        assert optimized == baseline
    assert feed == original


def test_auto_kpis_parse_authorized_row_dates_only_once_per_invocation(monkeypatch):
    feed = _feed()
    original = deepcopy(feed)
    config = {"dashboard": {"kpi_cards": [
        {"metric": "auto_success", "period": "auto"},
        {"metric": "auto_avg_odds", "period": "auto"},
        {"metric": "auto_roi", "period": "auto"},
        {"metric": "auto_yield_units", "period": "auto"},
    ]}}
    calls = {"date": 0, "identity": 0, "outcome": 0}
    for label, attribute in (("date", "_result_datetime"),
                             ("identity", "_result_identity"),
                             ("outcome", "_result_outcome")):
        real = getattr(kpis, attribute)
        def wrapped(*args, _real=real, _label=label, **kwargs):
            calls[_label] += 1
            return _real(*args, **kwargs)
        monkeypatch.setattr(kpis, attribute, wrapped)

    first = kpis.selected_dashboard_cards(feed, config, now=NOW)
    assert len(first) == 4
    assert all(card["value"] is not None for card in first)
    # Six rows with one publication each; parse scheduled+issued dates only
    # for relevant rows and publications, not again for every auto window.
    assert calls["date"] <= 12, calls
    assert calls["identity"] <= 5, calls
    assert calls["outcome"] <= 5, calls
    assert feed == original
    second = kpis.selected_dashboard_cards(feed, config, now=NOW)
    assert second == first
    assert calls["date"] > 12, "A new invocation must build its own cache"


def test_kpi_memo_is_not_shared_across_authorized_accounts():
    config = {"dashboard": {"kpi_cards": [
        {"metric": "results_success", "period": "all"},
        {"metric": "results_top_success", "period": "all"},
        {"metric": "results_roi", "period": "all"},
        {"metric": "results_avg_odds", "period": "all"},
    ]}}
    full = _feed()
    restricted = {"results": [deepcopy(full["results"][2])]}
    full_values = kpis.selected_dashboard_cards(full, config, now=NOW)
    restricted_values = kpis.selected_dashboard_cards(restricted, config, now=NOW)
    assert full_values[0]["value"] != restricted_values[0]["value"]
    assert restricted_values[0]["value"] == 0.0
    assert restricted_values[1]["value"] is None
    assert kpis.selected_dashboard_cards(full, config, now=NOW) == full_values
