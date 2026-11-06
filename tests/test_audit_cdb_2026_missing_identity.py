"""The diagnostic exposes counts only and never authors CDB mutations."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pyarrow as pa
import pytest

from audit_cdb_2026_missing_identity import compare_origins


def table(names):
    when = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    return pa.Table.from_pylist([
        {"match_id": key, "player1_id": a, "player2_id": b,
         "scheduled_at": when, "stats_json": json.dumps(stats)}
        for key, a, b, stats in names
    ])


def test_current_drift_aggregate_has_no_raw_ids_or_stat_values():
    old = table([
        ("common", "a", "b", {"aces": 2}),
        ("restored", "c", "d", {"aces": 5}),
    ])
    before = table([
        ("common", "a", "b", {"aces": 3}),
        ("prewrite_only", "e", "f", {"serve": .9}),
    ])
    current = table([
        ("common", "a", "b", {"aces": 3}),
        ("prewrite_only", "e", "f", {"serve": .9}),
    ])
    report = compare_origins(old, before, current, expected=(2, 2, 1, 1, 1))
    assert report["backup_ids_missing_now"] == 1
    assert report["prewrite_ids_missing_now"] == 0
    assert report["original_backup_only_id_count"] == 1
    assert report["prewrite_only_ids_preserved_now"] == 1
    assert report["current_2026_rows"] == 2
    assert all(private not in json.dumps(report) for private in
               ("common", "restored", "prewrite_only", "aces", "serve"))


def test_lost_prewrite_and_changed_player_identity_are_reported_not_overwritten():
    old = table([
        ("common", "a", "b", {}),
        ("restored", "c", "d", {}),
    ])
    before = table([
        ("common", "a", "b", {}),
        ("prewrite_only", "e", "f", {}),
    ])
    changed = table([
        ("common", "b", "a", {}),
        ("restored", "c", "d", {}),
    ])
    report = compare_origins(old, before, changed, expected=(2, 2, 1, 1, 1))
    assert report["backup_ids_missing_now"] == 0
    assert report["prewrite_ids_missing_now"] == 1
    assert report["prewrite_identity_conflicts_now"] == 1
    assert report["prewrite_only_ids_preserved_now"] == 0


def test_pinned_lineage_cohort_counts_never_silently_change():
    old = table([("only_old", "a", "b", {})])
    before = table([("only_old", "a", "b", {})])
    current = table([("only_old", "a", "b", {})])
    with pytest.raises(ValueError, match="authoritative 1 Nov"):
        compare_origins(old, before, current, expected=(98994, 2927, 1258, 97736, 1669))


def test_private_diagnostic_workflow_is_aggregate_only_no_writer():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/cdb-2026-loss-audit.yml").read_text()
    isolated = workflow.split("  current-drift-forensics:\n", 1)[1]
    assert "github.event_name == 'pull_request'" in isolated
    assert "github.event.pull_request.head.repo.full_name == 'BackstageTalks/tbt'" in isolated
    assert "audit_cdb_2026_missing_identity.py" in isolated
    assert "drift-report.json" in isolated
    assert "cdb_global_writer_lock.py acquire" not in isolated
    assert "gh release upload" not in isolated
    assert "RAPIDAPI_KEY:" not in isolated
    assert "PROPL:" not in isolated
    source = (root / "scripts/audit_cdb_2026_missing_identity.py").read_text()
    assert "download_stable(REPO, TAG" in source
    assert "merge_preserving_live(" in source
    assert "raise RuntimeError(\"Current canonical identity drift detected" in source
    assert "upload_bundle" not in source
