"""Breakpoint-only opt-in CDB gap selection; no change to ordinary hourly queues."""
from datetime import date, datetime, timedelta, timezone

import pytest

from tbt.services.statistics_gapfill import missing_fields, retry_due
from tbt.services.statistics_enrichment import StatisticsEnricher, STATISTICS_SCHEMA_VERSION
from download_tennis_history import _statistics_candidates


def ready_stats():
    return {f"{side}_{field}": (.55 if "points_won" in field else 3)
            for side in ("p1", "p2")
            for field in ("service_points_won", "return_points_won",
                          "aces", "double_faults")}


def ready_match(match_factory, key="bp", when=None):
    m = match_factory(key, "A", "B", "A")
    m.scheduled_at = when or datetime(2023, 1, 18, 12, tzinfo=timezone.utc)
    m.stats = ready_stats()
    m.provider_payload = {
        "id": "123",
        "_tbt_event_identity": {
            "event_id": "123", "status": "finished",
            "home": "A", "away": "B",
        },
        "_tbt_statistics": {
            "schema": STATISTICS_SCHEMA_VERSION,
            "event_id": "123", "status": "available",
            "fetched_at": (datetime.now(timezone.utc)-timedelta(days=31)).isoformat(),
        },
    }
    return m


def test_optin_only_breakpoint_nulls_and_no_change_to_hourly_fields(match_factory):
    m = ready_match(match_factory)
    assert missing_fields(m) == []
    assert set(missing_fields(m, break_points_focus=True)) == {
        "p1_break_point_serve_win", "p1_break_point_return_win",
        "p2_break_point_serve_win", "p2_break_point_return_win"}
    assert retry_due(m, STATISTICS_SCHEMA_VERSION) is False
    assert retry_due(m, STATISTICS_SCHEMA_VERSION, break_points_focus=True) is True
    m.provider_payload["_tbt_statistics"]["fetched_at"] = datetime.now(timezone.utc).isoformat()
    assert retry_due(m, STATISTICS_SCHEMA_VERSION, break_points_focus=True) is False


def test_breakpoint_provider_native_parser_fills_null_only(match_factory, tmp_path):
    class Provider:
        calls = 0

        def _get(self, path, **kwargs):
            self.calls += 1
            assert path == "/api/tennis/event/123/statistics"
            assert kwargs.get("enrichment") is True
            return {"statistics": [{"period": "ALL", "groups": [
                {"statisticsItems": [
                    {"key": "breakPointsSaved",
                     "homeValue": 3, "homeTotal": 5,
                     "awayValue": 4, "awayTotal": 6},
                    {"key": "breakPointsConverted",
                     "homeValue": 2, "homeTotal": 6,
                     "awayValue": 3, "awayTotal": 7},
                ]}
            ]}]}

    m = ready_match(match_factory)
    old = dict(m.stats)
    provider = Provider()
    e = StatisticsEnricher(provider, tmp_path/"cache.sqlite",
                           targeted=True, break_points_focus=True)
    try:
        assert e.enrich(m) == "enriched"
        assert provider.calls == 1
        assert all(m.stats[k] == v for k,v in old.items())
        assert m.stats["p1_break_point_serve_win"] == pytest.approx(3/5)
        assert m.stats["p2_break_point_serve_win"] == pytest.approx(4/6)
        assert m.stats["p1_break_point_return_win"] == pytest.approx(2/6)
        assert m.stats["p2_break_point_return_win"] == pytest.approx(3/7)
        assert m.stats["p1_break_points_won"] == pytest.approx(2/6)
        # Fresh marker prevents re-fetching same event in the next hourly tick.
        assert e.enrich(m) == "cached"  # cooldown cache, not a second paid request
        assert provider.calls == 1
    finally:
        e.close()


def test_conflicting_bp_value_quarantines_entire_provider_response(match_factory, tmp_path):
    class Provider:
        calls = 0
        def _get(self, path, **kwargs):
            self.calls += 1
            return {"statistics": [{"period": "ALL", "groups": [{
                "statisticsItems": [
                    {"key": "breakPointsSaved", "homeValue": 3, "homeTotal": 5,
                     "awayValue": 4, "awayTotal": 6},
                    {"key": "breakPointsConverted", "homeValue": 2, "homeTotal": 6,
                     "awayValue": 3, "awayTotal": 7},
                ]
            }]}]}
    m = ready_match(match_factory)
    m.stats["p1_break_point_serve_win"] = .9
    old=dict(m.stats)
    e=StatisticsEnricher(Provider(),tmp_path/"cache.sqlite",targeted=True,break_points_focus=True)
    try:
        assert e.enrich(m)=="conflict"
        assert m.stats == old
        assert m.provider_payload["_tbt_statistics"]["status"]=="conflict"
    finally:
        e.close()


def test_breakpoint_candidate_queue_fails_closed_on_weak_identity_and_cooldown(match_factory):
    valid = ready_match(match_factory,"valid")
    noid = ready_match(match_factory,"no-id")
    noid.provider_payload={"id": "123", "_tbt_event_identity": {
        "event_id":"124", "home":"A", "away":"B", "status":"finished"}}
    recent = ready_match(match_factory,"recent")
    recent.provider_payload["_tbt_statistics"]["fetched_at"]=datetime.now(timezone.utc).isoformat()
    filled = ready_match(match_factory,"filled")
    for f in ("break_point_serve_win","break_point_return_win"):
        filled.stats[f"p1_{f}"]=.5
        filled.stats[f"p2_{f}"]=.5
    ordinary, _ = _statistics_candidates(
        [valid,noid,recent,filled],date(2023,1,1),date(2023,12,31),targeted=True)
    assert ordinary == []
    focused, plan = _statistics_candidates(
        [valid,noid,recent,filled],date(2023,1,1),date(2023,12,31),
        targeted=True,break_points_focus=True)
    assert [m.match_id for m in focused]==["valid"]
    assert plan["break_points_focus"] is True
    assert plan["skipped"] == {
        "missing_or_conflicting_event_id":1,
        "retry_not_due":1,
        "target_fields_present":1,
    }


def test_unsupported_mode_fails_without_changing_hourly_queue(match_factory):
    m=ready_match(match_factory)
    with pytest.raises(ValueError, match="isolated targeted"):
        _statistics_candidates([m],date(2023,1,1),date(2023,12,31),
                               break_points_focus=True)
    with pytest.raises(ValueError, match="isolated targeted"):
        _statistics_candidates([m],date(2023,1,1),date(2023,12,31),
                               targeted=True,break_points_focus=True,
                               historical_high_yield=True)
    with pytest.raises(ValueError, match="requires"):
        StatisticsEnricher(object(),":memory:",break_points_focus=True)


def test_partially_complete_bp_still_is_a_gap(match_factory):
    m=ready_match(match_factory)
    m.stats["p1_break_point_serve_win"]=.6
    m.stats["p2_break_point_return_win"]=.4
    assert set(missing_fields(m,break_points_focus=True)) == {
        "p1_break_point_return_win","p2_break_point_serve_win"}


def test_bp_push_guard_preserves_explicit_false_and_rejects_missing_model_change_flag():
    """Regression: jq `false // true` means true and rejects a safe BP request."""
    import json
    from pathlib import Path
    import subprocess
    import shutil
    import pytest
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/data.yml").read_text()
    expression = 'if has("model_changes") then .model_changes else true end'
    assert expression in workflow
    if not shutil.which("jq"):
        pytest.skip("jq not installed in local unit-test environment")
    for request, expected in (
        ({"model_changes": False}, "false"),
        ({"model_changes": True}, "true"),
        ({}, "true"),
    ):
        result = subprocess.run(
            ["jq", "-r", expression],
            input=json.dumps(request),
            capture_output=True, text=True, check=True,
        )
        assert result.stdout.strip() == expected


def test_breakpointsscored_native_return_conversion_fraction_only():
    from tbt.providers.statistics import parse_statistics, inventory_statistics_keys
    payload = {"statistics": [{"period": "ALL", "groups": [{
        "statisticsItems": [
            {"key": "breakPointsScored", "homeValue": 2, "homeTotal": 5,
             "awayValue": 3, "awayTotal": 9},
        ],
    }]}]}
    inventory = inventory_statistics_keys(payload)
    assert "breakpointsscored" in inventory["supported"]
    assert "breakpointsscored" not in inventory["unsupported"]
    parsed = parse_statistics(payload, home_is_player1=False)
    assert parsed["p2_break_point_return_win"] == pytest.approx(2/5)
    assert parsed["p1_break_point_return_win"] == pytest.approx(3/9)
    assert parsed["p2_break_points_won"] == pytest.approx(2/5)
    assert parsed["p1_break_points_won"] == pytest.approx(3/9)
    assert all("break_point_serve_win" not in key for key in parsed)


def test_breakpointsscored_bare_count_or_zero_denominator_never_becomes_a_rate():
    from tbt.providers.statistics import parse_statistics, NoSupportedStatisticsError
    payload = {"statistics": [{"period": "ALL", "groups": [{
        "statisticsItems": [{"key":"breakPointsScored", "home": "5", "away": "8"}]
    }]}]}
    with pytest.raises(NoSupportedStatisticsError, match="no supported"):
        parse_statistics(payload, home_is_player1=True)
    payload["statistics"][0]["groups"][0]["statisticsItems"][0] = {
        "key":"breakPointsScored",
        "homeValue":5, "homeTotal":0,
        "awayValue":6, "awayTotal":4,
    }
    with pytest.raises(NoSupportedStatisticsError, match="no supported"):
        parse_statistics(payload, home_is_player1=True)


def test_breakpointsscored_and_converted_disagreement_fails_closed():
    from tbt.providers.statistics import parse_statistics
    from tbt.errors import ProviderError
    payload={"statistics":[{"period":"ALL","groups":[{
        "statisticsItems":[
            {"key":"breakPointsConverted", "homeValue":2, "homeTotal":5},
            {"key":"breakPointsScored", "homeValue":3, "homeTotal":5},
        ],
    }]}]}
    with pytest.raises(ProviderError, match="Conflicting whole-match statistic"):
        parse_statistics(payload, home_is_player1=True)
