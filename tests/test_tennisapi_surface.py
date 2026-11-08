"""Historical TennisApi surface aggregates from a supplied API PRO sample."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from tbt.errors import ProviderError
from tbt.providers.tennisapi_surface import completed_year_surface_profile


_ROWS = [
    # surface, matches, wins, ace, df, first attempts, first pts played/won,
    # second attempts, second pts played/won, converted/chances, conceded/faced
    ("Grass", 6, 3, 8, 12, 444, 278, 170, 166, 154, 79, 18, 48, 24, 48),
    ("Hardcourt indoor", 3, 3, 6, 4, 284, 233, 129, 51, 47, 28, 16, 25, 13, 29),
    ("Hardcourt outdoor", 38, 23, 55, 69, 2632, 1810, 1124, 822, 753, 395, 135, 303, 121, 285),
    ("Red clay", 12, 10, 14, 12, 788, 574, 338, 214, 202, 123, 62, 114, 38, 81),
    ("Red clay indoor", 4, 3, 2, 5, 253, 197, 120, 56, 51, 24, 20, 34, 13, 22),
]


def example():
    keys = ("groundType", "matches", "wins", "aces", "doubleFaults",
            "firstServeTotal", "firstServePointsTotal", "firstServePointsScored",
            "secondServeTotal", "secondServePointsTotal", "secondServePointsScored",
            "breakPointsScored", "breakPointsTotal",
            "opponentBreakPointsScored", "opponentBreakPointsTotal")
    return {"statistics": [
        {**dict(zip(keys, row)), "totalServeAttempts": row[5] + row[8]}
        for row in _ROWS
    ]}


def observe(payload=None, *, year=2025):
    return completed_year_surface_profile(
        example() if payload is None else payload,
        team_id=987654321, year=year,  # Synthetic ID: supplied body has no player ID.
        observed_at=datetime(2026, 11, 8, tzinfo=timezone.utc),
    )


def test_real_surface_sample_preserves_denominators_and_year_guard():
    r = observe()
    summary = r["summary"]
    assert summary["matches"] == 63 and summary["wins"] == 42
    assert summary["aces"] == 85 and summary["double_faults"] == 102
    assert summary["service_points_total"] == 4401
    assert summary["service_points_won"] == 2530
    assert summary["service_points_won_rate"] == pytest.approx(2530 / 4401)
    assert summary["bp_converted"] == 251 and summary["bp_chances"] == 524
    assert summary["bp_saved"] == 256 and summary["bp_faced"] == 465
    assert len(r["by_surface"]) == 5
    assert r["by_surface"]["Red clay"]["service_points_won_rate"] == pytest.approx(461/788)
    assert r["by_surface"]["Grass"]["winnersTotal"] is None
    assert r["eligible_for_pre_match_features"] is False
    assert r["eligible_for_match_level_cdb_fill"] is False
    assert r["production_mutated"] is False
    assert r["provider_requests"] == 0


def test_current_year_rejected_as_future_leakage():
    with pytest.raises(ValueError, match="completed"):
        observe(year=2026)


@pytest.mark.parametrize("field,value", [
    ("firstServeTotal", 0),
    ("secondServePointsTotal", 999),
    ("breakPointsScored", 999),
    ("totalServeAttempts", 999),
    ("doubleFaults", 0),
    ("aces", 999),
    ("matches", 0),
])
def test_invalid_surface_counts_never_become_model_features(field, value):
    p = deepcopy(example())
    p["statistics"][0][field] = value
    with pytest.raises(ProviderError):
        observe(p)


def test_unknown_duplicate_surface_and_bad_identity_rejected():
    p = example()
    p["statistics"][0]["groundType"] = "Red clay"
    with pytest.raises(ProviderError):
        observe(p)
    with pytest.raises(ValueError):
        completed_year_surface_profile(example(), team_id="..", year=2025,
                                       observed_at=datetime(2026, 11, 8, tzinfo=timezone.utc))
