"""Offline tests: only persisted CDB evidence influences the next hourly queue."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
from adaptive_verified_prior import validated_prior
from adaptive_statistics_queue import AdaptiveStatisticsQueue


def verified(now, *, version=3):
    return {
        "schema": 1, "status": "VERIFIED_CDB_GAIN",
        "parser_version": version, "reported_at_utc": now.isoformat(),
        "requests_including_retries": 200, "persisted_new_statistic_values": 640,
        "cohorts": [
            {"cohort": "atp:2024:serve_return", "api_requests": 100,
             "new_fields": 600, "full_serve_return_rows": 40},
            {"cohort": "wta:2025:serve_return", "api_requests": 100,
             "new_fields": 40, "full_serve_return_rows": 0},
        ]
    }


def row(index, tour, year):
    return SimpleNamespace(
        match_id=str(index), tour=tour,
        scheduled_at=datetime(year, 7, 1, tzinfo=timezone.utc),
        stats={"p1_service_points_won": 0.6}
    )


def test_verified_prior_rebalances_early_without_extra_paid_calls():
    now = datetime.now(timezone.utc)
    prior = validated_prior(verified(now), parser_version=3, now=now)
    rows = [r for i in range(180) for r in
            (row(2*i, "ATP", 2024), row(2*i+1, "WTA", 2025))]
    q = AdaptiveStatisticsQueue(rows, verified_prior=prior)
    selections = []
    for _ in range(120):
        m = next(q)
        selections.append(m.tour)
        q.record(m, 0, {"new_statistic_values": 12, "new_quality_ready_rows": 1})
    assert selections.count("ATP") > selections.count("WTA")
    report = q.summary()
    assert report["observed_paid_requests"] == 0
    assert report["verified_prior_used"] is True
    assert report["baseline_choices"] >= 30


def test_invalid_old_parser_and_unverified_records_are_rejected():
    now = datetime.now(timezone.utc)
    data = verified(now)
    for bad in (
        {**data, "status": "PREPARED"},
        {**data, "parser_version": 4},
        {**data, "reported_at_utc": (now-timedelta(days=8)).isoformat()},
        {**data, "persisted_new_statistic_values": 777},
        {**data, "requests_including_retries": 1},
    ):
        with pytest.raises(ValueError):
            validated_prior(bad, parser_version=3, now=now)


def test_previous_cache_hits_never_count_as_verified_paid_success():
    now = datetime.now(timezone.utc)
    data = verified(now)
    data["cohorts"].append(
        {"cohort": "atp:2026:ace_df", "api_requests": 0,
         "new_fields": 20, "full_serve_return_rows": 0})
    data["persisted_new_statistic_values"] += 20
    with pytest.raises(ValueError, match="Impossible"):
        validated_prior(data, parser_version=3, now=now)
