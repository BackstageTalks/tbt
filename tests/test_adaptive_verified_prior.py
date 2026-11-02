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


@pytest.mark.parametrize(
    ("paid_calls", "paid_fields", "cache_fields"),
    [(100, 30, 0), (100, 30, 5), (0, 0, 5)],
    ids=["paid-only", "mixed", "cache-only"],
)
def test_producer_to_prior_to_queue_uses_only_paid_gain(
        paid_calls, paid_fields, cache_fields):
    from summarize_hourly_adaptive_cdb import build
    now = datetime.now(timezone.utc)
    download = {
        "requests_including_retries": paid_calls,
        "statistics_schema_version": 3,
        "statistics_data_value": {
            "new_statistic_values": paid_fields + cache_fields,
            "api_new_statistic_values": paid_fields,
            "new_quality_ready_rows": 2 if paid_fields else 0,
        },
        "statistics_adaptive_priority": {
            "policy": "bounded_online_observed_cdb_yield_v1",
            "observed_paid_requests": paid_calls,
            "selected_rows": 100,
            "baseline_choices": 100, "adaptive_choices": 0,
            "online_adaptation_used": False,
            "cohorts": {
                "atp:2024:serve_return": {
                    "paid_requests": 60 if paid_calls else 0,
                    "new_statistic_values": paid_fields,
                    "new_quality_ready_rows": 2 if paid_fields else 0,
                },
                "wta:2025:serve_return": {
                    "paid_requests": 40 if paid_calls else 0,
                    "new_statistic_values": 0, "new_quality_ready_rows": 0,
                },
            },
        },
    }
    readback = {
        "status": "VERIFIED" if paid_fields + cache_fields else "VERIFIED_NO_NEW_FIELDS",
        "persisted_new_statistic_values": paid_fields + cache_fields,
    }
    report = build(download, readback)
    report["reported_at_utc"] = now.isoformat()
    assert report["paid_new_statistic_values"] == paid_fields
    assert report["non_paid_new_statistic_values"] == cache_fields
    prior = validated_prior(report, parser_version=3, now=now)
    assert sum(c["new_fields"] for c in prior.values()) == paid_fields
    rows = [r for i in range(150) for r in
            (row(2*i, "ATP", 2024), row(2*i+1, "WTA", 2025))]
    queue = AdaptiveStatisticsQueue(rows, verified_prior=prior)
    for _ in range(60):
        candidate = next(queue)
        queue.record(candidate, 0, {"new_statistic_values": 10})
    summary = queue.summary()
    assert summary["observed_paid_requests"] == 0
    assert summary["verified_prior_used"] is (paid_calls > 0)
    assert summary["verified_prior_paid_requests_bounded"] == paid_calls


def test_schema2_rejects_inconsistent_and_missing_attribution():
    now = datetime.now(timezone.utc)
    data = verified(now)
    data.update(schema=2, paid_new_statistic_values=640,
                non_paid_new_statistic_values=5,
                persisted_new_statistic_values=645)
    assert validated_prior(data, parser_version=3, now=now)
    bad = [
        {**data, "paid_new_statistic_values": 639},
        {**data, "non_paid_new_statistic_values": 4},
        {**data, "paid_new_statistic_values": 646},
        {**data, "paid_new_statistic_values": True},
        {**data, "requests_including_retries": 0},
        {k: v for k, v in data.items() if k != "paid_new_statistic_values"},
    ]
    for item in bad:
        with pytest.raises(ValueError):
            validated_prior(item, parser_version=3, now=now)


def test_legacy_paid_only_prior_is_compatible_but_mixed_legacy_fails_closed():
    now = datetime.now(timezone.utc)
    legacy = verified(now)
    assert validated_prior(legacy, parser_version=3, now=now)
    mixed = {**legacy, "persisted_new_statistic_values": 645}
    with pytest.raises(ValueError, match="Paid CDB cohort fields mismatch"):
        validated_prior(mixed, parser_version=3, now=now)
    with pytest.raises(ValueError, match="Missing prior paid/non-paid"):
        validated_prior({**legacy, "schema": 2}, parser_version=3, now=now)


def test_cache_only_report_cannot_claim_paid_yield():
    from summarize_hourly_adaptive_cdb import build
    download = {
        "requests_including_retries": 0,
        "statistics_schema_version": 3,
        "statistics_data_value": {
            "new_statistic_values": 5, "api_new_statistic_values": 0,
        },
        "statistics_adaptive_priority": {
            "policy": "bounded_online_observed_cdb_yield_v1",
            "observed_paid_requests": 0,
            "selected_rows": 1, "baseline_choices": 1,
            "adaptive_choices": 0, "online_adaptation_used": False,
            "cohorts": {
                "atp:2024:serve_return": {
                    "paid_requests": 0, "new_statistic_values": 5,
                    "new_quality_ready_rows": 0,
                },
            },
        },
    }
    with pytest.raises(ValueError, match="Cohort paid gains"):
        build(download, {"status": "VERIFIED", "persisted_new_statistic_values": 5})
