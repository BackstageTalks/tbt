"""Regression coverage for completed-day and preview-safe promotion governance."""
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from model_promotion_readiness import build_readiness
from pipeline import _holdout_already_used
from tbt.schemas import MatchRecord
from tbt.services.training import _eligible_evaluation


CLOCK = datetime(2026, 10, 8, 14, tzinfo=timezone.utc)


class Champion:
    version = "champion-v1"
    metadata = {"history_end": "2026-10-04T22:00:00+00:00"}


def _match(day):
    return MatchRecord(
        match_id=f"m-{day}",
        tour="atp" if day % 2 else "wta",
        scheduled_at=datetime(2026, 10, day, 12, tzinfo=timezone.utc),
        player1_id=f"a-{day}",
        player2_id=f"b-{day}",
        player1_name=f"A {day}",
        player2_name=f"B {day}",
        winner_id=f"a-{day}",
        surface="hard",
    )


def _frame(*days):
    return pd.DataFrame({
        "match_id": [f"m-{day}" for day in days],
        "scheduled_at": pd.to_datetime(
            [f"2026-10-{day:02d}T12:00:00Z" for day in days], utc=True
        ),
    })


def test_readiness_excludes_current_and_future_utc_days():
    report = build_readiness(
        [_match(day) for day in (5, 6, 7, 8)],
        production_model=Champion(),
        minimum_gate_rows=3,
        target_rows=4,
        minimum_days=3,
        as_of=CLOCK,
    )
    assert report["latest_complete_utc_day"] == "2026-10-07"
    assert report["eligible_unseen_rows"] == 3
    assert report["eligible_unseen_days"] == 3
    assert report["excluded_incomplete_or_future_rows"] == 1
    assert report["ready_for_metric_gate"] is True


def test_readiness_never_counts_an_ongoing_day_as_third_day():
    report = build_readiness(
        [_match(day) for day in (5, 6, 8)],
        production_model=Champion(),
        minimum_gate_rows=2,
        minimum_days=3,
        as_of=CLOCK,
    )
    assert report["eligible_unseen_days"] == 2
    assert report["ready_for_metric_gate"] is False


def test_training_evaluation_requires_three_completed_unseen_utc_days():
    eligible, reason = _eligible_evaluation(
        _frame(5, 6, 7, 8), Champion(), [], as_of=CLOCK
    )
    assert reason is None
    assert list(eligible["match_id"]) == ["m-5", "m-6", "m-7"]

    deferred, reason = _eligible_evaluation(
        _frame(5, 6, 8), Champion(), [], as_of=CLOCK
    )
    assert deferred.empty
    assert reason == "no_eligible_unseen_evaluation_rows"


def test_preview_does_not_consume_holdout_but_requested_rejection_does():
    preview = {
        "holdout_fingerprint": "same-cohort",
        "holdout_period": {"end": "2026-10-06T22:00:00+00:00"},
        "promotion_requested": False,
        "decision": "not_requested",
    }
    rejected = {
        **preview,
        "promotion_requested": True,
        "decision": "rejected",
    }
    assert not _holdout_already_used([preview], "same-cohort")
    assert _holdout_already_used([rejected], "same-cohort")

    eligible, reason = _eligible_evaluation(
        _frame(5, 6, 7), Champion(), [preview], as_of=CLOCK
    )
    assert reason is None
    assert len(eligible) == 3

    deferred, reason = _eligible_evaluation(
        _frame(5, 6, 7), Champion(), [rejected], as_of=CLOCK
    )
    assert deferred.empty
    assert reason == "no_eligible_unseen_evaluation_rows"

    readiness = build_readiness(
        [_match(day) for day in (5, 6, 7)],
        production_model=Champion(),
        promotion_history=[preview],
        minimum_gate_rows=3,
        minimum_days=3,
        as_of=CLOCK,
    )
    assert readiness["eligible_unseen_rows"] == 3


def test_pipeline_persists_only_requested_real_holdout_decisions():
    source = (ROOT / "scripts" / "pipeline.py").read_text(encoding="utf-8")
    assert "if args.promote and fingerprint and not deferred:" in source
    assert 'report["promotion_decision"] = decision' in source
    assert 'promotion_history.append(decision)' in source
