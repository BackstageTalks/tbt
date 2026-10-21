"""No paid-provider, EV or model-selection regression tests for paired segments."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from tbt.services.frozen_721_research import (
    FROZEN_721_TAG, FROZEN_721_VERSION, FROZEN_721_MODEL_SHA256
)
from audit_frozen_721_segments import (
    build_segment_report, MIN_CAPTURE_LEAD_SECONDS, VIP_PROBABILITY_TIERS,
)

PROD = "v201-20260925T204608601094Z"
START = datetime(2026, 10, 21, 15, tzinfo=timezone.utc)


def sample(*, count=4):
    rows = []
    for i in range(count):
        when = START + timedelta(hours=i)
        first = i % 2 == 0
        rows.append({
            "match_id": f"match-{i}", "event_id": f"event-{i}",
            "tour": "ATP" if first else "WTA",
            "surface": "clay" if first else "hard",
            "player1_id": f"a-{i}", "player2_id": f"b-{i}",
            "production_model_version": PROD,
            "challenger_model_version": FROZEN_721_VERSION,
            "scheduled_at": when.isoformat(),
            "captured_at": (when - timedelta(hours=2)).isoformat(),
            "settled_at": (when + timedelta(hours=6)).isoformat(),
            "production_player1_probability": .8 if first else .58,
            "challenger_player1_probability": .4 if first else .76,
            "target_player1_win": 1 if first else 0,
            "result_winner_id": f"a-{i}" if first else f"b-{i}",
            "status": "settled",
        })
    return {
        "source": {
            "candidate_tag": FROZEN_721_TAG,
            "candidate_version": FROZEN_721_VERSION,
            "candidate_model_sha256": FROZEN_721_MODEL_SHA256,
            "production_version": PROD,
            "provider_requests": 0,
        },
        "rows": rows,
    }


def test_segments_compare_exact_paired_outcomes_without_any_ev_or_odds():
    payload = sample()
    original = deepcopy(payload)
    report = build_segment_report(payload)
    assert payload == original
    assert report["eligible_settled"] == 4
    assert report["settled_total"] == 4
    assert report["by_tour"]["ATP"]["n"] == 2
    assert report["by_tour"]["WTA"]["n"] == 2
    assert report["by_surface"]["clay"]["n"] == 2
    assert report["by_surface"]["hard"]["n"] == 2
    assert report["by_tour_and_surface"]["ATP/clay"]["n"] == 2
    assert report["by_champion_confidence"]["80-100"]["n"] == 2
    assert report["by_champion_confidence"]["50-60"]["n"] == 2
    assert report["overall"]["champion"]["correct"] == 2
    assert report["overall"]["candidate_721"]["correct"] == 0
    assert report["overall"]["paired_diagnostics"]["champion_only_correct"] == 2
    assert report["overall"]["paired_diagnostics"]["candidate_only_correct"] == 0
    assert report["overall"]["paired_diagnostics"]["paired_accuracy_difference_ci95"] is None
    assert report["automatic_model_selection"] is False
    assert report["automatic_promotion"] is False
    assert report["calibrator_fit_performed"] is False
    assert report["historical_4544_rescoring_used"] is False
    assert report["production_mutated"] is False
    assert report["provider_requests"] == 0
    assert not any(
        key in json.dumps(report).lower()
        for key in ("expected_value", "roi", "betting_odds", "profit_", "value_filter")
    )


def test_predeclared_wall_clock_lead_guard_quarantines_near_start():
    p = sample(count=2)
    when = START + timedelta(hours=1)
    p["rows"][1]["captured_at"] = (
        when - timedelta(seconds=MIN_CAPTURE_LEAD_SECONDS - 1)
    ).isoformat()
    report = build_segment_report(p)
    assert report["settled_total"] == 2
    assert report["quarantined_capture_less_than_15m_before_start"] == 1
    assert report["eligible_settled"] == 1
    assert report["by_tour"]["WTA"]["n"] == 0
    assert report["by_champion_confidence"]["50-60"]["n"] == 0


def test_contradictory_artifact_or_post_start_evidence_fails_closed():
    p = sample(count=1)
    p["source"]["candidate_model_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="wrong_frozen_721_artifact"):
        build_segment_report(p)
    p = sample(count=1)
    p["rows"][0]["captured_at"] = p["rows"][0]["scheduled_at"]
    with pytest.raises(ValueError, match="prediction_not_captured_before_match"):
        build_segment_report(p)


def test_pending_future_and_duplicate_snapshots_never_inflate_scored_rows():
    p = sample(count=1)
    pending = deepcopy(p["rows"][0])
    pending.update(
        match_id="later-hash", captured_at=(
            START - timedelta(hours=1)).isoformat(),
        status="pending", result_winner_id=None,
    )
    pending.pop("settled_at")
    pending.pop("target_player1_win")
    p["rows"].append(pending)
    report = build_segment_report(p)
    assert report["cohort_status_counts"]["excluded"] == 1
    assert report["settled_total"] == 1
    assert report["eligible_settled"] == 1
    assert report["overall"]["n"] == 1


def test_missing_or_ambiguous_settled_identity_never_enters_scoreboard():
    p = sample(count=1)
    p["rows"][0]["result_winner_id"] = "outsider"
    with pytest.raises(ValueError, match="settled_winner_identity_mismatch"):
        build_segment_report(p)
    p = sample(count=2)
    p["rows"][1]["event_id"] = p["rows"][0]["event_id"]
    with pytest.raises(ValueError, match="Conflicting provider event"):
        build_segment_report(p)


def test_accuracy_interval_only_with_thirty_deduplicated_rows():
    p = sample(count=30)
    report = build_segment_report(p)
    assert report["eligible_settled"] == 30
    assert report["overall"]["paired_diagnostics"]["paired_accuracy_difference_ci95"] is not None
    assert all(-1 <= x <= 1 for x in
               report["overall"]["paired_diagnostics"]["paired_accuracy_difference_ci95"])


def test_vip_raw_confidence_cascade_keeps_all_above_first_sufficient_tier():
    p = sample(count=6)
    for row, probability in zip(p["rows"], (.95, .84, .79, .77, .72, .69)):
        row["challenger_player1_probability"] = probability
    result = build_segment_report(p)["candidate_vip_raw_confidence_scorecard"]
    assert result["fixed_tiers"] == [.80, .78, .75, .70]
    assert result["days_with_captured_cohort"] == 1
    assert result["days_with_3plus_raw_qualifiers"] == 1
    day = next(iter(result["daily"].values()))
    assert day["applied_raw_confidence_floor"] == .78
    assert day["selected"] == 3
    assert result["all_selected"]["settled"] == 3
    assert result["core_80_plus"]["settled"] == 2
    assert result["fallback_below_80"]["settled"] == 1
    assert result["all_selected"]["target_80_evidenced"] is False
    assert result["by_tour"]["ATP"]["selected"]["settled"] == 2
    assert result["by_tour"]["WTA"]["selected"]["settled"] == 1
    assert result["model_promoted"] is False
    assert result["provider_requests"] == 0
    assert "odds" in str(result["limitations"]).lower()


def test_vip_raw_confidence_above_three_is_uncapped():
    p = sample(count=6)
    for row in p["rows"]:
        row["challenger_player1_probability"] = .85
    data = build_segment_report(p)["candidate_vip_raw_confidence_scorecard"]
    assert data["all_selected"]["offered_before_settlement"] == 6
    assert data["core_80_plus"]["settled"] == 6
    assert data["fallback_below_80"]["settled"] == 0
    assert next(iter(data["daily"].values()))["applied_raw_confidence_floor"] == .80


def test_vip_raw_confidence_daily_shortfall_stops_at_70_and_no_post_selection_labels():
    p = sample(count=3)
    for row, probability in zip(p["rows"], (.81, .77, .69)):
        row["challenger_player1_probability"] = probability
    result = build_segment_report(p)["candidate_vip_raw_confidence_scorecard"]
    day = next(iter(result["daily"].values()))
    assert day["applied_raw_confidence_floor"] == .70
    assert day["selected"] == 2
    assert day["below_three"] is True
    assert result["all_selected"]["offered_before_settlement"] == 2
    assert result["fixed_cumulative_thresholds"]["0.7"]["offered_before_settlement"] == 2


def test_vip_raw_confidence_pending_consumes_capacity_but_not_hit_rate():
    p = sample(count=5)
    for row in p["rows"]:
        row["challenger_player1_probability"] = .86
    pending = p["rows"][0]
    pending["status"] = "pending"
    pending["target_player1_win"] = None
    pending["result_winner_id"] = None
    pending.pop("settled_at")
    result = build_segment_report(p)["candidate_vip_raw_confidence_scorecard"]
    assert result["all_selected"]["offered_before_settlement"] == 5
    assert result["all_selected"]["settled"] == 4
    assert result["all_selected"]["pending_or_void"] == 1
    assert result["all_selected"]["hit_rate"] == .5
    assert result["all_selected"]["hit_rate_ci95_wilson"] is not None
    assert result["all_selected"]["target_80_evidenced"] is False


def test_vip_raw_confidence_does_not_score_near_start_and_uses_slovak_local_day():
    p = sample(count=2)
    # October 21st 03:00 UTC = 05:00 Bratislava, on previous betting day.
    # 05:00 UTC = 07:00 Bratislava, on new betting day.
    p["rows"][0]["scheduled_at"] = "2026-10-21T03:00:00+00:00"
    p["rows"][0]["captured_at"] = "2026-10-21T01:00:00+00:00"
    p["rows"][0]["settled_at"] = "2026-10-21T09:00:00+00:00"
    p["rows"][1]["scheduled_at"] = "2026-10-21T05:00:00+00:00"
    p["rows"][1]["captured_at"] = "2026-10-21T03:00:00+00:00"
    p["rows"][1]["settled_at"] = "2026-10-21T11:00:00+00:00"
    p["rows"][0]["challenger_player1_probability"] = .82
    p["rows"][1]["challenger_player1_probability"] = .78
    daily = build_segment_report(p)["candidate_vip_raw_confidence_scorecard"]
    assert set(daily["daily"]) == {"2026-10-20", "2026-10-21"}
    # Quarantine the second prediction, do not infer an outcome from its confidence.
    p["rows"][1]["captured_at"] = "2026-10-21T04:50:01+00:00"
    result = build_segment_report(p)
    assert result["quarantined_capture_less_than_15m_before_start"] == 1
    assert result["candidate_vip_raw_confidence_scorecard"]["days_with_captured_cohort"] == 1


def test_vip_raw_confidence_synthetic_100pct_does_not_certify_80_from_small_n():
    p = sample(count=10)
    for row in p["rows"]:
        row["challenger_player1_probability"] = .87 if row["target_player1_win"] else .13
    result = build_segment_report(p)["candidate_vip_raw_confidence_scorecard"]
    assert result["all_selected"]["hit_rate"] == 1.0
    assert result["all_selected"]["settled"] == 10
    assert result["all_selected"]["target_80_evidenced"] is False
    assert result["all_selected"]["target_87_evidenced"] is False


def test_excluded_duplicate_shadow_does_not_fake_three_daily_80pct_candidates():
    p = sample(count=2)
    for row in p["rows"]:
        row["challenger_player1_probability"] = .90
    duplicate = deepcopy(p["rows"][0])
    duplicate["match_id"] = "later-schedule-hash"
    duplicate["captured_at"] = (START - timedelta(hours=1)).isoformat()
    duplicate["challenger_player1_probability"] = .99
    duplicate["status"] = "pending"
    duplicate["target_player1_win"] = None
    duplicate["result_winner_id"] = None
    duplicate.pop("settled_at")
    p["rows"].append(duplicate)
    report = build_segment_report(p)
    score = report["candidate_vip_raw_confidence_scorecard"]
    assert report["cohort_status_counts"]["excluded"] == 1
    assert score["all_selected"]["offered_before_settlement"] == 2
    assert score["days_with_3plus_raw_qualifiers"] == 0
    assert next(iter(score["daily"].values()))["below_three"] is True
