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
        "feature_state": {"players": {"atp:a": {"elo": 1500}}},
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
    assert directory_path.is_file() and full_model_path.is_file()
    directory = json.loads(directory_path.read_text(encoding="utf-8"))
    assert directory["schema"] == 1
    assert directory["model_version"] == "champion-test"
    assert directory["players"] == source["players"]
    assert "model" not in directory and "feature_state" not in directory
    assert search_players(directory, "Alpha", tour="atp")[0]["player_id"] == "a"
    with gzip.open(full_model_path, "rt", encoding="utf-8") as stream:
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
