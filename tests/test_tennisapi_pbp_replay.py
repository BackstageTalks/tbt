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


def test_user_fixture_18_games_crosschecks_actual_set_stat_counts():
    """Original two provider responses, not invented replacement data.

    Original requested URLs/event identity are not embedded in both bodies;
    matching the numbers is strong QA, but NOT import authorization.
    """
    import json
    from pathlib import Path

    folder = Path(__file__).parent / "fixtures"
    pbp = json.loads((folder / "tennisapi_pbp_14232981_minimal.json").read_text())
    stats = json.loads((folder / "tennisapi_stats_14232981_minimal.json").read_text())
    assert "eventId" not in pbp  # Original upload had no identity claim.
    r = replay_point_by_point(pbp, event_id=14232981,
                             expected_sets=[(4, 6), (2, 6)])
    assert r["provider_event_id_present"] is False
    assert r["counts"]["sets"] == 2
    assert r["counts"]["games"] == 18
    assert r["counts"]["points"] == 110
    assert r["counts"]["observed_points"] == 92
    assert r["counts"]["inferred_terminal_points"] == 18
    assert r["counts"]["p1_points_won"] == 45
    assert r["counts"]["p2_points_won"] == 65
    assert r["counts"]["p1_service_points_won"] == 30
    assert r["counts"]["p2_service_points_won"] == 36
    assert r["counts"]["p1_return_points_won"] == 15
    assert r["counts"]["p2_return_points_won"] == 29
    assert r["counts"]["p1_bp_converted"] == 1
    assert r["counts"]["p1_bp_chances"] == 3
    assert r["counts"]["p2_bp_converted"] == 4
    assert r["counts"]["p2_bp_chances"] == 5
    assert r["counts"]["p1_bp_saved"] == 1
    assert r["counts"]["p1_bp_faced"] == 5
    assert r["counts"]["p2_bp_saved"] == 2
    assert r["counts"]["p2_bp_faced"] == 3
    assert r["eligible_for_cdb_point_features"] is False

    by_period = {
        block["period"]: {item["key"]: item for group in block["groups"]
                          for item in group["statisticsItems"]}
        for block in stats["statistics"]
    }
    for num, period in (("1", "1ST"), ("2", "2ND")):
        reported = by_period[period]
        calculated = r["sets"][num]
        for player, side in (("p1", "homeValue"), ("p2", "awayValue")):
            opponent_side = "awayValue" if side == "homeValue" else "homeValue"
            expected_service = reported["servicePointsScored"][side]
            expected_return = reported["receiverPointsScored"][side]
            expected_bp_converted = reported["breakPointsScored"][side]
            expected_bp_saved = reported["breakPointsSaved"][side]
            expected_bp_faced = reported["breakPointsSaved"][
                "homeTotal" if player == "p1" else "awayTotal"
            ]
            assert calculated[f"{player}_service_points_won"] == expected_service
            assert calculated[f"{player}_return_points_won"] == expected_return
            assert calculated.get(f"{player}_bp_converted", 0) == expected_bp_converted
            assert calculated.get(f"{player}_bp_saved", 0) == expected_bp_saved
            assert calculated.get(f"{player}_bp_faced", 0) == expected_bp_faced
    # ALL disagrees with independently replayed 1ST/2ND, so no 'ALL' BP recovery.
    assert sum(by_period["ALL"]["pointsTotal"][s] for s in ("homeValue","awayValue")) == 115
    assert by_period["ALL"]["breakPointsScored"]["awayValue"] == 0
    assert r["counts"]["p2_bp_converted"] == 4


def test_pbp_fixture_cannot_be_misattached_to_another_event():
    import json
    from pathlib import Path
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "tennisapi_pbp_14232981_minimal.json").read_text()
    )
    # No event claim in uploaded body: cannot prove native event identity from it.
    report = replay_point_by_point(payload, event_id=999)
    assert report["provider_event_id_present"] is False
    assert report["eligible_for_cdb_point_features"] is False
