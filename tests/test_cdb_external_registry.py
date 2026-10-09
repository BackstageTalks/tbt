from audit_cdb_external_registry import audit


def test_official_atp_id_and_unique_name_links_historical_fragment():
    directory = {"players": [
        {"tour": "atp", "player_id": "hist-js:atp:BK92", "name": "Alexander Bublik"},
        {"tour": "atp", "player_id": "163480", "name": "Alexander Bublik"},
    ]}
    registry = [{
        "label": "Alexander Bublik", "wikidata_qid": "Q1",
        "atp_ids": ["BK92"], "wta_ids": [], "birth_dates": ["1997-06-17"],
    }]
    report = audit(directory, registry)
    assert report["total_candidates"] == 1
    assert report["candidates"][0]["to_id"] == "163480"


def test_ambiguous_full_name_cannot_link_even_with_atp_code():
    directory = {"players": [
        {"tour": "atp", "player_id": "hist-js:atp:BK92", "name": "Alexander Bublik"},
        {"tour": "atp", "player_id": "163480", "name": "Alexander Bublik"},
        {"tour": "atp", "player_id": "other", "name": "Alexander Bublik"},
    ]}
    registry = [{
        "label": "Alexander Bublik", "wikidata_qid": "Q1",
        "atp_ids": ["BK92"], "wta_ids": [],
    }]
    assert audit(directory, registry)["total_candidates"] == 0


def test_same_initial_or_altered_name_does_not_match_official_profile():
    directory = {"players": [
        {"tour": "atp", "player_id": "hist-js:atp:BK92", "name": "Bublik A."},
        {"tour": "atp", "player_id": "163480", "name": "Alexander Bublik"},
    ]}
    registry = [{
        "label": "Alexander Bublik", "wikidata_qid": "Q1",
        "atp_ids": ["BK92"], "wta_ids": [],
    }]
    assert audit(directory, registry)["total_candidates"] == 0


def test_conflicting_registry_code_is_not_promoted():
    directory = {"players": [
        {"tour": "atp", "player_id": "hist-js:atp:BK92", "name": "Alexander Bublik"},
        {"tour": "atp", "player_id": "163480", "name": "Alexander Bublik"},
    ]}
    registry = [
        {"label": "Alexander Bublik", "wikidata_qid": "Q1", "atp_ids": ["BK92"], "wta_ids": []},
        {"label": "Other Player", "wikidata_qid": "Q2", "atp_ids": ["BK92"], "wta_ids": []},
    ]
    assert audit(directory, registry)["total_candidates"] == 0
