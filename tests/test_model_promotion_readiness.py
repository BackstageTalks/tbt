from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from model_promotion_readiness import build_readiness
from tbt.schemas import MatchRecord


class FakeModel:
    version = "production-test"
    metadata = {"history_end": "2026-09-25T20:00:00+00:00"}


def _match(i, day, tour="atp"):
    when = datetime(2026, 9, 25, tzinfo=timezone.utc) + timedelta(days=day, hours=12)
    return MatchRecord(
        match_id=f"m{i}",
        tour=tour,
        scheduled_at=when,
        player1_id=f"a{i}",
        player2_id=f"b{i}",
        player1_name=f"A{i}",
        player2_name=f"B{i}",
        winner_id=f"a{i}",
        surface="hard",
    )


def test_readiness_uses_whole_days_after_latest_consumed_cutoff():
    matches = [_match(1, 0), _match(2, 1), _match(3, 2, "wta"), _match(4, 3)]
    history = [{
        "holdout_period": {
            "start": "2026-09-26T01:00:00+00:00",
            "end": "2026-09-26T22:00:00+00:00",
        }
    }]
    report = build_readiness(
        matches,
        production_model=FakeModel(),
        promotion_history=history,
        minimum_gate_rows=2,
        target_rows=3,
        minimum_days=2,
    )
    assert report["eligibility_cutoff_day_utc"] == "2026-09-26"
    assert report["eligible_unseen_rows"] == 2
    assert report["eligible_unseen_days"] == 2
    assert report["by_tour"] == {"wta": 1, "atp": 1}
    assert report["ready_for_metric_gate"] is True
    assert report["ready_for_retrain"] is False
    assert report["provider_requests"] == 0
