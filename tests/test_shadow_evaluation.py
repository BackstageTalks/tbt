from datetime import datetime, timedelta, timezone

from tbt.schemas import MatchRecord
from tbt.services.shadow_evaluation import build_shadow_report, update_shadow_ledger


def _prediction(match_id, scheduled_at, p1, *, p1_id="a", p2_id="b"):
    return {
        "id": match_id,
        "event_id": f"event-{match_id}",
        "tour": "ATP",
        "surface": "hard",
        "tournament": "Test",
        "scheduled_at": scheduled_at.isoformat(),
        "player1": {"id": p1_id, "probability": p1},
        "player2": {"id": p2_id, "probability": 1 - p1},
    }


def test_shadow_snapshot_is_immutable_and_settles_from_canonical_history():
    now = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    scheduled = now + timedelta(hours=6)
    production = [_prediction("m1", scheduled, 0.60)]
    challenger = [_prediction("m1", scheduled, 0.72)]

    ledger = update_shadow_ledger(
        [],
        production_predictions=production,
        challenger_predictions=challenger,
        production_model_version="prod-v1",
        challenger_model_version="chal-v1",
        now=now,
    )
    assert len(ledger) == 1
    assert ledger[0]["production_player1_probability"] == 0.60
    assert ledger[0]["challenger_player1_probability"] == 0.72
    assert ledger[0]["status"] == "pending"

    # A later refresh must not overwrite the original pre-match snapshot.
    ledger = update_shadow_ledger(
        ledger,
        production_predictions=[_prediction("m1", scheduled, 0.51)],
        challenger_predictions=[_prediction("m1", scheduled, 0.99)],
        production_model_version="prod-v1",
        challenger_model_version="chal-v1",
        now=now + timedelta(hours=1),
    )
    assert len(ledger) == 1
    assert ledger[0]["production_player1_probability"] == 0.60
    assert ledger[0]["challenger_player1_probability"] == 0.72

    completed = MatchRecord(
        match_id="m1",
        tour="atp",
        scheduled_at=scheduled,
        player1_id="a",
        player1_name="A",
        player2_id="b",
        player2_name="B",
        winner_id="a",
        status="completed",
        surface="hard",
    )
    ledger = update_shadow_ledger(
        ledger,
        completed_matches=[completed],
        now=scheduled + timedelta(hours=2),
    )
    assert ledger[0]["status"] == "settled"
    assert ledger[0]["target_player1_win"] == 1
    assert ledger[0]["production_correct"] is True
    assert ledger[0]["challenger_correct"] is True


def test_shadow_never_captures_after_match_start():
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    scheduled = now - timedelta(minutes=1)
    ledger = update_shadow_ledger(
        [],
        production_predictions=[_prediction("late", scheduled, 0.6)],
        challenger_predictions=[_prediction("late", scheduled, 0.7)],
        production_model_version="prod-v1",
        challenger_model_version="chal-v1",
        now=now,
    )
    assert ledger == []


def _settled_rows(n):
    rows = []
    for i in range(n):
        target = i % 2
        rows.append({
            "match_id": f"m{i}",
            "production_model_version": "prod-v1",
            "challenger_model_version": "chal-v1",
            "status": "settled",
            "scheduled_at": datetime(2026, 10, 1 + (i % 3), 12, tzinfo=timezone.utc).isoformat(),
            "target_player1_win": target,
            "production_player1_probability": 0.60 if target else 0.40,
            "challenger_player1_probability": 0.80 if target else 0.20,
            "production_correct": True,
            "challenger_correct": True,
        })
    return rows


def test_shadow_promotion_review_requires_200_settled_matches():
    report_199 = build_shadow_report(
        _settled_rows(199),
        production_model_version="prod-v1",
        challenger_model_version="chal-v1",
    )
    assert report_199["cohort"]["settled"] == 199
    assert report_199["gate"]["minimum_matches_met"] is False
    assert report_199["gate"]["ready_for_promotion_review"] is False
    assert report_199["gate"]["automatic_promotion"] is False

    report_200 = build_shadow_report(
        _settled_rows(200),
        production_model_version="prod-v1",
        challenger_model_version="chal-v1",
    )
    assert report_200["cohort"]["settled"] == 200
    assert report_200["gate"]["minimum_matches_met"] is True
    assert report_200["gate"]["minimum_days_met"] is True
    assert report_200["gate"]["accuracy_not_worse"] is True
    assert report_200["gate"]["log_loss_better"] is True
    assert report_200["gate"]["brier_better"] is True
    assert report_200["gate"]["ece_not_worse"] is True
    assert report_200["gate"]["ready_for_promotion_review"] is True
    assert report_200["gate"]["automatic_promotion"] is False


def test_new_challenger_version_starts_a_separate_cohort():
    ledger = _settled_rows(200)
    ledger.append({
        **ledger[0],
        "match_id": "new",
        "challenger_model_version": "chal-v2",
    })
    report = build_shadow_report(
        ledger,
        production_model_version="prod-v1",
        challenger_model_version="chal-v2",
    )
    assert report["cohort"]["settled"] == 1
    assert report["gate"]["minimum_matches_met"] is False


def test_shadow_review_requires_three_distinct_utc_days():
    rows = _settled_rows(200)
    for row in rows:
        row["scheduled_at"] = datetime(2026, 10, 1, 12, tzinfo=timezone.utc).isoformat()
    report = build_shadow_report(
        rows,
        production_model_version="prod-v1",
        challenger_model_version="chal-v1",
    )
    assert report["cohort"]["settled"] == 200
    assert report["cohort"]["settled_utc_days"] == 1
    assert report["gate"]["minimum_matches_met"] is True
    assert report["gate"]["minimum_days_met"] is False
    assert report["gate"]["ready_for_promotion_review"] is False
