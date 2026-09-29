from datetime import datetime, timezone

from tbt.schemas import MatchRecord

from scripts.link_all_matches_archive import (
    SourceMatch,
    _candidate,
    _orientation,
    _norm_round,
)


def _match(**overrides):
    base = dict(
        match_id="m1",
        tour="atp",
        scheduled_at=datetime(2012, 6, 13, 12, 0, tzinfo=timezone.utc),
        player1_id="p1",
        player1_name="Aljaz Bedene",
        player2_id="p2",
        player2_name="Ivo Minar",
        surface="Clay",
        tournament="Kosice Challenger",
        tournament_id="",
        tournament_level="challenger",
        round_name="Round of 16",
        player1_rank=None,
        player2_rank=None,
        winner_id="p1",
        status="finished",
        best_of=3,
        indoor=False,
        stats={},
        provider_payload={},
    )
    base.update(overrides)
    return MatchRecord(**base)


def _source(**overrides):
    base = dict(
        source_match_id="s1",
        start=datetime(2012, 6, 11).date(),
        end=datetime(2012, 6, 17).date(),
        player_a="aljaz bedene",
        player_b="ivo minar",
        winner="aljaz bedene",
        tournament="kosice_challenger",
        surface="clay",
        round_name="r16",
        stats_a={
            "aces": 7.0,
            "double_faults": 1.0,
            "first_serve_win": 26 / 31,
            "second_serve_win": 11 / 18,
            "service_points_won": 37 / 49,
            "return_points_won": 20 / 48,
        },
        stats_b={
            "aces": 4.0,
            "double_faults": 1.0,
            "first_serve_win": 18 / 27,
            "second_serve_win": 10 / 21,
            "service_points_won": 28 / 48,
            "return_points_won": 12 / 49,
        },
    )
    base.update(overrides)
    return SourceMatch(**base)


def test_round_aliases_cover_archive_labels():
    assert _norm_round("Finals") == "f"
    assert _norm_round("Semi-Finals") == "sf"
    assert _norm_round("Quarter-Finals") == "qf"
    assert _norm_round("1st Round Qualifying") == "q1"
    assert _norm_round("2nd Round Qualifying") == "q2"
    assert _norm_round("3rd Round Qualifying") == "q3"


def test_accepts_strict_tournament_window_identity():
    score, evidence, accepted = _candidate(_source(), _match())
    assert accepted is True
    assert score >= 9
    assert "winner" in evidence
    assert "surface" in evidence
    assert "round" in evidence
    assert "tournament_exact" in evidence


def test_rejects_round_conflict():
    score, evidence, accepted = _candidate(
        _source(round_name="qf"),
        _match(round_name="Round of 16"),
    )
    assert accepted is False
    assert "round_conflict" in evidence


def test_rejects_winner_conflict():
    score, evidence, accepted = _candidate(
        _source(winner="ivo minar"),
        _match(),
    )
    assert accepted is False
    assert "winner_conflict" in evidence


def test_rejects_outside_tournament_window():
    score, evidence, accepted = _candidate(
        _source(),
        _match(scheduled_at=datetime(2012, 6, 20, 12, 0, tzinfo=timezone.utc)),
    )
    assert accepted is False
    assert evidence == ["outside_tournament_window"]


def test_orientation_maps_player_stats_to_canonical_sides():
    incoming = _orientation(_source(), _match())
    assert incoming is not None
    assert incoming["p1_aces"] == 7.0
    assert incoming["p2_aces"] == 4.0

    swapped = _orientation(
        _source(player_a="ivo minar", player_b="aljaz bedene"),
        _match(),
    )
    assert swapped is not None
    assert swapped["p2_aces"] == 7.0
    assert swapped["p1_aces"] == 4.0
