from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tbt.models.ensemble import TennisEnsemble
from tbt.schemas import MatchRecord
from tbt.services.comparator import build_serving_artifact, compare
from tbt.services.comparator_runtime import compare_from_artifact, search_players


NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
FEATURES = [
    "elo_diff", "surface_elo_diff", "elo_probability",
    "recent_form_diff", "rank_known_both", "data_depth",
]


def _train_frame(count, offset):
    rng = np.random.default_rng(9000 + offset)
    origin = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset)
    rows = []
    for idx in range(count):
        elo = float(rng.normal(0, 0.55))
        surface = float(rng.normal(elo * .7, .35))
        recent = float(rng.normal(0, .15))
        elo_probability = 1.0 / (1.0 + np.exp(-(elo * 1.7)))
        latent = elo * 1.1 + surface * .8 + recent * 1.6
        p = 1.0 / (1.0 + np.exp(-latent))
        rows.append({
            "match_id": f"train-{offset}-{idx}",
            "scheduled_at": origin + timedelta(days=idx),
            "target": int(rng.random() < p),
            "elo_diff": elo,
            "surface_elo_diff": surface,
            "elo_probability": elo_probability,
            "recent_form_diff": recent,
            "rank_known_both": 0.0,
            "data_depth": float(rng.uniform(.2, 1.0)),
        })
    return pd.DataFrame(rows)


def _history():
    rows = []
    players = [
        ("a", "Alpha One"),
        ("b", "Beta Two"),
        ("x", "Other X"),
        ("y", "Other Y"),
    ]
    for day in range(1, 45):
        if day % 2:
            p1, p2, winner = players[0], players[2], "a"
        else:
            p1, p2, winner = players[1], players[3], "y"
        rows.append(MatchRecord(
            match_id=f"hist-{day}",
            tour="atp",
            scheduled_at=NOW - timedelta(days=day),
            player1_id=p1[0], player1_name=p1[1],
            player2_id=p2[0], player2_name=p2[1],
            surface="hard" if day % 3 else "clay",
            winner_id=winner, status="completed", best_of=3,
            stats={
                "p1_service_points_won": .64,
                "p2_service_points_won": .57,
                "p1_return_points_won": .42,
                "p2_return_points_won": .38,
                "p1_sets_won": 2.0 if winner == p1[0] else 0.0,
                "p2_sets_won": 2.0 if winner == p2[0] else 0.0,
            },
        ))
    rows.append(MatchRecord(
        match_id="hist-h2h",
        tour="atp",
        scheduled_at=NOW - timedelta(days=50),
        player1_id="a", player1_name="Alpha One",
        player2_id="b", player2_name="Beta Two",
        surface="hard", winner_id="a", status="completed", best_of=3,
        stats={"p1_sets_won": 2.0, "p2_sets_won": 0.0},
    ))
    return rows


def _model():
    model = TennisEnsemble(feature_names=FEATURES)
    model.fit(_train_frame(320, 0), _train_frame(140, 400))
    return model


def test_runtime_artifact_matches_offline_comparator_probability():
    model = _model()
    history = _history()
    offline = compare(
        model, history, player1="Alpha One", player2="Beta Two",
        tour="atp", surface="hard", now=NOW,
    )
    artifact = build_serving_artifact(model, history, now=NOW)
    runtime = compare_from_artifact(
        artifact, player1="a", player2="b",
        tour="atp", surface="hard", now=NOW,
    )
    assert runtime["api_requests"] == 0
    assert runtime["canonical_read_only"] is True
    assert runtime["model_version"] == model.version
    assert abs(runtime["player1"]["probability"] - offline["player1"]["probability"]) < 1e-6
    assert runtime["winner"]["player_id"] == offline["winner"]["player_id"]


def test_runtime_player_search_returns_canonical_id():
    artifact = build_serving_artifact(_model(), _history(), now=NOW)
    rows = search_players(artifact, "Alpha", tour="atp")
    assert rows
    assert rows[0]["player_id"] == "a"
    assert rows[0]["name"] == "Alpha One"


def test_public_runtime_modules_do_not_require_training_stack():
    for path in (
        "api/tbt/services/comparator_runtime.py",
        "api/tbt/models/portable_model.py",
    ):
        source = Path(path).read_text(encoding="utf-8").lower()
        assert "import pandas" not in source
        assert "import numpy" not in source
        assert "sklearn" not in source
        assert "joblib" not in source
