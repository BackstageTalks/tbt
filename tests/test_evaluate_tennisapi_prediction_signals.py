"""Research holdout data, identity and quote anti-leakage contracts."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.evaluate_tennisapi_prediction_signals import evaluate


def inputs(days=120, per_day=4):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    baselines, signals = [], []
    for day in range(days):
        dt = start + timedelta(days=day, hours=12)
        for number in range(per_day):
            key = f"match-{day}-{number}"
            p1, p2 = str(10000 + day * 10 + number), str(20000 + day * 10 + number)
            label = int((day + number) % 2 == 0)
            baselines.append({
                "match_id": key, "scheduled_at": dt.isoformat(),
                "prediction_observed_at": (dt - timedelta(days=1)).isoformat(),
                "player1_id": p1, "player2_id": p2,
                "target": label,
                "baseline_probability": .65 if label else .35,
            })
            signals.append({
                "canonical_match_id": key, "canonical_link_status": "linked",
                "home_id": int(p1), "away_id": int(p2),
                "utc_day": dt.date().isoformat(),
                "home_seed": 1 if label else 5,
                "away_seed": 5 if label else 1,
                "seed_known_both": True,
                "duration_7d_known_both": False,
                "historical_duration_window_complete": False,
                "point_in_time_day_snapshotted": True,
                "source_prematch_seed_temporal_attestation": False,
            })
    return baselines, signals


def test_no_lookahead_baseline_predictions():
    base, signal = inputs(days=1, per_day=1)
    base[0]["prediction_observed_at"] = base[0]["scheduled_at"]
    with pytest.raises(ValueError, match="Post-start"):
        evaluate(base, signal)
    base[0]["prediction_observed_at"] = "2024-01-01T07:00:00"  # naive
    with pytest.raises(ValueError, match="Naive"):
        evaluate(base, signal)


def test_past_model_quotes_do_not_become_historical_market_truth():
    base, signal = inputs(days=2, per_day=2)
    base[0]["market_probability"] = .52
    base[0]["market_asof_verified"] = False
    base[0]["market_observed_at"] = "2023-12-31T07:00:00Z"
    base[1]["market_probability"] = .53
    base[1]["market_asof_verified"] = True
    base[1]["market_observed_at"] = base[1]["scheduled_at"]
    base[2]["market_probability"] = .54
    base[2]["market_asof_verified"] = True
    base[2]["market_observed_at"] = "2024-01-01T07:00:00Z"
    report = evaluate(base, signal)
    assert report["status"] == "INSUFFICIENT_CHRONOLOGICAL_DATA"
    assert report["market_quotes_time_verified"] == 1
    assert report["unmatched_reasons"]["unverified_or_postmatch_market"] == 2
    assert report["model_721_unchanged"] is True


def test_source_id_orientation_reverses_seed_signal():
    from scripts.evaluate_tennisapi_prediction_signals import _oriented_signals
    signal = {"home_id": 11, "away_id": 22, "home_seed": 2,
              "away_seed": 6, "historical_duration_window_complete": False,
              "source_prematch_seed_temporal_attestation": True}
    home = _oriented_signals(signal, "11", "22")
    away = _oriented_signals(signal, "22", "11")
    assert home[1] == -away[1]
    assert home[0] == away[0] == 1.0
    assert home[3] == away[3] == 0.0
    with pytest.raises(ValueError, match="native participants"):
        _oriented_signals(signal, "11", "23")


def test_no_postmatch_duration_for_own_match():
    base, signal = inputs(days=1, per_day=1)
    signal[0]["duration_7d_known_both"] = True
    signal[0]["duration_7d_advantage_home_seconds"] = 9000
    signal[0]["historical_duration_window_complete"] = False
    from scripts.evaluate_tennisapi_prediction_signals import _oriented_signals
    x = _oriented_signals(signal[0], base[0]["player1_id"], base[0]["player2_id"])
    assert x[3:] == [0.0, 0.0]


def test_linked_chronological_ablation_no_model_write_or_promotion():
    base, signal = inputs()
    for item in signal:
        item["source_prematch_seed_temporal_attestation"] = True  # synthetic proof fixture
    report = evaluate(base, signal)
    assert report["status"] == "RESEARCH_ABLATION_COMPLETE"
    assert report["train"] > report["holdout"] >= 50
    assert report["train_end_utc_day"] < report["holdout_start_utc_day"]
    assert report["production_model_activated"] is False
    assert report["model_artifacts_written"] == 0
    assert report["promotable"] is False
    assert set(report["variants"]) == {
        "baseline_recalibrated", "baseline_plus_research_signals"}
    assert report["seed_source_temporally_attested_rows"] == len(signal)


def test_duplicate_linked_or_baseline_identity_fails_closed():
    base, signal = inputs(days=1, per_day=2)
    signal.append(dict(signal[0]))
    with pytest.raises(ValueError, match="Duplicate linked"):
        evaluate(base, signal)
    base, signal = inputs(days=1, per_day=2)
    base[1]["match_id"] = base[0]["match_id"]
    with pytest.raises(ValueError, match="duplicate baseline"):
        evaluate(base, signal)


def test_unmatched_canonical_rows_are_not_labeled_net_new():
    base, signal = inputs(days=1, per_day=1)
    signal[0]["canonical_link_status"] = "potential_unlinked"
    report = evaluate(base, signal)
    assert report["linked_baseline_with_candidate"] == 0
    assert report["unmatched_reasons"]["missing_exact_link"] == 1
    assert report["cdb_writes"] == 0



def test_unverified_seed_must_not_fit_candidate_even_with_valid_targets():
    base, signal = inputs()
    report = evaluate(base, signal)
    assert report["status"] == "INSUFFICIENT_CHRONOLOGICAL_DATA"
    assert report["linked_baseline_with_candidate"] == 0
    assert report["unmatched_reasons"]["no_candidate_signal"] == len(base)
    assert report["promotable"] is False
