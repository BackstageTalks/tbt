"""Regression checks for bounded, still full-coverage CDB opponent-rate readback."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import shutil

import pytest

from scripts.recover_cdb_opponent_service_rates import stage, write_exact_stats_partition
from scripts.verify_cdb_scoped_rate_delta import verify_scoped
from tbt.data.history_snapshot import write_snapshot, update_year_manifest
from tbt.schemas import MatchRecord


def _match(year: int, *, stats: dict) -> MatchRecord:
    return MatchRecord(
        match_id=f"fixture-{year}", tour="wta",
        scheduled_at=datetime(year, 4, 12, tzinfo=timezone.utc),
        player1_id=f"p1-{year}", player1_name="One",
        player2_id=f"p2-{year}", player2_name="Two",
        tournament="Tournament", winner_id=f"p1-{year}",
        status="completed", stats=stats,
    )


def _fixture(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    older = _match(2024, stats={"p1_aces": 5})
    newer = _match(2026, stats={"p1_service_points_won": 0.62})
    for year, match in ((2024, older), (2026, newer)):
        path = before / f"history-{year}.parquet"
        meta = write_snapshot([match], path)
        update_year_manifest(before, year, meta)
    shutil.copytree(before, after)
    staged, counts = stage([newer], pairwise=True)
    assert counts["staged_matches"] == 1
    path = tmp_path / "stage.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in staged))
    write_exact_stats_partition(after, 2026, staged)
    return before, after, path


def test_scoped_readback_validates_all_rows_and_exact_changed_year(tmp_path):
    before, after, stage_file = _fixture(tmp_path)
    report = verify_scoped(before, after, stage_file)
    assert report["status"] == "verified"
    assert report["canonical_matches"] == 2
    assert report["changed_year_matches_checked"] == 1
    assert report["untouched_partition_hashes_verified"] == 1
    assert report["canonical_year_partitions_verified"] == 2
    assert report["enriched_matches"] == 1
    assert report["new_stat_values"] == 1
    assert report["existing_values_overwritten"] == 0
    assert report["provider_requests"] == 0
    assert report["production_mutated"] is False


def test_scoped_readback_rejects_changes_in_any_other_year(tmp_path):
    before, after, stage_file = _fixture(tmp_path)
    replacement = _match(2024, stats={"p1_aces": 999})
    meta = write_snapshot([replacement], after / "history-2024.parquet")
    update_year_manifest(after, 2024, meta)
    with pytest.raises(ValueError, match="Untouched year metadata changed"):
        verify_scoped(before, after, stage_file)


def test_scoped_readback_rejects_unstaged_changed_year_stat(tmp_path):
    before, after, stage_file = _fixture(tmp_path)
    replacement = _match(2026, stats={"p1_service_points_won": 0.62, "p2_return_points_won": 0.38, "p1_aces": 999})
    meta = write_snapshot([replacement], after / "history-2026.parquet")
    update_year_manifest(after, 2026, meta)
    with pytest.raises(ValueError, match="Unstaged or missing persisted statistics"):
        verify_scoped(before, after, stage_file)


def test_scoped_readback_rejects_duplicate_or_empty_staging(tmp_path):
    before, after, stage_file = _fixture(tmp_path)
    row = stage_file.read_text()
    stage_file.write_text(row + row)
    with pytest.raises(ValueError, match="Duplicate"):
        verify_scoped(before, after, stage_file)
    stage_file.write_text("")
    with pytest.raises(ValueError, match="Empty"):
        verify_scoped(before, after, stage_file)


def test_scoped_readback_refuses_partition_sha_drift(tmp_path):
    before, after, stage_file = _fixture(tmp_path)
    with (after / "history-2026.parquet").open("ab") as f:
        f.write(b"not-part-of-manifest")
    with pytest.raises(ValueError, match="digest differs from manifest"):
        verify_scoped(before, after, stage_file)
