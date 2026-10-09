from collections import defaultdict

from build_cdb_verified_player_crosswalk import build


def players():
    return {"players": [
        {"tour": "atp", "player_id": "hist-js:atp:BK92", "name": "Alexander Bublik"},
        {"tour": "atp", "player_id": "163480", "name": "Alexander Bublik"},
    ]}


def registry():
    return [{
        "label": "Alexander Bublik", "wikidata_qid": "Q23678983",
        "atp_ids": ["BK92"], "wta_ids": [], "birth_dates": ["1997-06-17T00:00:00Z"],
    }]


def match(mid, *, winner=True, surface="hard"):
    return {"match_id": mid, "date": "2026-04-06", "opponent": "john smith",
            "tournament": "miami", "round": "r32", "surface": surface, "won": winner}


def test_official_identity_can_be_linked_without_duplicate_event_overlap():
    observations = {
        ("atp", "hist-js:atp:BK92"): [match("a")],
        ("atp", "163480"): [match("b", surface="hard")],
    }
    # One duplicate event is corroborating evidence but not required when an
    # independently unique external ATP code is present and no conflicts exist.
    names = {k: {"alexander bublik"} for k in observations}
    entries, blocked, report = build(players(), registry(), observations, names)
    assert len(entries) == 1
    assert entries[0]["source_player_id"] == "hist-js:atp:BK92"
    assert entries[0]["canonical_player_id"] == "163480"
    assert report["accepted"] == 1
    assert not blocked


def test_conflicting_canonical_outcome_is_quarantined():
    observations = {
        ("atp", "hist-js:atp:BK92"): [match("a")],
        ("atp", "163480"): [match("b", winner=False)],
    }
    names = {k: {"alexander bublik"} for k in observations}
    entries, blocked, report = build(players(), registry(), observations, names)
    assert not entries
    assert report["canonical_event_overlap_conflict"] == 1
    assert blocked[0]["reason"] == "canonical_event_overlap_conflict"


def test_inconsistent_name_and_missing_target_blocked():
    observations = {("atp", "hist-js:atp:BK92"): [match("a")]}
    names = {("atp", "hist-js:atp:BK92"): {"alexander bublik"}}
    entries, blocked, _ = build(players(), registry(), observations, names)
    assert not entries
    assert blocked[0]["reason"] == "missing_current_cdb_player_evidence"
    observations[("atp", "163480")] = [match("b")]
    names[("atp", "163480")] = {"different athlete"}
    entries, blocked, _ = build(players(), registry(), observations, names)
    assert not entries
    assert blocked[0]["reason"] == "inconsistent_canonical_source_player_name"
