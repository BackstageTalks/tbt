"""Synthetic identity-review tests: no CDB writes or guessed entity merges."""
from datetime import datetime, timezone
import json
import pyarrow as pa
import pytest

from cdb_2026_four_identity_triage import (
    cases, clean, compare_participants, native_evidence, missing_cross_source_pair,
)

WHEN = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


def tab(rows):
    return pa.Table.from_pylist([
        {"match_id": mid, "tour": "atp", "scheduled_at": WHEN,
         "tournament_id": "t1", "tournament": "Example",
         "round_name": "R16", "player1_id": p1, "player2_id": p2,
         "player1_name": p1, "player2_name": p2, "winner_id": p1,
         "status": "finished", "stats_json": json.dumps({"p1_aces": 4}),
         "provider_context_json": json.dumps({"_tbt_event_identity": {
             "event_id": native, "home": {"id": p1},
             "away": {"id": p2}}})}
        for mid, p1, p2, native in rows
    ])


def test_unicode_names_represent_same_player():
    assert clean("Šramková") == clean("Sramkova")


def test_same_provider_id_with_changed_players_is_not_safe_rekey():
    old = tab([("old", "a", "b", "event-1")])
    current = tab([("new", "a", "c", "event-1")])
    assert native_evidence(old, 0)[0] == native_evidence(current, 0)[0]
    comparison = compare_participants(old, 0, current, 0)
    assert comparison["same_player_ids_unordered"] is False
    assert comparison["native_home_away_exact"] is False
    assert comparison["same_winner_id"] is True


def test_same_provider_id_and_players_can_be_different_fixture():
    old = tab([("old", "a", "b", "event-1")])
    current = tab([("new", "a", "b", "event-1")])
    result = compare_participants(old, 0, current, 0)
    assert result["same_player_ids_unordered"] is True
    assert result["native_home_away_exact"] is True


def test_source_event_disagreement_fails_closed():
    original = tab([("old", "a", "b", "event-1")]).to_pylist()
    original[0]["provider_context_json"] = json.dumps({
        "_tbt_event_identity": {"event_id": "event-1"},
        "_tbt_statistics": {"event_id": "different-event"},
    })
    assert native_evidence(pa.Table.from_pylist(original), 0)[1] == "conflicting"



def test_same_real_fixture_can_have_two_missing_source_match_ids():
    original = tab([("legacy-name-id", "Jo Yee Chan", "Hanna Chang", "event-25")])
    previous = tab([("other-source-id", "Jo Yee Chan", "Hanna Chang", "event-25")])
    live = tab([("unrelated", "other", "people", "event-77")])
    pair = missing_cross_source_pair(original, previous, live)
    assert len(pair) == 1
    assert pair[0]["native_id_equal"] is True
    assert pair[0]["identity_comparison"]["same_player_ids_unordered"]
    assert pair[0]["conflicting_nonnull_stat_fields"] == 0
    assert pair[0]["same_nonnull_stat_fields"] == 1


def test_unpinned_cohort_fails_closed_even_if_four_missing():
    with pytest.raises(ValueError, match="Pinned original cohorts changed"):
        cases(tab([("a", "x", "y", "1")]),
              tab([("b", "x", "z", "2")]), tab([("c", "u", "v", "3")]))


def test_diagnostic_has_no_writer_or_paid_provider_requests():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts/cdb_2026_four_identity_triage.py").read_text()
    flow = (root / ".github/workflows/cdb-2026-four-identity-triage.yml").read_text()
    assert "download_stable(REPO, TAG" in script
    assert "stamp(initial) != stamp(release(TAG))" in script
    assert "CDB_FOUR_NATIVE_TRIAGE" in script
    assert "cdb_global_writer_lock.py acquire" not in flow
    assert "gh release upload" not in flow
    assert "RAPIDAPI_KEY" not in flow
    assert "TENNISAPI" not in flow
