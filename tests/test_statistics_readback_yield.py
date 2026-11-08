from collections import Counter
from types import SimpleNamespace

import pytest

from verify_targeted_statistics import verify_added_fields


def test_yield_separates_breakpoints_from_other_fields_and_tours():
    rows = [SimpleNamespace(match_id="a", tour="ATP", stats={"p1_aces": 0, "p1_break_point_serve_win": .5}),
            SimpleNamespace(match_id="b", tour="WTA", stats={"p1_aces": 2, "p2_return_points_won": .3})]
    fields, tours = Counter(), Counter()
    expected = {"a": {"p1_break_point_serve_win": .5}, "b": {"p1_aces": 2, "p2_return_points_won": .3}}
    n = verify_added_fields(rows, expected, field_counts=fields, tour_field_counts=tours)
    assert n == sum(fields.values()) == sum(tours.values()) == 3
    assert fields == {"p1_break_point_serve_win": 1, "p1_aces": 1, "p2_return_points_won": 1}
    assert tours[("atp", "p1_aces")] == 0  # existing cell is not new yield
    assert tours[("wta", "p1_aces")] == 1
    with pytest.raises(ValueError, match="Missing or changed"):
        verify_added_fields(rows, {"a": {"p1_break_point_serve_win": .6}}, field_counts=Counter())
