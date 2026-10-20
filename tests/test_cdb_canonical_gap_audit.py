"""Coverage audit must never export match identities, values or inferred fills."""
from datetime import datetime, timezone
from types import SimpleNamespace
import json

import pytest

from scripts.cdb_canonical_gap_audit import FIELDS, coverage


def _match(mid, year, tour, stats):
    return SimpleNamespace(
        match_id=mid, tour=tour,
        scheduled_at=datetime(year, 6, 2, tzinfo=timezone.utc),
        stats=stats,
    )


def test_aggregate_only_tracks_exact_missing_cells():
    rows = [
        _match("secret-one", 2018, "wta", {
            "p1_service_points_won": 0.4, "p2_service_points_won": 0.5,
            "p1_return_points_won": 0.2, "p2_return_points_won": 0.3,
            "p1_aces": 0, "p2_aces": None,
        }),
        _match("secret-two", 2018, "wta", {}),
        _match("private-atp", 2020, "atp", {
            "p1_service_points_won": 0.8,
        }),
    ]
    result = coverage(rows)
    assert result["canonical_rows"] == 3
    assert result["production_mutated"] is False
    assert result["api_requests"] == 0
    wta = next(x for x in result["year_tour"] if x["tour"] == "wta")
    assert wta["matches"] == 2
    assert wta["core_complete_matches"] == 1
    assert wta["core_fully_missing_matches"] == 1
    assert wta["fields"]["aces"]["present_cells"] == 1
    assert wta["fields"]["aces"]["missing_cells"] == 3
    assert wta["fields"]["aces"]["both_missing_matches"] == 1
    assert len(wta["fields"]) == len(FIELDS)
    dump = json.dumps(result)
    for forbidden in ("secret-one", "secret-two", "private-atp", "0.8", "0.4"):
        assert forbidden not in dump


def test_fail_closed_on_duplicate_id_and_bad_data():
    with pytest.raises(ValueError, match="duplicate"):
        coverage([_match("x", 2020, "atp", {}), _match("x", 2021, "atp", {})])
    with pytest.raises(ValueError, match="stats"):
        coverage([_match("x", 2020, "atp", ["bad"])])
    with pytest.raises(ValueError, match="year or tour"):
        coverage([_match("x", 2011, "wta", {})])
