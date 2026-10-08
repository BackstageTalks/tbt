"""Comparator indexed serving regression: never allocate all player histories."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tbt.services.comparator import build_serving_artifact
from tbt.services.comparator_index import ComparatorIndexError, build_comparator_index, load_pair_artifact
from tbt.services.comparator_runtime import compare_from_artifact
from test_comparator_runtime import _history, _model, NOW


def test_index_preserves_champion_and_pairwise_probabilities(tmp_path):
    source = build_serving_artifact(_model(), _history(), now=NOW)
    db = tmp_path / "comparator-serving.sqlite3"
    report = build_comparator_index(source, db)
    assert report["players"] == len(source["players"])
    assert report["bytes"] == db.stat().st_size
    directory = {
        "players": source["players"],
        "generated_at": source["generated_at"],
        "model_version": source["model"]["model_version"],
    }
    actual = load_pair_artifact(db, directory, player1="a", player2="b", tour="atp")
    assert set(actual["feature_state"]["players"]) == {"atp:a", "atp:b"}
    assert actual["model"] == source["model"]
    assert actual["feature_state"]["h2h"]
    for surface in ("hard", "clay"):
        original = compare_from_artifact(source, player1="a", player2="b", tour="atp", surface=surface, now=NOW)
        indexed = compare_from_artifact(actual, player1="a", player2="b", tour="atp", surface=surface, now=NOW)
        assert indexed["player1"]["probability"] == pytest.approx(original["player1"]["probability"], abs=1e-10)
        assert indexed["winner"] == original["winner"]
        assert indexed["api_requests"] == 0
    with pytest.raises(ComparatorIndexError, match="player_not_found"):
        load_pair_artifact(db, directory, player1="unknown-id", player2="b", tour="atp")
    with pytest.raises(ComparatorIndexError, match="same_player"):
        load_pair_artifact(db, directory, player1="a", player2="a", tour="atp")
    bad = dict(directory, model_version="different-model")
    with pytest.raises(ComparatorIndexError, match="mismatch"):
        load_pair_artifact(db, bad, player1="a", player2="b", tour="atp")


def test_public_endpoint_does_not_load_full_snapshot():
    app = Path("api/function_app.py").read_text(encoding="utf-8")
    route = app.split("def comparator_compare(req):", 1)[1].split("@app.route(", 1)[0]
    assert "load_pair_artifact(" in route
    assert "_load_comparator_artifact()" not in route
    assert 'COMPARATOR_INDEX = Path(__file__).parent / "data/comparator-serving.sqlite3"' in app
