"""Unproductive provider response guard; all tests are offline/zero paid calls."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from statistics_availability_circuit import StatisticsAvailabilityCircuit


def row(tour, year, reason="empty_whole_match_statistics"):
    return SimpleNamespace(
        tour=tour,
        scheduled_at=datetime(year, 7, 1, tzinfo=timezone.utc),
        stats={"p1_service_points_won": 0.68},
        provider_payload={"_tbt_statistics": {"reason": reason}},
    )


def sampled(circuit, count, *, status="unavailable", gain=0, paid=1):
    """Draw both tours and >=3 independently sampled year/tour cohorts."""
    rows = (row("atp", 2024), row("wta", 2023), row("atp", 2026))
    for index in range(count):
        match = rows[index % len(rows)]
        assert circuit.observe(match, status, paid, {"new_statistic_values": gain}) is (
            circuit.tripped
        )


def test_cross_tour_empty_paid_route_stops_before_wasting_full_daily_budget():
    gate = StatisticsAvailabilityCircuit()
    sampled(gate, 119)
    assert not gate.tripped
    assert gate.observe(row("atp", 2024), "unavailable", 1,
                        {"new_statistic_values": 0})
    evidence = gate.summary()
    assert evidence["tripped"]
    assert evidence["paid_attempts_observed"] == 120
    assert evidence["trigger"]["recent_unavailable_matches"] == 120
    assert evidence["trigger"]["sampled_cohorts"] == 3
    assert evidence["trigger"]["sampled_tours"] == 2
    assert evidence["trigger"]["recent_new_canonical_fields"] == 0
    assert evidence["trigger"]["scope"] == "current_high_yield_statistics_run_only"


def test_single_tour_or_single_cohort_cannot_stop_paid_collection():
    for matches in (
        [row("atp", 2026) for _ in range(170)],
        [row("atp", 2026), row("wta", 2026)] * 85,
        [row("atp", 2024), row("wta", 2023), row("wta", 2024)] * 2
        + [row("atp", 2026)] * 164,
    ):
        gate = StatisticsAvailabilityCircuit()
        for match in matches:
            assert not gate.observe(match, "unavailable", 1,
                                    {"new_statistic_values": 0})
        assert gate.summary()["tripped"] is False


def test_cache_hits_do_not_count_as_paid_provider_evidence():
    gate = StatisticsAvailabilityCircuit()
    for _ in range(500):
        assert not gate.observe(row("atp", 2026), "unavailable", 0,
                                {"new_statistic_values": 0})
    assert gate.summary()["paid_matches_observed"] == 0
    sampled(gate, 120)
    assert gate.tripped
    assert gate.summary()["paid_attempts_observed"] == 120


def test_productive_route_not_stopped_even_with_many_empty_responses():
    gate = StatisticsAvailabilityCircuit()
    rows = (row("atp", 2024), row("wta", 2023), row("atp", 2026))
    for index in range(350):
        added = 1 if index % 80 == 0 else 0
        match = rows[index % 3]
        status = "enriched" if added else "unavailable"
        assert not gate.observe(match, status, 1,
                                {"new_statistic_values": added})
    assert not gate.tripped
    assert gate.summary()["paid_matches_observed"] == 350


def test_unknown_or_identity_unavailable_not_misclassified_as_empty_statistics():
    gate = StatisticsAvailabilityCircuit()
    rows = [row("atp", 2024), row("wta", 2023), row("atp", 2026)]
    for i in range(150):
        match = rows[i % 3]
        if i % 10 == 0:
            match = row(match.tour, match.scheduled_at.year,
                        "provider_event_not_finished")
        assert not gate.observe(match, "unavailable", 1,
                                {"new_statistic_values": 0})
    assert gate.summary()["tripped"] is False


def test_all_supported_empty_classifications_trigger_and_canonical_unchanged():
    gate = StatisticsAvailabilityCircuit()
    reasons = ["no_supported_fields", "missing_unambiguous_all_period",
               "empty_whole_match_statistics"]
    matches = [row("atp", 2024, reasons[0]), row("wta", 2023, reasons[1]),
               row("atp", 2026, reasons[2])]
    before = [dict(m.stats) for m in matches]
    for i in range(120):
        gate.observe(matches[i % 3], "unavailable", 2, {"new_statistic_values": 0})
    assert gate.tripped
    assert gate.summary()["trigger"]["recent_paid_attempts"] == 240
    assert [m.stats for m in matches] == before


def test_malformed_paid_count_and_fake_gain_fail_closed():
    gate = StatisticsAvailabilityCircuit()
    match = row("atp", 2025)
    for paid in (-1, True, 1.5, "2"):
        with pytest.raises(ValueError):
            gate.observe(match, "unavailable", paid, {"new_statistic_values": 0})
    for gain in (-1, True, 2.5):
        with pytest.raises(ValueError):
            gate.observe(match, "unavailable", 1, {"new_statistic_values": gain})
    assert gate.summary()["paid_matches_observed"] == 0


def test_recent_window_allows_recovery_and_late_outage():
    gate = StatisticsAvailabilityCircuit()
    rows = (row("atp", 2024), row("wta", 2023), row("atp", 2026))
    for i in range(150):
        assert not gate.observe(rows[i % 3], "enriched", 1,
                                {"new_statistic_values": 1})
    for i in range(120):
        gate.observe(rows[i % 3], "unavailable", 1, {"new_statistic_values": 0})
    assert gate.tripped
    assert gate.summary()["paid_matches_observed"] <= 270
