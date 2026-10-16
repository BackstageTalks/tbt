"""Regression tests: shadow Platt research never sees future outcomes when fitted."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from tbt.services.shadow_calibration_research import research_comparison


def _cohort(*, days=8, rows_per_day=80, settlement_delay_hours=10):
    start = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    rows = []
    for day in range(days):
        scheduled = start + timedelta(days=day)
        for i in range(rows_per_day):
            target = int((i * 13 + day * 7) % 10 < 6)
            p_candidate = 0.72 if i % 3 else 0.25
            p_champion = 0.64 if i % 3 else 0.33
            rows.append({
                "match_id": f"m-{day}-{i}",
                "production_model_version": "champion",
                "challenger_model_version": "candidate",
                "tour": "ATP" if i % 2 else "WTA",
                "scheduled_at": scheduled.isoformat(),
                "captured_at": (scheduled - timedelta(hours=2)).isoformat(),
                "settled_at": (scheduled + timedelta(hours=settlement_delay_hours)).isoformat(),
                "status": "settled",
                "target_player1_win": target,
                "production_player1_probability": p_champion,
                "challenger_player1_probability": p_candidate,
            })
    return rows


def test_predeclared_global_and_tour_platt_on_distinct_future_days():
    rows = _cohort()
    before = deepcopy(rows)
    report = research_comparison(rows, "champion", "candidate")
    assert report["status"] == "RESEARCH_EVALUATED"
    assert report["fit_rows"] == 320
    assert report["evaluation_rows"] == 320
    assert report["evaluation_utc_days"] == 4
    assert report["fit_utc_days"] == 4
    assert report["late_settlements_excluded"] == 0
    assert report["not_a_production_decision"] is True
    assert report["overall"]["candidate_global_platt_research"]["n"] == 320
    for tour in ("ATP", "WTA"):
        assert report["by_tour"][tour]["status"] == "RESEARCH_EVALUATED"
        assert report["by_tour"][tour]["candidate_tour_platt_research"]["n"] == 160
    assert rows == before  # No mutation of issued predictions or outcomes.


def test_future_settlements_are_excluded_from_calibration():
    rows = _cohort()
    future = (datetime(2026, 12, 1, tzinfo=timezone.utc)).isoformat()
    for row in rows:
        row["settled_at"] = future
    report = research_comparison(rows, "champion", "candidate")
    assert report["status"] == "INSUFFICIENT_TEMPORAL_EVIDENCE"
    assert report["fit_rows"] == 0
    assert report["late_settlements_excluded"] == 320
    assert report["reason"] == "insufficient_independently_settled_fit_or_future_evaluation"


def test_missing_timestamp_fails_closed():
    rows = _cohort()
    del rows[0]["settled_at"]
    report = research_comparison(rows, "champion", "candidate")
    assert report["reason"] == "missing_immutable_settlement_timestamp"


def test_too_few_days_fails_closed_without_fitting():
    report = research_comparison(_cohort(days=5), "champion", "candidate")
    assert report["reason"] == "fewer_than_six_settled_utc_days"


def test_other_model_pairs_do_not_leak_into_calibration():
    rows = _cohort()
    unrelated = deepcopy(rows)
    for row in unrelated:
        row["challenger_model_version"] = "different"
    report = research_comparison(rows + unrelated, "champion", "candidate")
    assert report["status"] == "RESEARCH_EVALUATED"
    assert report["fit_rows"] == 320
