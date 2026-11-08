"""Research-only replay: no provider requests, canonical writes or model features."""
from copy import deepcopy

import pytest

from tbt.errors import ProviderError
from tbt.providers.tennisapi_pbp_replay import replay_point_by_point


def six_love_fixture():
    """Six ordinary games, terminal point omitted in every game."""
    return {"eventId": 14232981, "pointByPoint": [
        {"set": 1, "games": [
            {"game": g, "points": [
                {"homePoint": "15", "awayPoint": "0"},
                {"homePoint": "30", "awayPoint": "0"},
                {"homePoint": "40", "awayPoint": "0"},
            ], "score": {
                "serving": 1 if g % 2 else 2, "scoring": 1,
                "homeScore": g, "awayScore": 0,
            }} for g in range(6, 0, -1)
        ]},
    ]}


def test_replay_reconstructs_terminal_winners_and_breaks_without_cdb_promotion():
    fixture = six_love_fixture()
    result = replay_point_by_point(
        fixture, event_id=14232981, expected_sets=[(6, 0)])
    assert result["provider_event_id_present"] is True
    assert result["match_score_witness_attested"] is True
    assert result["counts"]["games"] == 6
    assert result["counts"]["observed_points"] == 18
    assert result["counts"]["inferred_terminal_points"] == 6
    assert result["counts"]["points"] == 24
    assert result["counts"]["p1_points_won"] == 24
    assert result["counts"]["p1_service_points_won"] == 12
    assert result["counts"]["p1_return_points_won"] == 12
    assert result["counts"]["p1_bp_converted"] == 3
    assert result["counts"]["p2_bp_faced"] == 3
    assert result["counts"]["p1_break_games_won"] == 3
    assert result["eligible_for_cdb_point_features"] is False
    assert result["production_mutated"] is False
    assert result["provider_requests"] == 0


def test_missing_event_id_is_reported_not_imagined():
    fixture = six_love_fixture()
    fixture.pop("eventId")
    r = replay_point_by_point(fixture, event_id=14232981)
    assert r["provider_event_id_present"] is False
    assert r["match_score_witness_attested"] is False
    assert r["eligible_for_cdb_point_features"] is False


@pytest.mark.parametrize("mutate", [
    lambda p: p.__setitem__("eventId", 1),
    lambda p: p["pointByPoint"][0]["games"][0].__setitem__("game", 3),
    lambda p: p["pointByPoint"][0]["games"][0]["points"][0].__setitem__("homePoint", "40"),
    lambda p: p["pointByPoint"][0]["games"][0]["score"].__setitem__("serving", 1),
    lambda p: p["pointByPoint"][0]["games"][0]["score"].__setitem__("homeScore", 999),
])
def test_replay_fails_closed_on_identity_gaps_invalid_transitions_and_score(mutate):
    fixture = deepcopy(six_love_fixture())
    mutate(fixture)
    with pytest.raises(ProviderError):
        replay_point_by_point(fixture, event_id=14232981, expected_sets=[(6, 0)])


def test_wrong_external_set_score_never_yields_verified_replay():
    with pytest.raises(ProviderError, match="score differs"):
        replay_point_by_point(
            six_love_fixture(), event_id=14232981, expected_sets=[(6, 1)])
