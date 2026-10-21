"""Synthetic contract tests only; never export private betting rows to public CI."""
import pandas as pd
import pytest

from train_top_721_odds_specialist import (
    _high_confidence_settled, _top_three, train_and_compare, validated_candidates,
)


def rows():
    result = []
    for day in range(1, 8):
        for i in range(8):
            result.append({
                "betting_day": f"2026-10-{day:02d}",
                "event_id": f"{day}-{i}",
                "selection_id": f"p-{day}-{i}",
                "quote_at": f"2026-10-{day:02d}T04:00:00+00:00",
                "snapshot_at": f"2026-10-{day:02d}T04:01:00+00:00",
                "scheduled_at": f"2026-10-{day:02d}T05:00:00+00:00",
                "model_probability": .55 + i * .045,
                "fair_market_probability": .52 + i * .02,
                "data_depth": .8,
                "odds": 1.5 if i == 0 else 1.55 + i * .04,
                "outcome": "win" if i >= 4 else "loss",
            })
    return pd.DataFrame(result)


def test_training_includes_exact_top_odds_boundary_and_keeps_days_disjoint(tmp_path):
    source = tmp_path / "rows.csv"
    rows().to_csv(source, index=False)
    result = train_and_compare(source, tmp_path / "out", min_train=10)
    assert result["counts"]["equal_150_included"] == 7
    assert result["counts"]["eligible_ge_150"] == len(rows())
    assert result["counts"]["raw_model_ge_80_settled"] > result["counts"]["public_top_ge_80_settled"]
    # Correct baseline is the probability TOP uses, not the model's raw score.
    assert result["probability_metrics"]["blinq"] != result["probability_metrics"]["raw_model"]
    assert result["top_80_reliability"]["blinq"]["settled"] == 0
    assert result["top_80_reliability"]["raw_model"]["settled"] > 0
    assert result["guardrails"]["odds"].startswith(">=1.50")
    assert result["train"]["last_day"] == "2026-10-04"
    assert result["test"]["first_day"] == "2026-10-05"
    assert result["top_three_metrics"]["specialist"]["selected"] == 9
    assert result["guardrails"]["production_writes"] == 0
    top = result["top_three_metrics"]["specialist"]
    assert top["offered"] == 24
    assert top["selected"] == 9
    assert top["selection_coverage"] == 9 / 24
    assert top["unsettled_selected"] == 0
    assert top["hit_rate_ci95_wilson"] is not None
    assert top["target_87_supported"] is False
    assert result["vip_accuracy_goal"]["target"] == .87
    assert (tmp_path / "out" / "research_model.joblib").exists()


def test_no_after_snapshot_quote():
    frame = rows()
    frame.loc[0, "quote_at"] = "2026-10-01T07:00:00+00:00"
    with pytest.raises(ValueError, match="Look-ahead"):
        validated_candidates(frame)


def test_no_naive_time():
    frame = rows()
    frame.loc[0, "quote_at"] = "2026-10-01T04:00:00"
    with pytest.raises(ValueError, match="Naive"):
        validated_candidates(frame)


def test_no_duplicate_event():
    frame = rows()
    with pytest.raises(ValueError, match="Duplicate"):
        validated_candidates(pd.concat([frame, frame.head(1)], ignore_index=True))


def test_pending_results_are_not_labels(tmp_path):
    frame = rows()
    frame.loc[frame.betting_day == "2026-10-07", "outcome"] = "pending"
    source = tmp_path / "rows.csv"
    frame.to_csv(source, index=False)
    result = train_and_compare(source, tmp_path / "out", min_train=10)
    assert result["test"]["last_day"] == "2026-10-06"
    assert result["test"]["settled"] == 24


def test_snapshot_top_probability_must_match_published_depth_shrink():
    frame = rows()
    frame["blinq_probability"] = .5 + (frame.model_probability - .5) * frame.data_depth
    priced, counts = validated_candidates(frame)
    assert len(priced) == 56
    assert counts["equal_150_included"] == 7
    frame.loc[0, "blinq_probability"] = .98
    with pytest.raises(ValueError, match="disagrees"):
        validated_candidates(frame)


def test_infinite_odds_never_enter_specialist_training():
    frame = rows()
    frame.loc[0, "odds"] = float("inf")
    with pytest.raises(ValueError, match="Nonfinite bookmaker odds"):
        validated_candidates(frame)


def test_no_80pct_reliability_claim_from_small_sample():
    frame = rows()
    priced, counts = validated_candidates(frame)
    assert counts["raw_model_ge_80_settled"] > 0
    assert counts["public_top_ge_80_settled"] == 0


def test_perfect_small_vip_sample_does_not_certify_87_percent():
    priced, _ = validated_candidates(rows())
    priced["outcome"] = "win"
    confidence = _high_confidence_settled(priced, "model_probability")
    assert confidence["settled"] > 0
    assert confidence["accuracy"] == 1.0
    assert confidence["accuracy_ci95_wilson"][0] < 0.87
    assert confidence["target_87_supported"] is False


def test_vip_report_counts_pending_selection_against_capacity():
    frame, _ = validated_candidates(rows())
    frame.loc[frame.betting_day == "2026-10-07", "outcome"] = "pending"
    top = _top_three(frame, "model_probability")
    assert top["selected"] == 21
    assert top["settled"] == 18
    assert top["unsettled_selected"] == 3
    assert top["selection_coverage"] == 21 / 56
