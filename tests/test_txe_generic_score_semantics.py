"""Proof that reusing exact score staging for ATP/WTA year families stays fail-closed."""
from __future__ import annotations

import os
import pytest
import stage_txe_wta2024_scores as stage


def source(year, tour, sets, games):
    value = {"category": tour + "-single", "match_id": "991",
             "date": f"{year}-05-10", "tournament": "Test",
             "side1_sets_won": str(sets[0]), "side2_sets_won": str(sets[1])}
    for i, (a, b) in enumerate(games, 1):
        value[f"set{i}_side1"], value[f"set{i}_side2"] = str(a), str(b)
    return value


def test_config_reflects_explicit_pinned_year_tour():
    assert stage.YEAR == int(os.environ.get("BLINQ_SCORE_YEAR", "2024"))
    assert stage.TOUR == os.environ.get("BLINQ_SCORE_TOUR", "wta")
    assert stage.RESULT_MEMBER == f"data/tennisexplorer/results/{stage.TOUR}-single/{stage.YEAR}.csv"
    assert stage.DETAIL_MEMBER == f"data/tennisexplorer/enrichment/{stage.TOUR}-single/{stage.YEAR}.jsonl"
    assert len(stage.SOURCE_SHA) == 64


def test_wta_2025_2026_three_set_game_totals(monkeypatch):
    monkeypatch.setattr(stage, "TOUR", "wta")
    for year in (2025, 2026):
        game = source(year, "wta", (2, 1), [(6, 4), (3, 6), (7, 5)])
        score = stage.score_values(game)
        assert score is not None
        assert score["sets"] == [2, 1]
        assert score["games"] == [16, 15]
        assert score["first"] == 1 and score["second"] == 0
    assert stage.score_values(source(2025, "wta", (3, 0), [(6, 4), (6, 4), (6, 4)])) is None


def test_atp_best_of_five_and_best_of_three(monkeypatch):
    monkeypatch.setattr(stage, "TOUR", "atp")
    for sets, games in [
        ((3, 0), [(6, 1), (6, 2), (6, 3)]),
        ((3, 2), [(6, 4), (4, 6), (6, 3), (3, 6), (7, 5)]),
        ((2, 0), [(6, 3), (6, 3)]),
        ((2, 1), [(6, 3), (3, 6), (6, 4)]),
    ]:
        score = stage.score_values(source(2025, "atp", sets, games))
        assert score is not None and score["sets"] == list(sets)
    bad = source(2025, "atp", (3, 2), [(6, 3), (5, 5), (6, 4), (4, 6), (7, 6)])
    assert stage.score_values(bad) is None


def test_invalid_atp_set_or_tiebreak_is_rejected(monkeypatch):
    monkeypatch.setattr(stage, "TOUR", "atp")
    assert stage.score_values(source(2026, "atp", (3, 0), [(6, 3), (7, 2), (6, 2)])) is None
    good = source(2026, "atp", (3, 0), [(7, 6), (6, 4), (6, 1)])
    good["set1_side1"] = "7(8)"
    good["set1_side2"] = "6(6)"
    assert stage.score_values(good) is not None
    good["set1_side1"] = "6(8)"
    assert stage.score_values(good) is None


def test_no_weak_fullname_identity(monkeypatch):
    assert stage.full_name("Bondar A.") is None
    assert stage.full_name("A. Bondar") is None
    assert stage.full_name("Anna Bondar") == ("anna", "bondar")
    assert stage.full_name("Bondar Anna") == ("anna", "bondar")
    assert stage.player_slug("https://evil.example/player/anna-bondar/") is None
    assert stage.player_slug("https://www.tennisexplorer.com/player/anna-bondar/") == "anna-bondar"
