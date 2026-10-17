"""Synthetic contract tests only; never export private betting rows to public CI."""
import pandas as pd
import pytest

from train_top_721_odds_specialist import train_and_compare, validated_candidates


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


def test_training_excludes_exact_boundary_and_keeps_days_disjoint(tmp_path):
    source = tmp_path / "rows.csv"
    rows().to_csv(source, index=False)
    result = train_and_compare(source, tmp_path / "out", min_train=10)
    assert result["counts"]["equal_150_excluded"] == 7
    assert result["train"]["last_day"] == "2026-10-04"
    assert result["test"]["first_day"] == "2026-10-05"
    assert result["top_three_metrics"]["specialist"]["selected"] == 9
    assert result["guardrails"]["production_writes"] == 0
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
    assert result["test"]["settled"] == 21
