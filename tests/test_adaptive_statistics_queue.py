"""No-provider regression coverage for the guarded adaptive statistics queue."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from adaptive_statistics_queue import AdaptiveStatisticsQueue


def _match(mid, tour="ATP", year=2025, *, ready=False):
    stats = (
        {"p1_service_points_won": 0.6, "p1_return_points_won": 0.4,
         "p2_service_points_won": 0.62, "p2_return_points_won": 0.38}
        if ready else {"p1_service_points_won": 0.6}
    )
    return SimpleNamespace(
        match_id=mid, tour=tour,
        scheduled_at=datetime(year, 6, 1, tzinfo=timezone.utc),
        stats=stats, is_completed=True,
    )


def _gain(values=0, quality=0, ace=0):
    return {"new_statistic_values": values,
            "new_quality_ready_rows": quality,
            "new_ace_df_values": ace}


def test_zero_spend_and_cache_gains_preserve_original_queue():
    rows = [_match(f"atp-{i}") if i % 2 == 0 else
            _match(f"wta-{i}", "WTA", 2026) for i in range(110)]
    queue = AdaptiveStatisticsQueue(rows)
    actual = []
    for row in queue:
        actual.append(row.match_id)
        queue.record(row, 0, _gain(8, 1, 4))
    assert actual == [row.match_id for row in rows]
    evidence = queue.summary()
    assert evidence["observed_paid_requests"] == 0
    assert evidence["online_adaptation_used"] is False
    assert evidence["adaptive_choices"] == 0
    assert evidence["remaining_rows"] == 0


def test_online_yield_moves_quota_away_from_zero_gain_cohort():
    # The deterministic legacy baseline alternates both cohorts. Paid
    # evidence, not the match year alone, must change subsequent selection.
    rows = []
    for i in range(160):
        rows.extend((_match(f"atp-{i}"), _match(f"wta-{i}", "WTA", 2026)))
    queue = AdaptiveStatisticsQueue(
        rows, {"atp:2025": {"quality_ready_rate": 0.81},
               "wta:2026": {"quality_ready_rate": 0.30}})
    seen = []
    for row in queue:
        seen.append(row.tour.lower())
        if row.tour.lower() == "atp":
            queue.record(row, 1, _gain(12, 1, 4))
        else:
            queue.record(row, 1, _gain())
    assert len(seen) == len(rows)
    assert len({row.match_id for row in rows}) == len(rows)
    # The adaptive phase exploits ATP yield, but some WTA is still sampled.
    assert seen[100:220].count("atp") >= 85
    assert seen[100:220].count("wta") >= 10
    assert set(seen) == {"atp", "wta"}
    evidence = queue.summary()
    assert evidence["observed_paid_requests"] == 320
    assert evidence["adaptive_choices"] > 0
    assert evidence["online_adaptation_used"] is True
    assert evidence["cohorts"]["wta:2026:serve_return"]["new_statistic_values"] == 0
    assert evidence["cohorts"]["atp:2025:serve_return"]["new_quality_ready_rows"] == 160
    assert evidence["baseline_choices"] >= 80


def test_feedback_uses_pre_call_missing_field_family():
    row = _match("changed", ready=False)
    queue = AdaptiveStatisticsQueue([row])
    selected = next(queue)
    selected.stats.update({
        "p1_return_points_won": 0.4, "p2_service_points_won": 0.61,
        "p2_return_points_won": 0.39})
    queue.record(selected, 1, _gain(3, 1))
    with pytest.raises(StopIteration):
        next(queue)
    assert queue.summary()["cohorts"]["atp:2025:serve_return"]["new_quality_ready_rows"] == 1


def test_ace_only_and_serve_return_gaps_are_distinct_cohorts():
    rows = [_match("serve"), _match("ace", ready=True)]
    queue = AdaptiveStatisticsQueue(rows)
    for row in queue:
        queue.record(row, 1, _gain(4))
    assert set(queue.summary()["cohorts"]) == {
        "atp:2025:serve_return", "atp:2025:ace_df"}


def test_nonselected_feedback_and_duplicate_queue_rows_fail_closed():
    row = _match("unique")
    with pytest.raises(ValueError, match="Duplicate statistics queue object"):
        AdaptiveStatisticsQueue([row, row])
    queue = AdaptiveStatisticsQueue([row])
    with pytest.raises(ValueError, match="does not match"):
        queue.record(row, 1, _gain(4))
    next(queue)
    with pytest.raises(ValueError, match="Negative"):
        queue.record(row, -1, _gain())


def test_priority_switches_after_a_previously_productive_cohort_drains():
    # A historical hot spot can be extremely productive early in a run and
    # then return empty provider responses. The algorithm must prefer the
    # consistently productive cohort instead of trusting lifetime averages.
    rows = []
    for i in range(650):
        rows.extend((_match(f"hot-{i}"), _match(f"stable-{i}", "WTA", 2026)))
    queue = AdaptiveStatisticsQueue(rows)
    selection = []
    hot_attempts = 0
    for _ in range(540):
        row = next(queue)
        if row.tour.lower() == "atp":
            hot_attempts += 1
            queue.record(row, 1, _gain(12, 1, 4) if hot_attempts <= 100 else _gain())
            selection.append("hot")
        else:
            queue.record(row, 1, _gain(4))
            selection.append("stable")

    assert selection[110:190].count("hot") >= 45
    assert selection[-120:].count("stable") >= 75
    report = queue.summary()
    hot = report["cohorts"]["atp:2025:serve_return"]
    stable = report["cohorts"]["wta:2026:serve_return"]
    assert report["selection_value_policy"] == "quality_ready_and_new_fields_recent_paid_window"
    assert report["recent_paid_match_window"] == 96
    assert hot["paid_requests"] > hot["recent_paid_requests"]
    assert hot["recent_paid_matches"] == 96
    assert stable["recent_paid_matches"] <= 96
    assert hot["recent_new_statistic_values"] < stable["recent_new_statistic_values"]
    assert report["baseline_choices"] >= 135  # >= one in every four
    assert report["observed_paid_requests"] == 540


def test_recent_score_uses_actual_provider_requests_including_retries():
    a = _match("one")
    b = _match("retry")
    queue = AdaptiveStatisticsQueue([a, b])
    assert next(queue) is a
    queue.record(a, 1, _gain(8, 1, 2))
    assert next(queue) is b
    queue.record(b, 4, _gain())
    report = queue.summary()
    row = report["cohorts"]["atp:2025:serve_return"]
    assert row["paid_requests"] == 5
    assert row["recent_paid_requests"] == 5
    assert row["recent_new_statistic_values"] == 8
    assert row["recent_new_quality_ready_rows"] == 1
    assert row["recent_paid_matches"] == 2
    assert report["adaptive_choices"] == 0  # normal warm-up


def test_recent_seasons_win_on_similar_paid_yield_but_history_can_outperform():
    # The 2026/2025/2024 focus is a *bounded* preference, not a hard
    # exclusion of high-yield 2023 history.
    rows = [_match("current", "WTA", 2026),
            _match("priority", "ATP", 2024),
            _match("history", "WTA", 2023)]
    q = AdaptiveStatisticsQueue(rows, {
        "wta:2026": {"quality_ready_rate": 0.71},
        "atp:2024": {"quality_ready_rate": 0.21},
        "wta:2023": {"quality_ready_rate": 0.29},
    })
    assert q.summary()["recency_reference_year"] == 2026
    assert q.summary()["recency_score_policy"] == (
        "bounded_latest_three_seasons_after_paid_yield"
    )
    assert q._score("atp:2024:serve_return") > q._score("wta:2023:serve_return")

    # The older cohort can still win if it is substantially more productive.
    for row in q:
        q.record(row, 1, _gain(24, 1, 4) if row.scheduled_at.year == 2023
                 else _gain(4))
    assert q._score("wta:2023:serve_return") > q._score("atp:2024:serve_return")


def test_recency_factor_never_bypasses_api_guard_or_paid_yield_warmup():
    rows = [_match(f"recent-{i}", "WTA", 2025) if i % 2 else
            _match(f"older-{i}", "ATP", 2022) for i in range(80)]
    q = AdaptiveStatisticsQueue(rows)
    for row in q:
        q.record(row, 0, _gain(5, 1, 2))
    assert q.summary()["observed_paid_requests"] == 0
    assert q.summary()["adaptive_choices"] == 0
    assert q.summary()["baseline_choices"] == 80


def test_audit_empty_provider_cohort_is_throttled_but_revisited():
    # The 26-27 Oct audit found repeated empty 2026 provider responses.
    # Preserve both tour/year exploration and cohort-local FIFO without
    # spending the fixed 25% baseline share on proven zero-value results.
    rows = []
    for i in range(600):
        rows.extend((
            _match(f"empty-{i}", "WTA", 2026),
            _match(f"productive-{i}", "ATP", 2024),
        ))
    q = AdaptiveStatisticsQueue(rows)
    seen = []
    for _ in range(360):
        row = next(q)
        seen.append(row.match_id)
        q.record(row, 1, _gain() if row.tour == "WTA" else _gain(16, 1, 4))
    report = q.summary()
    assert report["low_yield_baseline_deferrals"] > 0
    assert report["low_yield_baseline_samples"] > 0
    assert report["baseline_choices"] >= 90
    assert len(seen) == len(set(seen))
    # Revisit zero-yield cohorts, but do not require paid misses at the old frequency.
    assert 2 <= sum(x.startswith("empty-") for x in seen[200:360]) < 32
    assert q.LOW_YIELD_SAMPLE_EVERY == 12


def test_low_yield_probe_recovers_when_provider_starts_returning_values():
    # A previously empty cohort is sampled again and recovers priority
    # once its 96-match recent evidence becomes productive.
    rows = [_match(f"empty-{i}", "WTA", 2026) if i % 2 == 0
            else _match(f"other-{i}", "ATP", 2024) for i in range(800)]
    q = AdaptiveStatisticsQueue(rows)
    empty_calls = 0
    for _ in range(600):
        row = next(q)
        if row.tour == "WTA":
            empty_calls += 1
            q.record(row, 1, _gain() if empty_calls <= 40 else _gain(12, 1))
        else:
            q.record(row, 1, _gain(6))
    assert empty_calls > 40
    assert not q._low_yield("wta:2026:serve_return")
    assert q.summary()["low_yield_baseline_deferrals"] > 0


def test_low_yield_does_not_override_zero_paid_call_baseline():
    rows = [_match(f"a-{i}", "WTA", 2026) if i % 2 else
            _match(f"b-{i}", "ATP", 2024) for i in range(120)]
    q = AdaptiveStatisticsQueue(rows)
    observed = []
    for row in q:
        observed.append(row.match_id)
        q.record(row, 0, _gain())
    assert observed == [row.match_id for row in rows]
    assert q.summary()["low_yield_baseline_deferrals"] == 0
