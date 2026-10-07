from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import numpy as np

from tbt.schemas import MatchRecord
from tbt.services.comparator import (
    AmbiguousPlayerError,
    ComparatorError,
    PlayerDirectory,
    PlayerNotFoundError,
    compare,
)


BASE = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


class FakeModel:
    version = "test-champion"
    feature_names = [
        "elo_diff",
        "surface_elo_diff",
        "recent_form_diff",
        "serve_quality_diff",
        "return_quality_diff",
        "h2h_advantage",
    ]

    def predict_proba(self, frame):
        values = []
        for row in frame.to_dict("records"):
            score = (
                float(row["elo_diff"]) / 300.0
                + float(row["surface_elo_diff"]) / 300.0
                + float(row["recent_form_diff"]) * 1.5
            )
            values.append(1.0 / (1.0 + math.exp(-score)))
        return np.asarray(values, dtype=float)


def match(day, p1, n1, p2, n2, winner, surface="hard", p1_rank=None, p2_rank=None):
    return MatchRecord(
        match_id=f"m-{day}-{p1}-{p2}",
        tour="atp",
        scheduled_at=BASE - timedelta(days=day),
        player1_id=p1,
        player1_name=n1,
        player2_id=p2,
        player2_name=n2,
        surface=surface,
        player1_rank=p1_rank,
        player2_rank=p2_rank,
        winner_id=winner,
        status="completed",
        best_of=3,
        stats={
            "p1_serve_quality": 0.64,
            "p2_serve_quality": 0.57,
            "p1_return_quality": 0.42,
            "p2_return_quality": 0.38,
            "p1_sets_won": 2.0 if winner == p1 else 0.0,
            "p2_sets_won": 2.0 if winner == p2 else 0.0,
        },
    )


def history():
    rows = []
    for day in range(1, 31):
        if day % 2:
            rows.append(match(day, "a", "Alpha One", "x", "Other X", "a", "hard", 10, 80))
        else:
            rows.append(match(day, "b", "Beta Two", "y", "Other Y", "y", "hard", 40, 30))
    rows += [
        match(35, "a", "Alpha One", "b", "Beta Two", "a", "clay", 10, 40),
        match(50, "a", "Alpha One", "b", "Beta Two", "a", "hard", 10, 40),
    ]
    return rows


def test_comparator_uses_canonical_history_and_zero_api_calls():
    result = compare(
        FakeModel(),
        history(),
        player1="Alpha One",
        player2="Beta Two",
        tour="atp",
        surface="hard",
        now=BASE,
    )
    assert result["api_requests"] == 0
    assert result["canonical_read_only"] is True
    assert result["cutoff_utc"] == "2026-10-07T00:00:00+00:00"
    assert result["model_version"] == "test-champion"
    assert result["winner"]["player_id"] == "a"
    assert result["player1"]["probability"] > 0.5
    assert result["player1"]["fair_odds"] > 1.0
    assert result["feature_contract"]["point_in_time"] is True
    assert result["feature_contract"]["historical_date_mode"] is False


def test_comparator_swap_is_probability_symmetric():
    first = compare(
        FakeModel(), history(), player1="Alpha One", player2="Beta Two",
        tour="atp", surface="hard", now=BASE,
    )
    second = compare(
        FakeModel(), history(), player1="Beta Two", player2="Alpha One",
        tour="atp", surface="hard", now=BASE,
    )
    assert abs(first["player1"]["probability"] - second["player2"]["probability"]) < 1e-9


def test_player_directory_is_fail_closed_for_unknown_name():
    directory = PlayerDirectory.from_history(history())
    try:
        directory.resolve("Definitely Missing", tour="atp")
    except PlayerNotFoundError:
        pass
    else:
        raise AssertionError("unknown player must fail closed")


def test_player_directory_is_fail_closed_for_ambiguous_normalized_name():
    rows = history()
    rows.append(match(70, "duplicate", "Alpha One", "z", "Other Z", "duplicate"))
    directory = PlayerDirectory.from_history(rows)
    try:
        directory.resolve("Alpha One", tour="atp")
    except AmbiguousPlayerError:
        pass
    else:
        raise AssertionError("ambiguous player must fail closed")


def test_comparator_rejects_invalid_context():
    try:
        compare(
            FakeModel(), history(), player1="Alpha One", player2="Beta Two",
            tour="atp", surface="carpet", now=BASE,
        )
    except ComparatorError:
        pass
    else:
        raise AssertionError("unsupported surface must be rejected")
