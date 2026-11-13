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


def test_cross_tour_evidence_survives_skewed_adaptive_recent_window():
    """The live adaptive collector over-samples one cohort after exploration."""
    gate = StatisticsAvailabilityCircuit()
    for match in (row("atp", 2024), row("wta", 2023), row("atp", 2026)):
        for _ in range(8):
            assert not gate.observe(match, "unavailable", 1,
                                    {"new_statistic_values": 0})
    # Last 120 matches are entirely ATP 2026, but prior independently sampled
    # ATP/WTA cohorts already proved the empty-route condition.
    for i in range(120):
        stopped = gate.observe(row("atp", 2026), "unavailable", 1,
                               {"new_statistic_values": 0})
        if stopped:
            break
    assert stopped
    assert gate.summary()["trigger"]["sampled_tours"] == 2
    assert gate.summary()["paid_matches_observed"] == 120


def _verified_no_gain_prior():
    # A real-like prior: 120 paid matches, 40 in each tour/year, zero
    # independently CDB-read-back new fields. Each record was validated
    # by adaptive_verified_prior before reaching this circuit.
    return {
        f"{tour}:{year}:serve_return": {
            "api_requests": 40,
            "new_fields": 0,
            "full_serve_return_rows": 0,
        }
        for tour, year in (("wta", 2026), ("atp", 2026), ("atp", 2025))
    }


def test_prior_verified_repeat_empty_route_uses_24_new_paid_matches():
    from pathlib import Path
    original = _verified_no_gain_prior()
    gate = StatisticsAvailabilityCircuit(verified_prior=original)
    assert gate.summary()["prior_zero_gain_recheck_eligible"] is True
    rows = (row("wta", 2026), row("atp", 2026), row("atp", 2025))
    before = [dict(m.stats) for m in rows]
    for index in range(23):
        assert not gate.observe(rows[index % 3], "unavailable", 1,
                                {"new_statistic_values": 0})
    assert gate.observe(rows[23 % 3], "unavailable", 1,
                        {"new_statistic_values": 0})
    result = gate.summary()
    assert result["paid_attempts_observed"] == 24
    assert result["trigger"]["reason"] == (
        "verified_prior_zero_gain_cross_tour_recheck")
    assert result["trigger"]["sampled_tours"] == 2
    assert result["trigger"]["sampled_cohorts"] == 3
    assert result["trigger"]["recent_unavailable_matches"] == 24
    assert [dict(m.stats) for m in rows] == before
    assert original == _verified_no_gain_prior()


def test_prior_without_cross_tour_independent_zero_evidence_keeps_full_guard():
    prior = _verified_no_gain_prior()
    prior["atp:2025:serve_return"]["new_fields"] = 1
    gate = StatisticsAvailabilityCircuit(verified_prior=prior)
    assert not gate.summary()["prior_zero_gain_recheck_eligible"]
    sampled(gate, 119)
    assert not gate.tripped
    assert gate.observe(row("atp", 2024), "unavailable", 1,
                        {"new_statistic_values": 0})
    assert gate.summary()["paid_attempts_observed"] == 120


def test_fresh_new_cdb_field_disables_short_recheck_for_current_run():
    gate = StatisticsAvailabilityCircuit(verified_prior=_verified_no_gain_prior())
    rows = (row("wta", 2026), row("atp", 2026), row("atp", 2025))
    for index in range(120):
        match = rows[index % 3]
        new = 1 if index == 1 else 0
        state = "enriched" if new else "unavailable"
        assert not gate.observe(match, state, 1,
                                {"new_statistic_values": new})
    assert not gate.tripped
    assert gate.summary()["paid_matches_observed"] == 120


def test_prior_recovery_requires_fresh_empty_bodies_and_three_cohorts():
    prior = _verified_no_gain_prior()
    gate = StatisticsAvailabilityCircuit(verified_prior=prior)
    # Other returned status and narrower new sample do not prove an
    # unchanged empty route. Leave the full independent circuit intact.
    for index in range(40):
        match = row("wta" if index % 2 == 0 else "atp", 2026,
                    "provider_event_not_finished" if index == 0
                    else "empty_whole_match_statistics")
        assert not gate.observe(match, "unavailable", 1,
                                {"new_statistic_values": 0})
    assert not gate.tripped
    assert gate.summary()["paid_matches_observed"] == 40


def test_cache_only_rows_never_shorten_paid_recheck():
    gate = StatisticsAvailabilityCircuit(verified_prior=_verified_no_gain_prior())
    matches = (row("wta", 2026), row("atp", 2026), row("atp", 2025))
    for index in range(100):
        assert not gate.observe(matches[index % 3], "unavailable", 0,
                                {"new_statistic_values": 0})
    for index in range(24):
        result = gate.observe(matches[index % 3], "unavailable", 1,
                              {"new_statistic_values": 0})
    assert result is True
    assert gate.summary()["paid_attempts_observed"] == 24


def test_main_collector_reuses_verified_prior_only_in_hourly_mode():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] /
              "scripts/download_tennis_history.py").read_text()
    assert "statistics_coverage_circuit = StatisticsAvailabilityCircuit(\n                    verified_prior=prior)" in source
