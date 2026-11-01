"""Synthetic identity conservation for 2026 immutable backup recovery."""
from datetime import datetime, timezone

import pytest
import pyarrow as pa

from restore_cdb_2026_lossless import merge_preserving_live


def table(ids, *, stats=None, player2=None):
    stats = stats or ["{}"] * len(ids)
    p2 = player2 or ["player_b"] * len(ids)
    return pa.table({
        "match_id": pa.array(ids, type=pa.string()),
        "player1_id": pa.array(["player_a"] * len(ids), type=pa.string()),
        "player2_id": pa.array(p2, type=pa.string()),
        "scheduled_at": pa.array(
            [datetime(2026, 4, 15, tzinfo=timezone.utc)] * len(ids),
            type=pa.timestamp("us", tz="UTC"),
        ),
        "stats_json": pa.array(stats, type=pa.string()),
    })


def test_backup_only_rows_appended_live_exactly_unchanged():
    old = table(["shared", "old_only"], stats=['{"aces":3}', '{"aces":7}'])
    current = table(["shared", "new_only"], stats=['{"aces":4}', '{"aces":5}'])
    merged, counts, ids = merge_preserving_live(old, current)
    assert merged.num_rows == 3
    assert merged.slice(0, 2).equals(current)
    assert counts["old_only_restored"] == 1
    assert counts["live_only_preserved"] == 1
    assert counts["conflicts_quarantined_live_precedence"] == 1
    assert counts["existing_cells_overwritten"] == 0
    assert merged["stats_json"][0].as_py() == '{"aces":4}'
    assert ids == {"shared", "old_only", "new_only"}


def test_null_on_current_not_overwritten():
    old = table(["shared"], stats=['{"aces":8}'])
    current = table(["shared"], stats=['{}'])
    merged, counts, _ = merge_preserving_live(old, current)
    assert counts["null_on_live_overlap_not_modified"] == 1
    assert merged.equals(current)


def test_overlap_identity_mismatch_fails_closed():
    old = table(["shared"])
    new = table(["shared"], player2=["different"])
    with pytest.raises(ValueError, match="identity conflict"):
        merge_preserving_live(old, new)


def test_duplicate_backup_identity_fails_closed():
    with pytest.raises(ValueError, match="duplicate"):
        merge_preserving_live(table(["same", "same"]), table(["shared"]))


def test_schema_drift_fails_closed():
    with pytest.raises(ValueError, match="schema differs") as exc:
        merge_preserving_live(table(["a"]), table(["a"]).drop(["stats_json"]))
    assert '"backup_only": {"stats_json": "string"}' in str(exc.value)
    assert "player_a" not in str(exc.value)
    assert "2026-04-15" not in str(exc.value)


def test_schema_type_difference_reported_without_coercion():
    old = table(["old_id"])
    current = table(["new_id"]).set_column(
        4, "stats_json", pa.array(["{}"], type=pa.large_string()))
    with pytest.raises(ValueError, match="type_differences") as exc:
        merge_preserving_live(old, current)
    assert '"backup": "string", "current": "large_string"' in str(exc.value)
    assert "old_id" not in str(exc.value)
