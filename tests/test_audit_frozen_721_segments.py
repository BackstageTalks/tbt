"""Frozen 721 descriptive error breakdowns: identity, size and anti-leakage tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

import audit_frozen_721_segments as audit
from tbt.services.frozen_721_research import (
    FROZEN_721_TAG, FROZEN_721_VERSION, FROZEN_721_MODEL_SHA256,
)

PROD = "v201-20260925T204608601094Z"


def payload():
    start = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    rows = []
    for i, (tour, surface, pprod, p721, target) in enumerate([
        ("ATP", "hard", 0.64, 0.72, 1),
        ("ATP", "clay", 0.76, 0.65, 0),
        ("WTA", "grass", 0.24, 0.83, 0),
        ("WTA", "indoor_hard", 0.53, 0.51, 1),
        ("WTA", "hard", 0.42, 0.94, 1),
    ]):
        kickoff = start + timedelta(hours=i)
        rows.append({
            "schema": 1, "match_id": f"match-{i}", "event_id": f"event-{i}",
            "tour": tour, "surface": surface, "player1_id": "a",
            "player2_id": "b",
            "production_model_version": PROD,
            "challenger_model_version": FROZEN_721_VERSION,
            "production_player1_probability": pprod,
            "challenger_player1_probability": p721,
            "scheduled_at": kickoff.isoformat(),
            "captured_at": (kickoff - timedelta(hours=3)).isoformat(),
            "settled_at": (kickoff + timedelta(hours=5)).isoformat(),
            "status": "settled",
            "target_player1_win": target,
            "result_winner_id": "a" if target else "b",
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


def test_paired_descriptive_metrics_do_not_rewrite_originals():
    data = payload()
    before = deepcopy(data)
    report = audit.segment_diagnostics(data, production_version=PROD)
    assert data == before
    assert report["full_cohort"]["n"] == 5
    assert report["by_tour"]["ATP"]["n"] == 2
    assert report["by_tour"]["WTA"]["n"] == 3
    assert report["by_surface"]["hard"]["n"] == 2
    assert report["by_surface"]["indoor_hard"]["n"] == 1
    assert report["by_tour_surface"]["WTA/indoor_hard"]["n"] == 1
    assert report["by_candidate_confidence"]["50-59%"]["n"] == 1
    assert report["by_candidate_confidence"]["60-69%"]["n"] == 1
    assert report["by_candidate_confidence"]["70-79%"]["n"] == 1
    assert report["by_candidate_confidence"]["80-89%"]["n"] == 1
    assert report["by_candidate_confidence"]["90-100%"]["n"] == 1
    full = report["full_cohort"]
    assert full["champion"]["correct"] == 3
    assert full["frozen_721"]["correct"] == 3
    assert full["paired_outcomes"] == {
        "both_correct": 1,
        "champion_only_correct": 2,
        "frozen_721_only_correct": 2,
        "both_wrong": 0,
        "discordant": 4,
    }
    assert sum(report["by_tour"][tour]["n"] for tour in ("ATP", "WTA")) == 5
    assert full["sample_size_flag"] == "DESCRIPTIVE_ONLY_SMALL_N"
    assert report["limitations"]["significance_or_promotion_inferred"] is False
    assert report["limitations"]["feature_ablation_not_possible_from_probability_only_ledger"]
    assert report["automatic_promotion"] is False
    assert report["provider_requests"] == 0
    assert report["production_mutated"] is False
    assert not any("odds" in k.lower() or "value" in k.lower() or "roi" in k.lower()
                   for k in (" ".join(report["full_cohort"].keys()),))
    json.dumps(report, allow_nan=False)


def test_pending_and_void_are_not_scored_or_used_to_select_groups():
    data = payload()
    pending = dict(data["rows"][0], match_id="pending",
                   event_id="pending", status="pending")
    pending.pop("settled_at")
    pending.pop("target_player1_win")
    pending["result_winner_id"] = None
    void = dict(data["rows"][1], match_id="void",
                event_id="void", status="void")
    void.pop("target_player1_win")
    void.pop("settled_at")
    void["result_winner_id"] = None
    data["rows"].extend([pending, void])
    r = audit.segment_diagnostics(data, production_version=PROD)
    assert r["full_cohort"]["n"] == 5
    assert r["cohort_after_duplicate_exclusion"]["pending"] == 1
    assert r["cohort_after_duplicate_exclusion"]["void"] == 1


def test_repeated_provider_event_keeps_only_first_and_retains_audit_count():
    data = payload()
    later = dict(data["rows"][0],
                 match_id="rescheduled-id",
                 captured_at=(datetime.fromisoformat(data["rows"][0]["captured_at"])
                              + timedelta(minutes=15)).isoformat(),
                 status="pending")
    later.pop("settled_at")
    later.pop("target_player1_win")
    later["result_winner_id"] = None
    data["rows"].append(later)
    before = deepcopy(data)
    report = audit.segment_diagnostics(data, production_version=PROD)
    assert data == before
    assert report["full_cohort"]["n"] == 5
    assert report["cohort_before_duplicate_exclusion"]["pending"] == 1
    assert report["cohort_after_duplicate_exclusion"]["pending"] == 0
    assert report["cohort_after_duplicate_exclusion"]["excluded"] == 1


@pytest.mark.parametrize("corruption", ["foreign_candidate", "post_kickoff", "outcome_on_pending", "wrong_champion"])
def test_provenance_corruptions_fail_before_any_metric(corruption):
    data = payload()
    if corruption == "foreign_candidate":
        data["rows"][0]["challenger_model_version"] = "v7.2.2-foreign"
    elif corruption == "post_kickoff":
        data["rows"][0]["captured_at"] = data["rows"][0]["scheduled_at"]
    elif corruption == "outcome_on_pending":
        data["rows"][0]["status"] = "pending"
        data["rows"][0].pop("settled_at")
    else:
        data["source"]["production_version"] = "other"
    with pytest.raises(ValueError):
        audit.segment_diagnostics(data, production_version=PROD)


def test_zero_settled_is_explicit_and_has_no_nan():
    data = payload()
    for row in data["rows"]:
        row["status"] = "pending"
        row.pop("settled_at")
        row.pop("target_player1_win")
        row["result_winner_id"] = None
    result = audit.segment_diagnostics(data, production_version=PROD)
    assert result["full_cohort"]["n"] == 0
    assert result["by_tour"]["ATP"]["frozen_721"]["accuracy"] is None
    assert result["by_tour"]["WTA"]["champion"]["accuracy_ci95_wilson"] is None
    assert sum(z["n"] for z in result["by_candidate_confidence"].values()) == 0
    json.dumps(result, allow_nan=False)


def test_missing_or_unsupported_surface_never_invents_indoor_provenance():
    data = payload()
    data["rows"][0]["surface"] = None
    data["rows"][1]["surface"] = "mystery"
    result = audit.segment_diagnostics(data, production_version=PROD)
    assert result["by_surface"]["unknown"]["n"] == 2
    assert result["by_surface"]["indoor_hard"]["n"] == 1
