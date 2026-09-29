from datetime import datetime, timezone
from types import SimpleNamespace

from link_atpworldtour_stats import (
    SourceMatch,
    _candidate,
    _orientation,
    _player_stats,
    _url_key,
)


def test_url_key_normalizes_old_and_new_stats_paths():
    old = "/en/scores/2019/451/MS001/match-stats?isLive=False"
    new = "/en/scores/stats-centre/archive/2022/8998/ms001"
    score_new = "/en/scores/match-stats/archive/2022/8998/ms001"
    assert _url_key(old) == ("2019", "451", "ms001")
    assert _url_key(new) == ("2022", "8998", "ms001")
    assert _url_key(score_new) == ("2022", "8998", "ms001")


def test_player_stats_builds_serve_return_quality():
    row = {
        "winner_aces": "6",
        "winner_double_faults": "2",
        "winner_first_serve_points_won": "30",
        "winner_first_serve_points_total": "37",
        "winner_second_serve_points_won": "11",
        "winner_second_serve_points_total": "14",
        "winner_service_points_won": "41",
        "winner_service_points_total": "51",
        "winner_return_points_won": "23",
        "winner_return_points_total": "62",
    }
    stats = _player_stats("winner", row)
    assert stats is not None
    assert stats["aces"] == 6.0
    assert stats["double_faults"] == 2.0
    assert round(stats["first_serve_win"], 6) == round(30 / 37, 6)
    assert round(stats["return_points_won"], 6) == round(23 / 62, 6)


def _source():
    return SourceMatch(
        source_match_id="2022-8998-test",
        start=datetime(2022, 1, 3).date(),
        end=datetime(2022, 1, 9).date(),
        tournament="Adelaide",
        tournament_id="2022-8998",
        surface="hard",
        round_name="f",
        winner_name="Gael Monfils",
        loser_name="Karen Khachanov",
        winner_stats={
            "aces": 6.0,
            "double_faults": 2.0,
            "first_serve_win": 0.8,
            "second_serve_win": 0.6,
            "service_points_won": 0.7,
            "return_points_won": 0.4,
        },
        loser_stats={
            "aces": 4.0,
            "double_faults": 1.0,
            "first_serve_win": 0.7,
            "second_serve_win": 0.5,
            "service_points_won": 0.6,
            "return_points_won": 0.3,
        },
        stats_source_file="match_stats_2022.csv",
        stats_source_sha256="b" * 64,
    )


def test_candidate_requires_full_identity_evidence():
    match = SimpleNamespace(
        player1_name="Karen Khachanov",
        player2_name="Gael Monfils",
        player1_id="k",
        player2_id="m",
        winner_id="m",
        scheduled_at=datetime(2022, 1, 9, tzinfo=timezone.utc),
        surface="Hard",
        round_name="Final",
        tournament="Adelaide",
    )
    score, evidence, accepted = _candidate(_source(), match)
    assert accepted is True
    assert score >= 9
    assert {"winner", "surface", "round", "tournament_exact"} <= set(evidence)


def test_orientation_maps_source_winner_loser_to_canonical_sides():
    match = SimpleNamespace(
        player1_name="Karen Khachanov",
        player2_name="Gael Monfils",
    )
    oriented = _orientation(_source(), match)
    assert oriented["p1_aces"] == 4.0
    assert oriented["p2_aces"] == 6.0
    assert oriented["p1_return_points_won"] == 0.3
    assert oriented["p2_return_points_won"] == 0.4
