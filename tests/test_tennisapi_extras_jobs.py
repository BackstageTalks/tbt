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
