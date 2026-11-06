"""The diagnostic exposes counts only and never authors CDB mutations."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pyarrow as pa
import pytest

from audit_cdb_2026_missing_identity import compare_origins, classify_identity_drift


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
    assert '"tour", "tournament_id", "player1_id"' in source
    # The 1 Nov logged source_manifest_sha256 is the BUNDLE manifest digest.
    # The enclosed year manifest and Parquet must be checked against its files.
    assert 'if sha(prewrite_bundle) != PREWRITE_MANIFEST_SHA:' in source
    assert 'covered[name].get("sha256") != sha(path)' in source
    assert 'if sha(prewrite_manifest_path) != PREWRITE_MANIFEST_SHA:' not in source


def test_missing_identity_candidate_is_only_classified_not_recovered():
    when = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    def records(rows):
        return pa.Table.from_pylist([
            {"match_id": id, "tour": "atp", "tournament_id": tourn,
             "player1_id": p1, "player2_id": p2, "scheduled_at": when}
            for id, tourn, p1, p2 in rows
        ])
    old = records([
        ("old-original", "tourn-A", "player-a", "player-b"),
        ("unresolved", "tourn-X", "player-x", "player-y"),
        ("missing-no-tourn", "", "player-p", "player-q"),
    ])
    prewrite = records([("original-live", "tourn-B", "player-c", "player-d")])
    current = records([
        ("new-match-id", "tourn-A", "player-b", "player-a"),
        ("original-live", "tourn-B", "player-c", "player-d"),
        ("new-no-tourn", "", "player-p", "player-q"),
    ])
    report = classify_identity_drift(old, prewrite, current)
    assert report["unique_missing_source_ids"] == 3
    assert report["missing_with_one_strong_rekey_candidate"] == 1
    assert report["missing_without_strong_rekey_candidate"] == 1
    assert report["missing_without_source_tournament_id"] == 1
    assert report["existing_id_player_or_time_conflict"] == 0
    assert not any(term in json.dumps(report) for term in
                   ("old-original", "player-a", "tourn-A", "new-match-id"))


def test_prewrite_identity_orientation_and_date_conflict_are_aggregate_only():
    when = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    other = datetime(2026, 11, 1, 13, tzinfo=timezone.utc)
    def rows(items):
        return pa.Table.from_pylist([
            {"match_id": mid, "tour": "wta", "tournament_id": "T",
             "player1_id": a, "player2_id": b, "scheduled_at": start}
            for mid, a, b, start in items
        ])
    old = rows([("a", "x", "y", when)])
    prewrite = rows([
        ("a", "x", "y", when),
        ("b", "p", "q", when),
        ("c", "r", "s", when),
    ])
    current = rows([
        ("a", "y", "x", when),
        ("b", "p", "q", other),
        ("c", "r", "new", when),
    ])
    report = classify_identity_drift(old, prewrite, current)
    assert report["unique_missing_source_ids"] == 0
    assert report["existing_id_player_or_time_conflict"] == 3
    assert report["existing_id_swapped_orientation"] == 1
    assert report["existing_id_changed_scheduled_at"] == 1
    assert report["existing_id_time_shift_under_24h"] == 1
    assert report["existing_id_changed_player_pair"] == 1


def test_rekey_after_kickoff_time_shift_is_candidate_not_an_automatic_merge():
    when = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    shifted = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    def make(rows):
        return pa.Table.from_pylist([
            {"match_id": mid, "tour": "atp", "tournament_id": "T-verified",
             "player1_id": a, "player2_id": b, "scheduled_at": date}
            for mid, a, b, date in rows
        ])
    old = make([("original-id", "A", "B", when)])
    prewrite = make([("original-id", "A", "B", when)])
    now = make([("new-id", "B", "A", shifted)])
    report = classify_identity_drift(old, prewrite, now)
    assert report["unique_missing_source_ids"] == 1
    assert report["missing_with_one_strong_rekey_candidate"] == 0
    assert report["missing_with_one_7day_time_shift_candidate"] == 1
    assert report["missing_without_7day_time_shift_candidate"] == 0
    assert "original-id" not in json.dumps(report)
