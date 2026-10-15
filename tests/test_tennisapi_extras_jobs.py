"""Regression contract for scheduled provider-1 extra API enrichment."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tbt.errors import ProviderError
from tbt.data.provider_context import minimize_provider_payload
from tbt.providers.budget import RequestBudgetExceeded
from tbt.services.tennisapi_extras_enrichment import (
    enrich_event_extras, marker_due, needs_extras,
)
from verify_tennisapi_extras import verify_markers


NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


class Provider:
    def __init__(self, *, exhausted_pbp=False, malformed_id=False):
        self.calls = []
        self.request_count = 0
        self.exhausted_pbp = exhausted_pbp
        self.malformed_id = malformed_id

    def _get(self, path, **kwargs):
        self.calls.append(path)
        self.request_count += 1
        return {"event": {
            "id": "other" if self.malformed_id else "100",
            "homeTeam": {"id": "A"}, "awayTeam": {"id": "B"},
            "status": {"type": "finished"},
        }}

    def event_odds(self, eid, provider_id=1):
        self.calls.append("odds")
        self.request_count += 1
        return {"eventId": 100, "markets": [{
            "marketId": 12, "choiceGroup": "21.5", "isLive": False,
            "choices": [
                {"name": "Over", "fractionalValue": "4/5"},
                {"name": "Under", "fractionalValue": "10/11"},
            ],
        }]}

    def event_point_by_point(self, eid):
        self.calls.append("pbp")
        self.request_count += 1
        if self.exhausted_pbp:
            raise RequestBudgetExceeded("shared budget reached")
        return {"eventId": 100, "sets": [{
            "games": [{"score": {"serving": 1, "scoring": 2}, "points": [{}, {}]}]
        }]}


def match_for_extras(match_factory):
    match = match_factory("event-match", "A", "B", "A")
    match.provider_payload = {"id": "100"}
    match.stats = {"p1_aces": 9}
    return match


def test_extras_reuse_identity_and_do_not_touch_model_fields(match_factory):
    match = match_for_extras(match_factory)
    original_stats = dict(match.stats)
    provider = Provider()
    assert needs_extras(match, now=NOW)
    result = enrich_event_extras(match, provider, now=NOW)
    assert result["changed"] is True
    assert result["markets"] == "available"
    assert result["pbp"] == "available"
    assert provider.calls == ["/api/tennis/event/100", "odds", "pbp"]
    assert match.stats == original_stats
    markers = {k: match.provider_payload[k] for k in (
        "_tbt_tennisapi_markets", "_tbt_tennisapi_pbp")}
    assert verify_markers([match], {str(match.match_id): markers}) == 2
    assert not needs_extras(match, now=NOW + timedelta(days=1))
    assert enrich_event_extras(match, provider, now=NOW)["status"] == "cached"
    assert provider.request_count == 3

    # Strict CDB compacting must preserve observed evidence, including price lines.
    compact = minimize_provider_payload(match.provider_payload)
    assert compact["_tbt_tennisapi_markets"] == markers["_tbt_tennisapi_markets"]
    assert compact["_tbt_tennisapi_pbp"] == markers["_tbt_tennisapi_pbp"]
    assert compact["_tbt_tennisapi_markets"]["quotes"][0]["line_games"] == 21.5
    assert compact["_tbt_tennisapi_markets"]["pre_match_asof_verified"] is False
    assert compact["_tbt_tennisapi_pbp"]["eligible_for_cdb_point_features"] is False


def test_daily_extras_priority_2026_then_2025_then_older(match_factory):
    from datetime import date
    from download_tennis_history import _extras_candidates

    def candidate(name, year, month, day, *, verified=False, covered=False):
        match = match_factory(name, "A", "B", "A")
        match.scheduled_at = datetime(year, month, day, 12, tzinfo=timezone.utc)
        raw = {"id": "100"}
        if verified:
            raw["_tbt_event_identity"] = {
                "event_id": "100", "status": "finished",
                "home": "A", "away": "B",
            }
        if covered:
            for marker in ("_tbt_tennisapi_markets", "_tbt_tennisapi_pbp"):
                raw[marker] = {
                    "schema": 1, "event_id": "100", "status": "available",
                    "observed_at_utc": NOW.isoformat(),
                }
        match.provider_payload = raw
        return match

    older_verified = candidate("older-2022", 2022, 7, 4, verified=True)
    previous_verified = candidate("previous-2025", 2025, 9, 1, verified=True)
    current_unverified = candidate("current-2026-unverified", 2026, 10, 13)
    current_verified = candidate("current-2026-verified", 2026, 8, 3, verified=True)
    current_covered = candidate("current-2026-covered", 2026, 10, 14, covered=True)
    future = candidate("future-2026", 2026, 12, 1)
    backlog = [older_verified, previous_verified, current_unverified,
               current_verified, current_covered, future]
    dates = (date(2022, 1, 1), date(2026, 10, 14))
    result = _extras_candidates(backlog, *dates)
    assert [m.match_id for m in result] == [
        "current-2026-verified", "current-2026-unverified",
        "previous-2025", "older-2022",
    ]
    # When the current year is fully covered, daily runs automatically
    # advance to 2025 rather than repeatedly querying cached 2026 events.
    remaining = _extras_candidates(
        [current_covered, previous_verified, older_verified], *dates)
    assert [m.match_id for m in remaining] == ["previous-2025", "older-2022"]


def test_shared_budget_stop_keeps_successful_first_endpoint_for_resume(match_factory):
    match = match_for_extras(match_factory)
    provider = Provider(exhausted_pbp=True)
    with pytest.raises(RequestBudgetExceeded):
        enrich_event_extras(match, provider, now=NOW)
    assert match.provider_payload["_tbt_tennisapi_markets"]["status"] == "available"
    assert "_tbt_tennisapi_pbp" not in match.provider_payload
    assert needs_extras(match, now=NOW)
    resumed = Provider()
    assert enrich_event_extras(match, resumed, now=NOW)["markets"] == "cached"
    assert resumed.calls == ["pbp"]


def test_failed_identity_never_queries_or_attaches_market_pbp(match_factory):
    match = match_for_extras(match_factory)
    provider = Provider(malformed_id=True)
    with pytest.raises(ProviderError, match="event ID mismatch"):
        enrich_event_extras(match, provider, now=NOW)
    assert provider.calls == ["/api/tennis/event/100"]
    assert "_tbt_tennisapi_markets" not in match.provider_payload
    assert "_tbt_tennisapi_pbp" not in match.provider_payload


def test_stale_missing_coverage_retry_is_cooldown_guarded():
    marker = {"schema": 1, "event_id": "100", "status": "unavailable",
              "observed_at_utc": NOW.isoformat()}
    assert not marker_due(marker, "100", NOW + timedelta(days=7))
    assert marker_due(marker, "100", NOW + timedelta(days=31))
    assert not marker_due({**marker, "status": "available"}, "100", NOW + timedelta(days=100))


def test_existing_set_statistics_survive_parquet_minimization():
    sample = {"_tbt_statistics_by_set": {
        "schema": 1, "source": "tennisapi1", "event_id": "100",
        "orientation": "provider_home_away", "scope": "post_match_only",
        "sets": {"1": {"home_aces": 5, "away_double_faults": 2},
                 "2": {"home_aces": 3}},
    }}
    assert minimize_provider_payload(sample)["_tbt_statistics_by_set"] == sample["_tbt_statistics_by_set"]


def test_hourly_scheduler_keeps_bounded_extras_and_same_writer():
    root = Path(__file__).resolve().parents[1]
    hourly = (root / ".github/workflows/data-hourly-quota-gapfill.yml").read_text()
    data = (root / ".github/workflows/data.yml").read_text()
    assert "extras_slot = local.hour in (14, 17)" in hourly
    assert "proposed = min(proposed, 450)" in hourly
    assert 'payload["inputs"]["mode"] = "extras"' in hourly
    assert "BLINQ_PROVIDER_REQUEST_RESERVE=450" in data
    assert "BLINQ_RAPIDAPI_MAX_RPS=6" in data
    assert "python scripts/cdb_global_writer_lock.py acquire" in data
    assert "python scripts/verify_tennisapi_extras.py" in data
    assert "BLINQ_AUTOFILL_HIGH_YIELD:" in data


def test_targeted_statistics_readback_requires_exact_provider_set_evidence(match_factory):
    from verify_targeted_statistics import verify_per_set_markers

    match = match_for_extras(match_factory)
    marker = {
        "schema": 1, "source": "tennisapi1", "event_id": "100",
        "orientation": "provider_home_away", "scope": "post_match_only",
        "sets": {"1": {"home_aces": 3.0, "away_aces": 4.0}},
    }
    match.provider_payload["_tbt_statistics_by_set"] = marker
    assert verify_per_set_markers([match], {str(match.match_id): marker}) == 1
    with pytest.raises(ValueError, match="Missing or modified"):
        verify_per_set_markers(
            [match], {str(match.match_id): {**marker, "sets": {"1": {"home_aces": 5}}}}
        )


def test_merge_never_downgrades_provider_side_postmatch_evidence():
    from tbt.data.provider_context import merge_provider_context

    old = {
        "_tbt_statistics_by_set": {
            "schema": 1, "source": "tennisapi1", "event_id": "100",
            "orientation": "provider_home_away", "scope": "post_match_only",
            "sets": {"1": {"home_aces": 3}, "2": {"home_aces": 4}},
        },
        "_tbt_tennisapi_pbp": {
            "schema": 1, "source": "tennisapi1", "event_id": "100",
            "observed_at_utc": NOW.isoformat(), "status": "available",
            "sets": 2, "games": 18, "points": 100,
            "games_with_explicit_server": 18,
            "games_with_explicit_winner": 18,
            "quality_status": "structural_only",
            "eligible_for_cdb_point_features": False,
        },
    }
    incoming = {
        "_tbt_statistics_by_set": {
            **old["_tbt_statistics_by_set"],
            "sets": {"1": {"home_aces": 1}},
        },
        "_tbt_tennisapi_pbp": {
            **old["_tbt_tennisapi_pbp"],
            "status": "unavailable", "sets": 0, "games": 0, "points": 0,
        },
    }
    merged = merge_provider_context(old, incoming)
    assert merged["_tbt_statistics_by_set"]["sets"] == {"1": {"home_aces": 3.0}, "2": {"home_aces": 4.0}}
    assert merged["_tbt_tennisapi_pbp"]["status"] == "available"
    assert merged["_tbt_tennisapi_pbp"]["points"] == 100


def test_pbp_wrapped_list_from_provider_is_counted_not_rejected(match_factory):
    from tbt.providers.tennisapi_extra import point_by_point_inventory

    sample = {
        "eventId": 100,
        "pointByPoint": [{"games": [{
            "score": {"serving": 1, "scoring": 2},
            "points": [{"home": 15}, {"home": 30}],
        }]}],
    }
    result = point_by_point_inventory(sample, event_id=100)
    assert result["sets"] == 1
    assert result["games"] == 1
    assert result["points"] == 2

    # Some events return an unwrapped list of sets.
    assert point_by_point_inventory(sample["pointByPoint"], event_id=100)["points"] == 2

    class WrappedProvider(Provider):
        def event_point_by_point(self, eid):
            self.calls.append("pbp")
            self.request_count += 1
            return sample

    match = match_for_extras(match_factory)
    p = WrappedProvider()
    result = enrich_event_extras(match, p, now=NOW)
    assert result["pbp"] == "available"
    assert result["changed"] is True
    assert match.provider_payload["_tbt_tennisapi_pbp"]["points"] == 2
    assert not needs_extras(match, now=NOW + timedelta(days=1))
    assert p.request_count == 3


def test_optional_pbp_204_and_empty_arrays_are_not_provider_errors(match_factory):
    from tbt.providers.tennisapi_extra import point_by_point_inventory

    for body in ({}, None, [], {"pointByPoint": []}, {"pointByPoint": None}):
        parsed = point_by_point_inventory(body, event_id=100)
        assert parsed["points"] == 0
        assert parsed["quality_status"] == "unavailable"

    class EmptyProvider(Provider):
        def event_point_by_point(self, eid):
            self.calls.append("pbp")
            self.request_count += 1
            return {"pointByPoint": []}

    match = match_for_extras(match_factory)
    outcome = enrich_event_extras(match, EmptyProvider(), now=NOW)
    assert outcome["pbp"] == "unavailable"
    assert not needs_extras(match, now=NOW + timedelta(days=7))
    assert needs_extras(match, now=NOW + timedelta(days=31))


def test_unsupported_pbp_shape_is_quarantined_not_reported_as_no_data(match_factory):
    class UnsupportedProvider(Provider):
        def event_point_by_point(self, eid):
            self.calls.append("pbp")
            self.request_count += 1
            return {"eventId": 100, "pointByPoint": "not-a-sets-list"}

    match = match_for_extras(match_factory)
    p = UnsupportedProvider()
    result = enrich_event_extras(match, p, now=NOW)
    assert result["pbp"] == "unsupported_shape"
    assert result["markets"] == "available"
    assert p.request_count == 3
    marker = match.provider_payload["_tbt_tennisapi_pbp"]
    assert marker["quality_status"] == "unsupported_shape"
    assert marker["eligible_for_cdb_point_features"] is False
    assert marker["points"] == 0
    assert not needs_extras(match, now=NOW + timedelta(days=7))
    assert needs_extras(match, now=NOW + timedelta(days=31))
    compact = minimize_provider_payload(match.provider_payload)
    assert compact["_tbt_tennisapi_pbp"] == marker
    assert verify_markers([match], {str(match.match_id): {
        "_tbt_tennisapi_pbp": marker,
    }}) == 1


def test_wrong_event_in_optional_pbp_is_hard_conflict(match_factory):
    class WrongEventProvider(Provider):
        def event_point_by_point(self, eid):
            self.calls.append("pbp")
            self.request_count += 1
            return {"eventId": 101, "pointByPoint": []}

    match = match_for_extras(match_factory)
    with pytest.raises(ProviderError, match="event ID mismatch"):
        enrich_event_extras(match, WrongEventProvider(), now=NOW)
    assert "_tbt_tennisapi_pbp" not in match.provider_payload
    assert match.provider_payload["_tbt_tennisapi_markets"]["status"] == "available"


def test_controlled_manual_extras_smoke_cannot_spend_bulk_quota_or_promote():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/data.yml").read_text()
    assert "ace-statistics|statistics|extras) ;;" in workflow
    assert '[[ "$mode" == "extras" ]]' in workflow
    assert '(( 10#$max_requests <= 30 ))' in workflow
    assert '[[ "$promote" == "false" ]]' in workflow
    assert 'Extras smoke cannot enable targeted-statistics' in workflow
    assert "python scripts/verify_tennisapi_extras.py" in workflow

def test_extras_batch_quota_is_handled_before_provider_rejection():
    """A normal 30-call smoke budget stop must not trip the 25-rejection gate."""
    source = (Path(__file__).resolve().parents[1] /
              "scripts/download_tennis_history.py").read_text()
    extras = source.split('elif args.mode == "extras":', 1)[1]
    loop = extras.split('            checkpoint(changed, True)', 1)[0]
    assert loop.index("except RequestBudgetExceeded:") < loop.index("except ProviderError as exc:")
    assert 'report["extras_rejected"] += 1' in loop
