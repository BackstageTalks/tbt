"""Fail-closed contracts for private paired TOP research; no provider calls."""
from datetime import datetime, timezone
from copy import deepcopy

import pandas as pd
import pytest

from tbt.schemas import MatchRecord
from tbt.models.feature_builder import FeatureBuilder
from tbt.services.paired_top_evaluation import make_paired_holdout
from scripts.evaluate_paired_top_selection import evaluate, auc, compare_confidence_floors


def match(i="f1", winner="A", date="2026-10-29T10:00:00+00:00"):
    return MatchRecord(
        match_id=i, tour="atp", scheduled_at=datetime.fromisoformat(date),
        player1_id="A", player1_name="A", player2_id="B", player2_name="B",
        winner_id=winner, surface="hard", tournament="Example", tournament_level="ATP",
    )


def export_fixture():
    record = match()
    oriented, target = FeatureBuilder.orient_for_training(record)
    frame = pd.DataFrame([{
        "match_id": record.match_id, "scheduled_at": record.scheduled_at,
        "target": target, "tour": "atp", "surface": "hard",
        "competition": "ATP", "tournament": "Example",
        "data_depth": .91, "surface_history_count": 9,
        "stats_known_both": 1, "surface_stats_known_both": 1,
        "rank_known_both": 0, "elo_probability": .73,
    }])
    exported = make_paired_holdout(
        frame, {record.match_id: record}, [.72], [.80],
        champion_version="champion-pinned", candidate_version="candidate-pinned",
        fingerprint="holdout-id",
        candidate_feature_names=["elo_probability"],
        champion_feature_names=["elo_probability"],
    )
    return exported, oriented


def quote(row, p1=1.6, p2=2.2):
    return {"match_id": row["match_id"], "player1_id": row["player1_id"],
            "player2_id": row["player2_id"],
            "captured_at": "2026-10-29T08:00:00Z",
            "odds_player1": p1, "odds_player2": p2}


def test_paired_fixture_exact_orientation_and_no_market_inputs():
    exported, oriented = export_fixture()
    row = exported["rows"][0]
    assert row["player1_id"] == oriented.player1_id
    assert row["player2_id"] == oriented.player2_id
    assert row["target_player1_win"] == int(oriented.player1_id == "A")
    assert "odds" not in str(exported).lower()
    assert len(row["feature_vector_sha256"]) == 64
    assert row["production_player1_probability"] == .72
    assert row["candidate_player1_probability"] == .80


def test_wrong_orientation_or_target_is_rejected():
    exported, _ = export_fixture()
    record = match()
    oriented, target = FeatureBuilder.orient_for_training(record)
    row = exported["rows"][0]
    frame = pd.DataFrame([{**{
        "match_id": record.match_id, "scheduled_at": record.scheduled_at,
        "target": 1-target, "tour": "atp", "surface": "hard",
        "competition": "ATP", "tournament": "Example",
        "data_depth": .91, "surface_history_count": 9,
        "stats_known_both": 1, "surface_stats_known_both": 1,
        "rank_known_both": 0, "elo_probability": .73
    }}])
    with pytest.raises(ValueError, match="orientation"):
        make_paired_holdout(
            frame, {record.match_id: record}, [.72], [.80],
            champion_version="v1", candidate_version="v2", fingerprint="f",
            candidate_feature_names=["elo_probability"], champion_feature_names=["elo_probability"])


def test_verified_price_is_subsequent_filter_not_score_input():
    exported, _ = export_fixture()
    row = exported["rows"][0]
    answer = evaluate(exported, [quote(row)])
    assert answer["counts"]["paired_rows"] == 1
    assert answer["comparison"]["candidate"]["qualified"] in (0,1)
    assert answer["conditions"]["subsequent_verified_odds"] == 1.5
    assert answer["comparison"]["candidate"]["all_qualified"]["confidence_accuracy_auc"] is None


def test_future_quotes_wrong_pair_duplicate_scores_fail_closed():
    exported, _ = export_fixture()
    row = exported["rows"][0]
    future = quote(row)
    future["captured_at"] = "2026-10-30T08:00:00Z"
    result = evaluate(exported, [future])
    assert result["counts"]["price_after_start"] == 1
    wrong = quote(row)
    wrong["player1_id"] = "NOT-A-PLAYER"
    with pytest.raises(ValueError, match="orientation"):
        evaluate(exported, [wrong])
    with pytest.raises(ValueError, match="Duplicated|Duplicate"):
        evaluate(exported, [quote(row), quote(row)])
    duplicate = deepcopy(exported)
    duplicate["rows"].append(deepcopy(row))
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate(duplicate, [quote(row)])


def test_auc_uses_tie_half_credit_and_both_classes():
    assert auc([0, 1], [.5, .5]) == .5
    assert auc([0, 1], [.2, .8]) == 1.0
    assert auc([0, 1], [.8, .2]) == 0.0
    assert auc([1, 1], [.2, .8]) is None


def test_missing_price_never_manufactures_qualified_picks():
    exported, _ = export_fixture()
    result = evaluate(exported, [])
    assert result["counts"]["price_missing"] == 1
    assert result["comparison"]["candidate"]["qualified"] == 0
    assert result["comparison"]["production"]["qualified"] == 0


def test_research_60_percent_is_inclusive_with_fixed_150_price_and_65_reference():
    """60% widens the sports cohort; prices are unchanged and applied later."""
    exported, _ = export_fixture()
    template = exported["rows"][0]
    scored = deepcopy(exported)
    scored["rows"] = []
    quotes = []
    # First two are only in the added 60-65% confidence range.
    # Third was already 65+; last is rejected by the 1.50 quote floor.
    for i, (confidence, price) in enumerate([
        (.60, 1.50), (.62, 1.52), (.70, 1.50), (.61, 1.49)
    ]):
        row = deepcopy(template)
        row["match_id"] = f"sample-{i}"
        row["player1_id"] = f"player1-{i}"
        row["player2_id"] = f"player2-{i}"
        row["winner_id"] = row["player1_id"]
        row["target_player1_win"] = 1
        row["production_player1_probability"] = confidence
        row["candidate_player1_probability"] = confidence
        scored["rows"].append(row)
        quotes.append(quote(row, p1=price))

    paired = compare_confidence_floors(scored, quotes)
    primary, reference = paired["primary"], paired["reference_65"]
    assert primary["conditions"]["sports_confidence_floor"] == .60
    assert reference["conditions"]["sports_confidence_floor"] == .65
    assert primary["conditions"]["subsequent_verified_odds"] == 1.5
    assert reference["conditions"]["subsequent_verified_odds"] == 1.5
    for model in ("production", "candidate"):
        assert primary["comparison"][model]["qualified"] == 3
        assert reference["comparison"][model]["qualified"] == 1
        assert primary["comparison"][model]["days_with_3plus"] == 1
        assert reference["comparison"][model]["days_with_3plus"] == 0
        diff = paired["increment_from_65_to_60"]["by_model"][model]
        assert diff["new_price_qualified_picks"] == 2
        assert diff["correct_among_new"] == 2
        assert diff["accuracy_among_new"] == 1
        assert diff["new_top3_daily_slots"] == 2
        assert diff["days_with_3plus_delta"] == 1
    assert primary["counts"]["below_price_floor_per_model"]["candidate"] == 1


def test_60_percent_does_not_force_picks_if_real_quotes_missing():
    exported, _ = export_fixture()
    paired = compare_confidence_floors(exported, [])
    for report in (paired["primary"], paired["reference_65"]):
        assert report["comparison"]["production"]["qualified"] == 0
        assert report["comparison"]["candidate"]["qualified"] == 0
    for model in ("production", "candidate"):
        assert paired["increment_from_65_to_60"]["by_model"][model]["accuracy_among_new"] is None
