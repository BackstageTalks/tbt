"""WTA doubles four-player crosswalk candidate admission stays fail-closed."""
import json
import pytest
from scripts.audit_wta_doubles_four_ids import strict_four_player_ids, parse_context


def test_four_distinct_explicit_individual_ids():
    assert strict_four_player_ids({
        "team1_player_ids": ["p1", "p2"],
        "team2_player_ids": ["p3", "p4"],
    }) == ("p1", "p2", "p3", "p4")


@pytest.mark.parametrize("payload", [
    {"player1_id": "teamA", "player2_id": "teamB"},
    {"team1_player_ids": ["p1", "p2"], "team2_player_ids": ["p2", "p4"]},
    {"team1_player_ids": ["p1 / p2"], "team2_player_ids": ["p3", "p4"]},
    {"team1_player_ids": [123, 456], "team2_player_ids": ["p3", "p4"]},
    {"team1_player_ids": "p1,p2", "team2_player_ids": "p3,p4"},
    {"team1_player_ids": ["p1", " "], "team2_player_ids": ["p3", "p4"]},
    {"team1_player_ids": ["p1", "p2"], "team2_player_ids": ["p3"]},
    [],
    None,
])
def test_ambiguous_or_two_team_ids_never_count_as_four_individuals(payload):
    assert strict_four_player_ids(payload) is None


def test_context_invalid_json_fails():
    with pytest.raises(ValueError):
        parse_context("not json", "bad")
    with pytest.raises(ValueError):
        parse_context("[]", "bad")
    with pytest.raises(ValueError):
        parse_context('{"x":NaN}', "bad")
    assert parse_context("{}", "ok") == {}


def test_unavailable_source_cannot_serialize_authorized_write():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] /
              "scripts/audit_wta_doubles_four_ids.py").read_text()
    assert '"write_authorized": False' in script
    assert '"canonical_mutated": False' in script
    assert '"production_model_training": False' in script
    assert "upload_bundle(" not in script
