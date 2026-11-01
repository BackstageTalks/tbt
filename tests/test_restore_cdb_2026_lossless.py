"""Synthetic identity conservation for 2026 immutable backup recovery."""
from datetime import datetime, timezone

import pytest
import pyarrow as pa

from restore_cdb_2026_lossless import merge_preserving_live, _live_prefix_is_conserved


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


def typed_2026(ids, *, backup, best_of=None, rank1=None, rank2=None):
    source = table(ids)
    count = len(ids)
    return (source
            .append_column("best_of", pa.array(
                best_of if best_of is not None else ([3.0] * count if backup else [3] * count),
                type=pa.float64() if backup else pa.int64()))
            .append_column("player1_rank", pa.array(
                rank1 if backup else [None] * count,
                type=pa.float64() if backup else pa.null()))
            .append_column("player2_rank", pa.array(
                rank2 if backup else [None] * count,
                type=pa.float64() if backup else pa.null())))


def test_known_actual_2026_drift_is_losslessly_normalized():
    old = typed_2026(
        ["shared", "backup_only"], backup=True,
        best_of=[3.0, 5.0], rank1=[11.0, 87.0], rank2=[23.0, None])
    live = typed_2026(
        ["shared", "live_only"], backup=False, best_of=[3, 3])
    merged, counts, ids = merge_preserving_live(old, live)
    assert counts["old_only_restored"] == 1
    assert counts["live_only_preserved"] == 1
    assert counts["existing_cells_overwritten"] == 0
    assert merged.schema.field("best_of").type == pa.int64()
    assert merged.schema.field("player1_rank").type == pa.float64()
    assert merged.schema.field("player2_rank").type == pa.float64()
    assert merged["best_of"].to_pylist() == [3, 3, 5]
    assert merged["player1_rank"].to_pylist() == [None, None, 87.0]
    assert merged["player2_rank"].to_pylist() == [None, None, None]
    assert ids == {"shared", "live_only", "backup_only"}
    assert _live_prefix_is_conserved(live, merged)


@pytest.mark.parametrize("bad_value", [2.5, float("nan"), float("inf"), 6.0])
def test_non_integral_or_invalid_best_of_rejected(bad_value):
    old = typed_2026(["a"], backup=True, best_of=[bad_value], rank1=[4.0], rank2=[7.0])
    current = typed_2026(["b"], backup=False)
    with pytest.raises(ValueError, match="Unsafe backup best_of"):
        merge_preserving_live(old, current)


def test_other_type_drift_still_fails_closed():
    old = typed_2026(["a"], backup=True, rank1=[4.0], rank2=[7.0])
    current = typed_2026(["b"], backup=False)
    current = current.set_column(
        current.schema.get_field_index("player1_rank"),
        "player1_rank", pa.array([7], type=pa.int64()))
    with pytest.raises(ValueError, match="schema differs"):
        merge_preserving_live(old, current)


def test_null_typed_live_rank_keeps_all_its_original_nulls():
    old = typed_2026(["a"], backup=True, rank1=[55.0], rank2=[89.0])
    live = typed_2026(["b"], backup=False)
    merged, _, _ = merge_preserving_live(old, live)
    damaged = merged.set_column(
        merged.schema.get_field_index("player1_rank"),
        "player1_rank", pa.array([3.0, 55.0], type=pa.float64()))
    assert not _live_prefix_is_conserved(live, damaged)


def test_nan_old_ranks_rejected():
    old = typed_2026(["a"], backup=True, rank1=[float("nan")], rank2=[None])
    live = typed_2026(["b"], backup=False)
    with pytest.raises(ValueError, match="Unsafe backup rank"):
        merge_preserving_live(old, live)
