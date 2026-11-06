"""Fail-closed CDB annual row conservation before publication."""
import pytest

from release_store import assert_history_rows_monotonic, assert_history_partition_bundle_atomic, assert_history_identities_conserved


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


def _year_parquet(path, rows):
    from datetime import datetime, timezone, timedelta
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.Table.from_pylist([
        {
            "match_id": match_id,
            "player1_id": p1,
            "player2_id": p2,
            "scheduled_at": datetime(2026, 10, day, 12, tzinfo=timezone.utc),
            "stats_json": '{"aces":1}' if index == 0 else '{}',
        }
        for index, (match_id, p1, p2, day) in enumerate(rows)
    ])
    pq.write_table(table, path)
    return path


def test_existing_identity_rows_preserved_by_additive_history_candidate(tmp_path):
    earlier = _year_parquet(tmp_path / "old.parquet", [
        ("id-a", "p1", "p2", 3), ("id-b", "p3", "p4", 4),
    ])
    proposed = _year_parquet(tmp_path / "candidate.parquet", [
        ("id-a", "p1", "p2", 3), ("id-b", "p3", "p4", 4),
        ("id-c", "p5", "p6", 5),
    ])
    result = assert_history_identities_conserved(earlier, proposed, year=2026)
    assert result == {
        "year": 2026, "existing_ids_preserved": 2, "new_ids": 1,
        "changed_original_identities": 0,
    }


def test_increasing_row_count_must_not_hide_deleted_original_ids(tmp_path):
    earlier = _year_parquet(tmp_path / "old.parquet", [
        ("id-a", "p1", "p2", 3), ("id-b", "p3", "p4", 4),
    ])
    proposed = _year_parquet(tmp_path / "candidate.parquet", [
        ("id-a", "p1", "p2", 3), ("new-c", "p5", "p6", 5),
        ("new-d", "p7", "p8", 6), ("new-e", "p9", "p10", 7),
    ])
    with pytest.raises(ValueError, match="missing_old_ids=1"):
        assert_history_identities_conserved(earlier, proposed, year=2026)


@pytest.mark.parametrize("replacement", [
    ("id-a", "p2", "p1", 3),
    ("id-a", "p1", "p2", 9),
    ("id-a", "p1", "different-p2", 3),
])
def test_existing_player_pair_or_original_kickoff_cannot_silently_change(tmp_path, replacement):
    original = _year_parquet(tmp_path / "old.parquet", [
        ("id-a", "p1", "p2", 3),
    ])
    candidate = _year_parquet(tmp_path / "candidate.parquet", [
        replacement,
        ("new-row", "p3", "p4", 4),
    ])
    with pytest.raises(ValueError, match="changed_original_identities=1"):
        assert_history_identities_conserved(original, candidate, year=2026)


def test_canonical_history_identity_guard_rejects_duplicate_and_wrong_year(tmp_path):
    original = _year_parquet(tmp_path / "old.parquet", [
        ("id-a", "p1", "p2", 3),
    ])
    dup = _year_parquet(tmp_path / "duplicate.parquet", [
        ("id-a", "p1", "p2", 3), ("id-a", "p3", "p4", 4),
    ])
    with pytest.raises(ValueError, match="INVALID_OR_DUPLICATE"):
        assert_history_identities_conserved(original, dup, year=2026)
    with pytest.raises(ValueError, match="WRONG_UTC_YEAR"):
        assert_history_identities_conserved(original, original, year=2025)


def test_production_writer_enforces_remote_id_conservation_before_upload():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "scripts/release_store.py").read_text()
    area = source.split("def upload_bundle(", 1)[1]
    prior = area.index("previous = self._remote_bundle_files()")
    guard = area.index("assert_history_identities_conserved(")
    publish = area.index("guarded = (")
    assert prior < guard < publish
    assert "self._sha256(remote) != expected[\"sha256\"]" in area
    assert "history_manifest.json" in area[:guard]
