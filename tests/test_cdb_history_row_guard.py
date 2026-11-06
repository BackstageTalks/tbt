"""Fail-closed CDB annual row conservation before publication."""
import pytest

from release_store import assert_history_rows_monotonic, assert_history_partition_bundle_atomic


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


@pytest.mark.parametrize("paths,removals", [
    (["history-2026.parquet"], ()),
    ([], ("history-2026.parquet",)),
    (["history-2022.parquet", "history-2026.parquet"], ()),
    (["history-2026.parquet"], ("history-2024.parquet",)),
])
def test_canonical_year_mutations_cannot_bypass_year_manifest(paths, removals):
    with pytest.raises(ValueError, match="CDB_ANNUAL_MANIFEST_REQUIRED"):
        assert_history_partition_bundle_atomic(paths, removals)


def test_canonical_year_mutation_keeps_existing_atomic_manifest_path():
    assert_history_partition_bundle_atomic(["history-2026.parquet", "history_manifest.json"])
    assert_history_partition_bundle_atomic(["history_manifest.json"],
                                           ("history-2026.parquet",))
    assert_history_partition_bundle_atomic(["history_manifest.json"])
    assert_history_partition_bundle_atomic(["model.joblib", "training_report.json"])


def test_canonical_history_manifest_cannot_be_deleted():
    with pytest.raises(ValueError, match="CDB_HISTORY_MANIFEST_REMOVAL_BLOCKED"):
        assert_history_partition_bundle_atomic([], ("history_manifest.json",))
    with pytest.raises(ValueError, match="CDB_HISTORY_MANIFEST_REMOVAL_BLOCKED"):
        assert_history_partition_bundle_atomic(["history_manifest.json"],
                                               ("history_manifest.json",))


def test_upload_bundle_invokes_year_manifest_guard_even_without_row_count_change():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "scripts/release_store.py").read_text()
    assert "assert_history_partition_bundle_atomic(files, removals)" in source
    assert source.index("assert_history_partition_bundle_atomic(files, removals)") < source.index("previous = self._remote_bundle_files()", source.index("def upload_bundle("))
