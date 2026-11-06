"""Synthetic fail-closed tests for the 1 Nov restored 2026 CDB lineage."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from verify_cdb_2026_postrestore import compare_lineage, verify_current_years
from restore_cdb_2026_lossless import sha

WHEN = datetime(2026, 10, 29, 11, 0, tzinfo=timezone.utc)


def table(items):
    return pa.Table.from_pylist([
        {"match_id": name, "player1_id": p1, "player2_id": p2,
         "scheduled_at": WHEN, "stats_json": json.dumps(stats)}
        for name, p1, p2, stats in items
    ])


def cohorts():
    old = table([
        ("overlap", "p1", "p2", {"aces": 2}),
        ("old_only", "o1", "o2", {"aces": 4, "break_points": 2}),
    ])
    prewrite = table([
        ("overlap", "p1", "p2", {"aces": 3}),
        ("new_only", "n1", "n2", {"serve": 1}),
    ])
    live = table([
        ("overlap", "p1", "p2", {"aces": 3}),
        ("new_only", "n1", "n2", {"serve": 1, "return": 0.6}),
        ("old_only", "o1", "o2", {"aces": 4, "break_points": 2}),
        ("after_recovery", "a1", "a2", {}),
    ])
    return old, prewrite, live


EXPECT = dict(expected_backup=2, expected_prewrite=2, expected_overlap=1,
              expected_old_only=1, expected_prewrite_only=1, expected_min=3)


def test_preserves_original_backup_prewrite_and_later_valid_enrichment():
    old, before, live = cohorts()
    report = compare_lineage(old, before, live, **EXPECT)
    assert report["current_2026_rows"] == 4
    assert report["backup_only_restored_and_still_present"] == 1
    assert report["prewrite_only_still_present"] == 1
    assert report["post_restore_net_new_2026_rows"] == 1
    assert report["missing_original_nonnull_cells"] == 0
    assert report["modified_original_nonnull_cells"] == 0
    assert report["historical_identity_conflicts"] == 0


@pytest.mark.parametrize("replaced_name", ["old_only", "new_only"])
def test_missing_old_or_new_prewrite_identity_blocks_even_if_row_count_is_same(replaced_name):
    old, before, live = cohorts()
    data = live.to_pylist()
    row = next(item for item in data if item["match_id"] == replaced_name)
    row["match_id"] = "replacement-id"
    with pytest.raises(ValueError, match="missing restored or prewrite"):
        compare_lineage(old, before, table([
            (r["match_id"], r["player1_id"], r["player2_id"], json.loads(r["stats_json"]))
            for r in data
        ]), **EXPECT)


def test_player_identity_orientation_must_not_change():
    old, before, live = cohorts()
    data = live.to_pylist()
    row = next(item for item in data if item["match_id"] == "old_only")
    row["player1_id"], row["player2_id"] = row["player2_id"], row["player1_id"]
    with pytest.raises(ValueError, match="conservation failure"):
        compare_lineage(old, before, table([
            (r["match_id"], r["player1_id"], r["player2_id"], json.loads(r["stats_json"]))
            for r in data
        ]), **EXPECT)


@pytest.mark.parametrize("new_stats", [
    {"aces": None, "break_points": 2},
    {"aces": 999, "break_points": 2},
])
def test_missing_or_overwritten_cdb_evidence_fails_closed(new_stats):
    old, before, live = cohorts()
    data = live.to_pylist()
    row = next(item for item in data if item["match_id"] == "old_only")
    row["stats_json"] = json.dumps(new_stats)
    with pytest.raises(ValueError, match="conservation failure"):
        compare_lineage(old, before, table([
            (r["match_id"], r["player1_id"], r["player2_id"], json.loads(r["stats_json"]))
            for r in data
        ]), **EXPECT)


def _full_files(tmp_path, ids_2025=("only-2025",), ids_2026=("only-2026",)):
    years = {}
    for year, ids in ((2025, ids_2025), (2026, ids_2026)):
        path = tmp_path / f"history-{year}.parquet"
        pq.write_table(pa.table({"match_id": list(ids)}), path)
        years[str(year)] = {
            "asset": path.name, "sha256": sha(path), "rows": len(ids),
            "bytes": path.stat().st_size,
        }
    manifest = {"years": years}
    (tmp_path / "history_manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_full_inventory_requires_exact_sha_unique_ids_and_no_year_shrink(tmp_path):
    previous = _full_files(tmp_path)
    verified = verify_current_years(tmp_path, previous, expected_years={2025, 2026})
    assert verified == {
        "years_verified": 2,
        "canonical_total_rows": 2,
        "canonical_unique_match_ids": 2,
        "year_row_reductions_from_prewrite": 0,
        "duplicate_or_missing_match_ids": 0,
    }
    newer = {"years": {key: dict(v) for key, v in previous["years"].items()}}
    newer["years"]["2025"]["rows"] = 2
    with pytest.raises(ValueError, match="below prewrite floor"):
        verify_current_years(tmp_path, newer, expected_years={2025, 2026})
    with pytest.raises(ValueError, match="Incomplete 78-year"):
        verify_current_years(tmp_path, previous, expected_years={2024, 2025, 2026})


def test_full_inventory_rejects_sha_corruption_and_cross_year_collision(tmp_path):
    previous = _full_files(tmp_path)
    corrupt = tmp_path / "history-2026.parquet"
    corrupt.write_bytes(corrupt.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="SHA or length mismatch"):
        verify_current_years(tmp_path, previous, expected_years={2025, 2026})
    changed = _full_files(tmp_path, ids_2026=("only-2025",))
    with pytest.raises(ValueError, match="Duplicate/blank"):
        verify_current_years(tmp_path, changed, expected_years={2025, 2026})


def test_runtime_entrypoint_has_no_mutation_or_provider_code():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/cdb-2026-loss-audit.yml").read_text()
    own = workflow.split("  current-restoration-readback:\n", 1)[1]
    assert "expected-old-only 0" in own
    assert "verify_cdb_2026_postrestore.py" in own
    assert "gh release upload" not in own
    assert "cdb_global_writer_lock.py acquire" not in own
    assert "RAPIDAPI_KEY:" not in own
    assert "PROPL:" not in own
    assert "provider_calls" not in own
