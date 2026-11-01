"""Fail-closed CDB annual row conservation before publication."""
import pytest

from release_store import assert_history_rows_monotonic


def manifest(**years):
    return {"years": {str(year): {"rows": rows} for year, rows in years.items()}}


def test_preserves_year_counts():
    assert_history_rows_monotonic(manifest(**{"2025": 600, "2026": 100}),
                                  manifest(**{"2025": 600, "2026": 100}))


def test_allows_only_additive_growth():
    assert_history_rows_monotonic(manifest(**{"2025": 600, "2026": 100}),
                                  manifest(**{"2025": 620, "2026": 105}))


def test_rejects_2026_shrink():
    with pytest.raises(ValueError, match="CDB_YEAR_ROW_REGRESSION_BLOCKED year=2026"):
        assert_history_rows_monotonic(manifest(**{"2025": 600, "2026": 98994}),
                                      manifest(**{"2025": 620, "2026": 2927}))


def test_rejects_dropped_partition():
    with pytest.raises(ValueError, match="CDB year removed"):
        assert_history_rows_monotonic(manifest(**{"2024": 500, "2026": 900}),
                                      manifest(**{"2024": 501}))


@pytest.mark.parametrize("old,new", [
    ({"years": {"2026": {"rows": True}}}, manifest(**{"2026": 1})),
    (manifest(**{"2026": 1}), {"years": {"2026": {"rows": False}}}),
    (manifest(**{"2026": 1}), {"years": {"2026": {"rows": None}}}),
    ({"years": {}}, manifest(**{"2026": 5})),
])
def test_invalid_inventory_fails_closed(old, new):
    with pytest.raises(ValueError):
        assert_history_rows_monotonic(old, new)
