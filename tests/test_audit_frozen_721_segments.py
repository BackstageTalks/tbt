"""No paid-provider, EV or model-selection regression tests for paired segments."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from tbt.services.frozen_721_research import (
    FROZEN_721_TAG, FROZEN_721_VERSION, FROZEN_721_MODEL_SHA256
)
from audit_frozen_721_segments import build_segment_report, MIN_CAPTURE_LEAD_SECONDS

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
