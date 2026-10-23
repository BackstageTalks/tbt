from datetime import datetime, timedelta, timezone
import pytest

from tbt.models.evidence_lab import HistoricalEvidence, player_features, reliability_gate

UTC = timezone.utc
T = datetime(2026, 10, 23, 10, tzinfo=UTC)


def obs(k, player="A", when=None, surface="hard", available=None, reviewed=True, **kw):
    day = when or T - timedelta(days=10)
    d = dict(canonical_match_id=str(k), tour="ATP", player_id=player, surface=surface,
             completed_at=day, available_at=available or day + timedelta(hours=1),
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
                 matches_surface=15, covered_matches={k: 20 for k in
                 ["serve", "return", "second_serve", "bp_save", "bp_convert"]})
    small = dict(large, canonical_player_id="B", matches_recent=3, matches_surface=1)
    assert not reliability_gate(large, small, [.80, .82])["eligible"]
    rich = dict(large, canonical_player_id="B")
    assert reliability_gate(large, rich, [.80, .82])["eligible"]
    assert not reliability_gate(large, rich, [.80, .60])["eligible"]
    assert not reliability_gate(large, rich, [.80])["eligible"]


def test_source_timestamp_and_malformed_data_rejected():
    with pytest.raises(ValueError):
        player_features([obs("x", completed_at=T-timedelta(days=4),
                          available_at=T-timedelta(days=6))],
                        player_id="A", tour="ATP", surface="hard", issued_at=T)
    with pytest.raises(ValueError):
        player_features([obs("x")], player_id="A", tour="ATP", surface="hard",
                        issued_at=datetime(2026, 10, 23))
