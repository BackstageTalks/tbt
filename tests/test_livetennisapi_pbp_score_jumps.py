"""Regression gates for live score STATE changes at game/set boundaries."""
from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "link_livetennisapi_pbp_serve_return.py"


def _helpers():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {"_same_score", "_can_end_game_in_one_point", "_point_winner"}
    selected = [node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(selected) == len(names)
    namespace = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["_point_winner"]


def _state(sets=(0, 0), games=([0], [0]), points=("0", "0"), tie=False):
    return {"sets": sets, "games": games, "points": points, "server": 1,
            "is_tiebreak": tie}


def test_rejects_game_winner_when_score_jumps_from_zero():
    infer = _helpers()
    assert infer(_state(), _state(games=([1], [0]))) is None
    assert infer(_state(points=("15", "0")),
                 _state(games=([1], [0]))) is None


def test_accepts_provable_single_point_game_finish():
    infer = _helpers()
    assert infer(_state(points=("40", "15")),
                 _state(games=([1], [0]))) == 1
    assert infer(_state(points=("A", "40")),
                 _state(games=([1], [0]))) == 1
    assert infer(_state(points=("15", "40")),
                 _state(games=([0], [1]))) == 2


def test_deuce_cannot_jump_to_finished_game_as_one_point():
    infer = _helpers()
    assert infer(_state(points=("40", "40")),
                 _state(games=([1], [0]))) is None


def test_set_boundary_also_requires_game_point():
    infer = _helpers()
    assert infer(_state(games=([5], [4]), points=("0", "0")),
                 _state(sets=(1, 0), games=([6], [4]))) is None
    assert infer(_state(games=([5], [4]), points=("40", "15")),
                 _state(sets=(1, 0), games=([6], [4]))) == 1


def test_tiebreak_set_boundary_must_be_one_point_from_finish():
    infer = _helpers()
    assert infer(_state(games=([6], [6]), points=("6", "6"), tie=True),
                 _state(sets=(1, 0), games=([7], [6]))) is None
    assert infer(_state(games=([6], [6]), points=("6", "5"), tie=True),
                 _state(sets=(1, 0), games=([7], [6]))) == 1


def test_normal_point_and_duplicate_still_work():
    infer = _helpers()
    assert infer(_state(points=("15", "0")),
                 _state(points=("30", "0"))) == 1
    assert infer(_state(), _state()) == 0
