"""Release-derived comparator directory: fast search without loading model weights."""
import gzip
import json
from pathlib import Path

import prepare_feed
from tbt.services.comparator_runtime import search_players


def test_comparator_directory_is_derived_from_verified_serving_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare_feed, "ROOT", tmp_path)
    path = tmp_path / "fixture" / "comparator.json.gz"
    path.parent.mkdir(parents=True)
    source = {
        "schema": 1,
        "model": {"schema": 1, "model_version": "champion-test", "feature_names": ["elo_diff"]},
        "feature_state": {"schema_version": 4, "players": {"atp:a": {"elo": 1500}}},
        "players": [{"player_id": "a", "name": "Alpha One", "tour": "atp", "matches_seen": 20}],
        "generated_at": "2026-10-08T08:00:00+00:00",
        "cutoff_utc": "2026-10-08T00:00:00+00:00",
    }
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(source, stream)

    report = prepare_feed._deploy_comparator_artifact(path)
    directory_path = tmp_path / "api/data/comparator-players.json"
    full_model_path = tmp_path / "api/data/comparator.json.gz"
    assert report["available"] is True
    assert report["players"] == 1
    assert directory_path.is_file() and not full_model_path.exists()
    directory = json.loads(directory_path.read_text(encoding="utf-8"))
    assert directory["schema"] == 1
    assert directory["model_version"] == "champion-test"
    assert directory["players"] == source["players"]
    assert "model" not in directory and "feature_state" not in directory
    assert search_players(directory, "Alpha", tour="atp")[0]["player_id"] == "a"
    # Source remains immutable in the verified release cache, never exposed
    # inside the public API deployment.
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        assert json.load(stream) == source

    path.unlink()
    assert prepare_feed._deploy_comparator_artifact(path)["available"] is False
    assert not directory_path.exists() and not full_model_path.exists()


def test_comparator_search_route_uses_small_directory():
    source = Path("api/function_app.py").read_text(encoding="utf-8")
    players_route = source.split('def comparator_players(req):', 1)[1].split('def comparator_compare(req):', 1)[0]
    assert "_load_comparator_players()" in players_route
    assert "_load_comparator_artifact()" not in players_route
    assert 'data/comparator-players.json' in source


def test_search_compacts_cerundolo_and_keeps_juan_manuel():
    directory = {"players": [
        {"player_id": "short-f", "name": "Cerundolo F.", "tour": "atp", "rank": 24, "matches_seen": 700},
        {"player_id": "francisco", "name": "Francisco Cerundolo", "tour": "atp", "rank": 21, "matches_seen": 500},
        {"player_id": "juan", "name": "Juan Manuel Cerundolo", "tour": "atp", "rank": 87, "matches_seen": 350},
    ]}
    found = search_players(directory, "cerun", tour="atp")
    assert {row["player_id"] for row in found} == {"francisco", "juan"}
    assert len(found) == 2
    # An exact abbreviated query must resolve to the presentation target too.
    assert [row["player_id"] for row in search_players(directory, "Cerundolo F.", tour="atp")] == ["francisco"]
    # Search presentation must not write an ID linkage into the input artifact.
    assert directory["players"][0]["player_id"] == "short-f"


def test_search_compacts_reversed_initial_and_accents_without_merging_ids():
    directory = {"players": [
        {"player_id": "hist-d", "name": "Svrčina D.", "tour": "atp", "rank": 99, "matches_seen": 600},
        {"player_id": "provider-d", "name": "Dalibor Svrčina", "tour": "atp", "rank": 91, "matches_seen": 100},
    ]}
    found = search_players(directory, "svrc", tour="atp")
    assert [p["player_id"] for p in found] == ["provider-d"]
    assert [p["player_id"] for p in search_players(directory, "D. Svrcina", tour="atp")] == []
    assert [p["player_id"] for p in search_players(directory, "Svrcina D", tour="atp")] == ["provider-d"]


def test_search_limits_after_compaction_not_before():
    directory = {"players": [
        {"player_id": "short-f", "name": "Cerundolo F.", "tour": "atp", "rank": 24, "matches_seen": 999},
        {"player_id": "francisco", "name": "Francisco Cerundolo", "tour": "atp", "rank": 21, "matches_seen": 1},
        {"player_id": "juan", "name": "Juan Manuel Cerundolo", "tour": "atp", "rank": 87, "matches_seen": 2},
        *(
            {"player_id": f"extra-{i}", "name": f"Test Cerundolo{i}", "tour": "atp", "rank": 100 + i, "matches_seen": 800 - i}
            for i in range(25)
        ),
    ]}
    found = search_players(directory, "cerun", tour="atp", limit=12)
    assert len(found) == 12
    assert found[0]["player_id"] == "francisco"
    assert all(row["player_id"] != "short-f" for row in found)


def test_search_fails_closed_for_same_initial_homonyms_and_weak_evidence():
    directory = {"players": [
        {"player_id": "short", "name": "Kecmanovic M.", "tour": "atp", "rank": 50, "matches_seen": 500},
        {"player_id": "miomir", "name": "Miomir Kecmanović", "tour": "atp", "rank": 54, "matches_seen": 300},
        {"player_id": "milos", "name": "Milos Kecmanovic", "tour": "atp", "rank": 53, "matches_seen": 200},
    ]}
    assert {p["player_id"] for p in search_players(directory, "kecma", tour="atp")} == {"short", "miomir", "milos"}

    directory["players"].pop()
    directory["players"][1]["rank"] = 251
    assert {p["player_id"] for p in search_players(directory, "kecma", tour="atp")} == {"short", "miomir"}

    # Explicit full alias is a second source of evidence when ranks are missing.
    directory["players"][0]["aliases"] = ["Miomir Kecmanovic"]
    assert [p["player_id"] for p in search_players(directory, "kecma", tour="atp")] == ["miomir"]

    # A matching WTA name cannot resolve an ATP initial.
    directory["players"][1]["tour"] = "wta"
    assert [p["player_id"] for p in search_players(directory, "kecma", tour="atp")] == ["short"]


def test_search_bublik_with_historical_full_and_short_records():
    """Screenshot: Bublik A. (#51) should show only Alexander Bublik (#13)."""
    directory = {"players": [
        {"player_id": "hist-js:atp:122330", "name": "Bublik A.", "tour": "atp", "rank": 51, "matches_seen": 900},
        {"player_id": "hist-js:atp:BK92", "name": "Alexander Bublik", "tour": "atp", "rank": None, "matches_seen": 100},
        {"player_id": "163480", "name": "Alexander Bublik", "tour": "atp", "rank": 13, "matches_seen": 500},
    ]}
    found = search_players(directory, "bublik", tour="atp")
    # Response is deduplicated *before* the search page limit and always
    # selects the numeric canonical provider ID; histories are untouched.
    assert [row["player_id"] for row in found] == ["163480"]
    assert found[0]["name"] == "Alexander Bublik"
    assert found[0]["rank"] == 13
    assert [row["player_id"] for row in search_players(directory, "Bublik A", tour="atp")] == ["163480"]
    assert len(directory["players"]) == 3


def test_search_historical_full_provenance_does_not_collapse_different_people():
    directory = {"players": [
        {"player_id": "hist-js:atp:short", "name": "Perez B.", "tour": "atp", "rank": 48},
        {"player_id": "provider-ben", "name": "Benjamin Perez", "tour": "atp", "rank": 12},
        {"player_id": "hist-js:atp:ben", "name": "Benjamin Perez", "tour": "atp"},
        {"player_id": "provider-brandon", "name": "Brandon Perez", "tour": "atp", "rank": 54},
    ]}
    ids = {row["player_id"] for row in search_players(directory, "perez", tour="atp")}
    assert "hist-js:atp:short" in ids
    assert "provider-ben" in ids
    assert "provider-brandon" in ids


def test_search_duplicate_full_names_from_two_providers_fail_closed():
    directory = {"players": [
        {"player_id": "hist-js:atp:short", "name": "Bublik A.", "tour": "atp", "rank": 51},
        {"player_id": "provider-one", "name": "Alexander Bublik", "tour": "atp", "rank": 13},
        {"player_id": "provider-two", "name": "Alexander Bublik", "tour": "atp", "rank": 14},
    ]}
    ids = {row["player_id"] for row in search_players(directory, "bublik", tour="atp")}
    assert "hist-js:atp:short" in ids
    assert "provider-one" in ids
    assert "provider-two" in ids


def test_search_works_with_diacritics_and_historical_name_same_spelling():
    directory = {"players": [
        {"player_id": "hist-js:atp:abbrev", "name": "Ćorić B.", "tour": "atp", "rank": 55},
        {"player_id": "hist-js:atp:full", "name": "Borna Coric", "tour": "atp"},
        {"player_id": "64580", "name": "Borna Ćorić", "tour": "atp", "rank": 27},
    ]}
    assert [x["player_id"] for x in search_players(directory, "coric", tour="atp")] == ["64580"]
