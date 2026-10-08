"""Comparator player autocomplete must not load the full model artifact."""
from __future__ import annotations

import gzip
import json

import function_app
import prepare_feed
from tbt.services.comparator_runtime import search_players


def test_prepare_feed_creates_verified_compact_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare_feed, "ROOT", tmp_path)
    (tmp_path / "api" / "data").mkdir(parents=True)
    artifact = {
        "schema": 1,
        "generated_at": "2026-10-08T03:46:13+00:00",
        "cutoff_utc": "2026-10-08T00:00:00+00:00",
        "model": {"schema": 1, "model_version": "test-champion"},
        "feature_state": {"players": {}},
        "players": [
            {"player_id": "p1", "name": "Novak Djokovic", "tour": "atp", "matches_seen": 99},
            {"player_id": "p2", "name": "Rafael Nadal", "tour": "atp", "matches_seen": 97},
        ],
    }
    source = tmp_path / "source.json.gz"
    with gzip.open(source, "wt", encoding="utf-8") as handle:
        json.dump(artifact, handle)
    result = prepare_feed._deploy_comparator_artifact(source)
    assert result["available"] is True
    assert result["players"] == 2
    full = tmp_path / "api" / "data" / "comparator.json.gz"
    index = tmp_path / "api" / "data" / "comparator_players.json.gz"
    assert full.exists() and index.exists()
    with gzip.open(index, "rt", encoding="utf-8") as handle:
        directory = json.load(handle)
    assert directory["players"] == artifact["players"]
    assert directory["model_version"] == "test-champion"
    assert "feature_state" not in directory
    assert "model" not in directory


def test_search_uses_compact_index_even_when_model_artifact_is_missing(tmp_path, monkeypatch):
    index = tmp_path / "players.json.gz"
    directory = {
        "schema": 1,
        "generated_at": "2026-10-08T03:46:13+00:00",
        "model_version": "test-champion",
        "players": [
            {"player_id": "atp-a", "name": "Novak Djokovic", "tour": "atp", "matches_seen": 250},
            {"player_id": "wta-b", "name": "Iga Swiatek", "tour": "wta", "matches_seen": 220},
        ],
    }
    with gzip.open(index, "wt", encoding="utf-8") as handle:
        json.dump(directory, handle)
    monkeypatch.setattr(function_app, "COMPARATOR_PLAYERS", index)
    monkeypatch.setattr(function_app, "COMPARATOR", tmp_path / "absent-comparator.json.gz")
    monkeypatch.setattr(function_app, "_COMPARATOR_PLAYERS_CACHE", None)
    loaded = function_app._load_comparator_players()
    assert search_players(loaded, "Novak", tour="atp")[0]["player_id"] == "atp-a"
    assert search_players(loaded, "Iga", tour="wta")[0]["player_id"] == "wta-b"
    assert search_players(loaded, "Novak", tour="wta") == []
    assert function_app._load_comparator_players() is loaded
