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
    vip = result["vip_selective_metrics"]["blinq"]
    assert vip["offered"] == 24
    assert vip["selected"] == 0  # 80% gate does not force three picks/day
    assert vip["settled"] == 0
    assert vip["hit_rate"] is None
    assert vip["selection_coverage"] == 0
    assert vip["target_87_supported"] is False
    assert vip["target_80_supported"] is False
    assert vip["minimum_daily_picks_target"] == 3
    assert vip["maximum_daily_picks"] is None
    assert len(vip["days_below_minimum"]) == 3
    assert vip["daily_pick_shortfall"] == 9
    assert vip["minimum_daily_target_met"] is False
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
    vip = _top_three(frame, "model_probability", minimum_probability=.80,
                     maximum_daily_picks=None, minimum_daily_picks=3)
    assert vip["selected"] == 14  # exactly two eligible offers/day
    assert vip["settled"] == 12
    assert vip["unsettled_selected"] == 2
    assert vip["selection_coverage"] == 14 / 56
    assert vip["days_meeting_minimum"] == 0
    assert len(vip["days_below_minimum"]) == 7
    assert vip["daily_pick_shortfall"] == 7
    assert vip["minimum_daily_target_met"] is False



def test_uncapped_vip_selects_every_offer_at_or_above_80_and_reports_shortfall():
    frame, _ = validated_candidates(rows())
    # Five legitimate 80% offers on day one; two on each other day.
    day_one = frame.betting_day == "2026-10-01"
    frame.loc[day_one & frame.event_id.isin(
        [f"1-{i}" for i in range(3, 8)]
    ), "model_probability"] = .85
    vip = _top_three(frame, "model_probability", minimum_probability=.80,
                     maximum_daily_picks=None, minimum_daily_picks=3)
    assert vip["qualified_picks_per_day"]["2026-10-01"] == 5
    assert vip["selected"] == 17  # old cap of 3 would discard two good candidates
    assert vip["days_meeting_minimum"] == 1
    assert len(vip["days_below_minimum"]) == 6
    assert vip["daily_pick_shortfall"] == 6
    assert vip["minimum_daily_target_met"] is False
    assert vip["hit_rate"] is not None
    assert vip["target_80_supported"] is False  # small historical sample


def test_uncapped_vip_can_exceed_three_each_day_without_forcing_any():
    frame, _ = validated_candidates(rows())
    frame.loc[:, "model_probability"] = .80
    vip = _top_three(frame, "model_probability", minimum_probability=.80,
                     maximum_daily_picks=None, minimum_daily_picks=3)
    assert vip["selected"] == 56
    assert vip["days_meeting_minimum"] == 7
    assert vip["days_below_minimum"] == []
    assert vip["daily_pick_shortfall"] == 0
    assert vip["minimum_daily_target_met"] is True
    assert all(count == 8 for count in vip["qualified_picks_per_day"].values())


def test_vip_threshold_below_minimum_never_forces_low_probability_offers():
    frame, _ = validated_candidates(rows())
    frame.loc[frame.betting_day == "2026-10-04", "model_probability"] = .60
    vip = _top_three(frame, "model_probability", minimum_probability=.80,
                     maximum_daily_picks=None, minimum_daily_picks=3)
    assert vip["qualified_picks_per_day"]["2026-10-04"] == 0
    assert "2026-10-04" in vip["days_below_minimum"]
    assert vip["daily_pick_shortfall"] >= 3
    assert vip["minimum_daily_target_met"] is False
