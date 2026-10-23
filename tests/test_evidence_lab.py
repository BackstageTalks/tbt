from datetime import datetime, timedelta, timezone
import pytest

from tbt.models.evidence_lab import HistoricalEvidence, player_features, reliability_gate, pair_feature_projection, DIL_FEATURE_NAMES

UTC = timezone.utc
T = datetime(2026, 10, 23, 10, tzinfo=UTC)


def obs(k, player="A", when=None, surface="hard", available=None, reviewed=True, **kw):
    day = when or T - timedelta(days=10)
    d = dict(canonical_match_id=str(k), tour="ATP", player_id=player, surface=surface,
             started_at=day-timedelta(hours=1),
             completed_at=day, available_at=available or day + timedelta(hours=1),
             expected_recorded_at=day-timedelta(hours=2),
             won=True, expected_win=.5, service_points=100, first_in=60,
             first_won=45, second_won=20, opponent_service_points=100,
             opponent_first_won=38, opponent_second_won=18, bp_saved=4, bp_faced=5,
             opponent_bp_saved=3, opponent_bp_faced=7, reviewed_cdb_link=reviewed)
    d.update(kw)
    return HistoricalEvidence(**d)


def test_service_return_second_serve_breakpoints_correct():
    row = player_features([obs("x")], player_id="A", tour="ATP", surface="hard", issued_at=T)
    assert row["stats"]["serve_rate"] == .65
    assert row["stats"]["return_rate"] == .44
    assert row["stats"]["second_serve_rate"] == .5
    assert row["stats"]["bp_save_rate"] == .8
    assert row["stats"]["bp_convert_rate"] == 4 / 7
    assert row["covered_matches"]["return"] == 1


def test_future_same_day_and_late_stats_are_excluded():
    rows = [obs("prior"),
            obs("same", when=T-timedelta(hours=6), available=T-timedelta(hours=4)),
            obs("late", when=T-timedelta(days=3), available=T+timedelta(days=1)),
            obs("future", when=T+timedelta(days=1))]
    out = player_features(rows, player_id="A", tour="ATP", surface="hard", issued_at=T)
    assert out["matches_recent"] == 1


def test_unknown_counts_remain_null_and_no_free_stats():
    r = obs("s", service_points=None, first_in=None, first_won=None, second_won=None,
            opponent_service_points=None, opponent_first_won=None, opponent_second_won=None,
            bp_saved=None, bp_faced=None, opponent_bp_saved=None, opponent_bp_faced=None)
    out = player_features([r], player_id="A", tour="ATP", surface="hard", issued_at=T)
    assert all(v is None for v in out["stats"].values())
    assert set(out["covered_matches"].values()) == {0}


def test_unreviewed_duplicate_and_impossible_stats_fail_closed():
    for sample in ([obs("a", reviewed=False)], [obs("x"), obs("x")],
                   [obs("x", first_won=200)]):
        with pytest.raises(ValueError):
            player_features(sample, player_id="A", tour="ATP", surface="hard", issued_at=T)


def test_form_uses_surface_shrink_and_indoor_hard_bucket():
    rows = [obs(str(i), when=T-timedelta(days=i+2),
                surface="clay", won=False, expected_win=.9) for i in range(10)]
    rows.append(obs("h", surface="indoor_hard", won=True, expected_win=.1))
    out = player_features(rows, player_id="A", tour="ATP", surface="hard", issued_at=T)
    assert out["matches_surface"] == 1
    assert out["surface_opponent_adjusted_form"] > out["opponent_adjusted_form"]
    assert out["surface_opponent_adjusted_form"] < .9


def test_reliability_withholds_confident_but_sparse_player():
    large = dict(canonical_player_id="A", tour="atp", matches_recent=20,
                 matches_surface=15, stat_opportunities={k: 400 for k in
                 ["serve", "return", "second_serve", "bp_save", "bp_convert"]},
                 covered_matches={k: 20 for k in
                 ["serve", "return", "second_serve", "bp_save", "bp_convert"]})
    small = dict(large, canonical_player_id="B", matches_recent=3, matches_surface=1,
                 covered_matches={k: 3 for k in large["covered_matches"]})
    assert not reliability_gate(large, small, two_models(.80, .82))["eligible"]
    rich = dict(large, canonical_player_id="B")
    assert reliability_gate(large, rich, two_models(.80, .82))["eligible"]
    assert not reliability_gate(large, rich, two_models(.80, .60))["eligible"]
    assert not reliability_gate(large, rich, {"elo": {"left_player_id": "A", "probability": .80}})["eligible"]


def test_source_timestamp_and_malformed_data_rejected():
    with pytest.raises(ValueError):
        player_features([obs("x", completed_at=T-timedelta(days=4),
                          available_at=T-timedelta(days=6))],
                        player_id="A", tour="ATP", surface="hard", issued_at=T)
    with pytest.raises(ValueError):
        player_features([obs("x")], player_id="A", tour="ATP", surface="hard",
                        issued_at=datetime(2026, 10, 23))


def test_future_fitted_expectation_rejected():
    with pytest.raises(ValueError):
        player_features([obs("x", expected_recorded_at=T)], player_id="A",
                        tour="ATP", surface="hard", issued_at=T)


def test_partial_counts_still_enforce_source_integrity():
    invalid = (
        {"service_points": -1, "first_in": None, "first_won": None, "second_won": None},
        {"first_in": 20, "first_won": 30, "second_won": 20},
        {"first_in": 99, "second_won": 20},
        {"opponent_service_points": -5, "opponent_first_won": None,
         "opponent_second_won": None},
        {"opponent_bp_saved": 8, "opponent_bp_faced": 7},
        {"second_won": 101},
    )
    for values in invalid:
        with pytest.raises(ValueError):
            player_features([obs("bad", **values)], player_id="A", tour="ATP",
                            surface="hard", issued_at=T)


def test_candidate_pair_adapter_exposes_known_both_and_respects_orientation():
    left = player_features([obs("a", player="A")], player_id="A",
                           tour="ATP", surface="hard", issued_at=T)
    right = player_features([obs("b", player="B", service_points=100,
                                 first_in=60, first_won=30, second_won=20)],
                            player_id="B", tour="ATP", surface="hard", issued_at=T)
    features = pair_feature_projection(left, right)
    swapped = pair_feature_projection(right, left)
    assert set(features) == set(DIL_FEATURE_NAMES)
    assert features["dil_serve_rate_diff"] == pytest.approx(.15)
    assert features["dil_stats_known_both"] == 1.0
    assert all(features[f"dil_{metric}_known_both"] == 1.0 for metric in
               ("serve", "return", "second_serve", "bp_save", "bp_convert"))
    assert features["dil_serve_rate_diff"] == -swapped["dil_serve_rate_diff"]
    assert features["dil_min_recent_count"] == 1.0


def test_pair_adapter_never_invents_missing_rate_coverage():
    left = player_features([obs("a", player="A")], player_id="A",
                           tour="ATP", surface="hard", issued_at=T)
    right = player_features([obs("b", player="B", opponent_bp_faced=None,
                                 opponent_bp_saved=None, bp_faced=None, bp_saved=None)],
                            player_id="B", tour="ATP", surface="hard", issued_at=T)
    features = pair_feature_projection(left, right)
    assert features["dil_bp_save_rate_diff"] == 0.0
    assert features["dil_bp_convert_rate_diff"] == 0.0
    assert features["dil_stats_known_both"] == pytest.approx(3 / 5)
    assert features["dil_bp_save_known_both"] == 0.0
    assert features["dil_bp_convert_known_both"] == 0.0
    assert features["dil_serve_known_both"] == 1.0
    assert features["dil_return_known_both"] == 1.0
    assert features["dil_second_serve_known_both"] == 1.0


def test_candidate_adapter_distinguishes_same_aggregate_coverage_with_different_missing_fields():
    left = player_features([obs("a", player="A")], player_id="A",
                           tour="ATP", surface="hard", issued_at=T)
    no_second = player_features([obs("b", player="B", second_won=None)], player_id="B",
                                tour="ATP", surface="hard", issued_at=T)
    no_break_save = player_features([obs("c", player="C", bp_saved=None)], player_id="C",
                                    tour="ATP", surface="hard", issued_at=T)
    s = pair_feature_projection(left, no_second)
    b = pair_feature_projection(left, no_break_save)
    assert s["dil_stats_known_both"] == b["dil_stats_known_both"]
    assert s["dil_second_serve_known_both"] == 0.0
    assert b["dil_second_serve_known_both"] == 1.0
    assert s["dil_bp_save_known_both"] == 1.0
    assert b["dil_bp_save_known_both"] == 0.0


def test_pair_adapter_refuses_unreviewed_or_cross_tour_identity():
    left = player_features([obs("a", player="A")], player_id="A",
                           tour="ATP", surface="hard", issued_at=T)
    with pytest.raises(ValueError):
        pair_feature_projection(left, dict(left))
    with pytest.raises(ValueError):
        pair_feature_projection(left, dict(left, canonical_player_id="B", tour="wta"))


def two_models(a, b):
    return {
        "elo": {"left_player_id": "A", "probability": a},
        "hgb": {"left_player_id": "A", "probability": b},
    }


def test_model_disagreement_requires_same_canonical_left_player():
    rich = dict(canonical_player_id="A", tour="atp", matches_recent=20,
                matches_surface=15, stat_opportunities={k: 400 for k in
                 ["serve", "return", "second_serve", "bp_save", "bp_convert"]},
                 covered_matches={k: 20 for k in
                ("serve", "return", "second_serve", "bp_save", "bp_convert")})
    other = dict(rich, canonical_player_id="B")
    # Two complementary player sides from one model must NOT look like
    # independent agreeing estimators.
    spoofed = {"elo-p1": {"left_player_id": "A", "probability": .80},
               "elo-p2": {"left_player_id": "B", "probability": .20}}
    assert not reliability_gate(rich, other, spoofed)["eligible"]
    assert not reliability_gate(rich, other, [.80, .82])["eligible"]
    assert reliability_gate(rich, other, two_models(.80, .82))["eligible"]


def test_bp_opportunity_denominators_gate_confident_thin_statistical_sample():
    ample = dict(canonical_player_id="A", tour="atp", matches_recent=20,
                 matches_surface=12, covered_matches={k: 20 for k in
                 ("serve", "return", "second_serve", "bp_save", "bp_convert")},
                 stat_opportunities={k: 300 for k in
                 ("serve", "return", "second_serve", "bp_save", "bp_convert")})
    other = dict(ample, canonical_player_id="B",
                 stat_opportunities={**ample["stat_opportunities"], "bp_convert": 2})
    report = reliability_gate(ample, other, two_models(.81, .82))
    assert not report["eligible"]
    assert "insufficient_stat_opportunities" in report["reasons"]
    assert reliability_gate(ample, dict(ample, canonical_player_id="B"),
                            two_models(.81, .82))["eligible"]


def test_inplay_expectation_not_misclassified_as_prematch():
    with pytest.raises(ValueError, match="before actual match start"):
        player_features([obs("x", expected_recorded_at=T-timedelta(minutes=30))],
                        player_id="A", tour="ATP", surface="hard", issued_at=T)
