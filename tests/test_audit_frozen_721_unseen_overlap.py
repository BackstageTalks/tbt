"""Proof that champion-unseen Oct 9–20 data are not automatically v7.2.1-unseen."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import audit_frozen_721_unseen_overlap as subject
from tbt.schemas import MatchRecord
from tbt.services.frozen_721_research import FROZEN_721_VERSION


CHAMP = "v201-20260925T204608601094Z"


def match(index, day, tour="atp"):
    scheduled = datetime(2026, 10, day, 12, tzinfo=timezone.utc)
    return MatchRecord(
        match_id=f"strict-{index}", tour=tour, scheduled_at=scheduled,
        player1_id=f"a{index}", player2_id=f"b{index}",
        player1_name=f"A{index}", player2_name=f"B{index}",
        winner_id=f"a{index}", surface="hard", status="finished",
    )


def metadata(*, consumed="2026-10-19T23:15:00+00:00"):
    return {
        "history_end": consumed, "evaluation_end": consumed,
        "selection_history_end": "2026-09-25T22:00:00+00:00",
        "selection_evaluation_end": "2026-10-19T23:15:00+00:00",
    }


def report(*, cutoff="2026-10-19T23:15:00+00:00"):
    return {
        "evaluation_governance": {"holdout_fingerprint": "pinned-selection"},
        "promotion_decision": {
            "candidate_version": FROZEN_721_VERSION,
            "production_version": CHAMP,
            "promotion_requested": False,
            "holdout_period": {
                "start": "2026-09-26T00:10:00+00:00",
                "end": cutoff,
            },
        },
    }


def provenance(*, meta=None, data=None):
    model = SimpleNamespace(version=FROZEN_721_VERSION, metadata=meta or metadata())
    return subject.candidate_provenance(model, data or report(), CHAMP)


def test_four_partitions_preserve_champion_rows_and_reject_reused_721_holdout():
    now = datetime(2026, 10, 21, 8, tzinfo=timezone.utc)
    matches = [
        match(1, 8), match(2, 9), match(3, 19, "wta"),
        match(4, 20, "wta"), match(5, 21),
    ]
    champion = {"eligibility_cutoff_day_utc": "2026-10-08",
                "eligible_unseen_rows": 3}
    proof = provenance()
    result = subject.partition_champion_unseen(matches, champion, proof, as_of=now)
    assert result["champion_unseen_reported"] == 3
    assert result["overlap_with_frozen_721_consumption_or_evaluation"]["rows"] == 2
    assert result["strictly_after_all_frozen_721_consumption"]["rows"] == 1
    assert result["strictly_after_all_frozen_721_consumption"]["by_tour"] == {"wta": 1}
    assert result["row_count_verified"] is True
    assert result["can_fit_721_calibration_from_champion_unseen_rows"] is False
    assert result["candidate_fresh_rows_are_not_prospective_predictions"] is True
    assert result["top_odds_roi_proven"] is False
    assert result["provider_requests"] == 0
    assert result["production_mutated"] is False


def test_candidate_governance_requires_exact_frozen_model_and_champion():
    wrong_model = SimpleNamespace(version="v7.2.1-other", metadata=metadata())
    with pytest.raises(ValueError, match="Unexpected frozen candidate"):
        subject.candidate_provenance(wrong_model, report(), CHAMP)
    data = report()
    data["promotion_decision"]["production_version"] = "unknown"
    with pytest.raises(ValueError, match="provenance mismatch"):
        provenance(data=data)
    data = report()
    data["promotion_decision"]["promotion_requested"] = True
    with pytest.raises(ValueError, match="provenance mismatch"):
        provenance(data=data)
    data = report()
    data["evaluation_governance"].pop("holdout_fingerprint")
    with pytest.raises(ValueError, match="provenance mismatch"):
        provenance(data=data)


@pytest.mark.parametrize("field", ["history_end", "evaluation_end", "selection_evaluation_end"])
def test_missing_or_naive_model_cutoff_fails_closed(field):
    values = metadata()
    values[field] = "2026-10-19T23:15:00" if field != "history_end" else None
    with pytest.raises(ValueError, match="provenance"):
        provenance(meta=values)


def test_entire_utc_day_after_latest_consumption_is_needed():
    now = datetime(2026, 10, 21, 8, tzinfo=timezone.utc)
    matches = [match(1, 19), match(2, 20)]
    data = provenance(meta=metadata(consumed="2026-10-20T00:30:00+00:00"))
    result = subject.partition_champion_unseen(
        matches, {"eligibility_cutoff_day_utc": "2026-10-08",
                  "eligible_unseen_rows": 2}, data, as_of=now
    )
    assert result["candidate_consumed_cutoff_utc_day"] == "2026-10-20"
    assert result["strictly_after_all_frozen_721_consumption"]["rows"] == 0


def test_disagreed_readiness_or_illogical_provenance_blocks_any_claim():
    now = datetime(2026, 10, 21, 8, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="disagrees"):
        subject.partition_champion_unseen(
            [match(1, 20)],
            {"eligibility_cutoff_day_utc": "2026-10-08", "eligible_unseen_rows": 4544},
            provenance(), as_of=now,
        )
    with pytest.raises(ValueError, match="precedes"):
        subject.partition_champion_unseen(
            [match(1, 20)],
            {"eligibility_cutoff_day_utc": "2026-10-21", "eligible_unseen_rows": 0},
            provenance(), as_of=now,
        )


def test_utc_requires_explicit_timezone():
    with pytest.raises(ValueError, match="Naive frozen candidate"):
        subject.strict_utc("2026-10-20T00:00:00", "test")
