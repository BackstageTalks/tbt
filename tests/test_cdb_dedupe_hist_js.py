import json
from datetime import datetime, timezone

import pandas as pd
import pytest

import cdb_dedupe_hist_js as dd
from release_store import assert_history_rows_monotonic, assert_history_identities_conserved


def _frame():
    t = pd.Timestamp("2024-03-05T10:00:00Z")
    return pd.DataFrame({
        "match_id": ["n1", "hist-js:itf:1", "hist-js:itf:2", "n2", "n3"],
        "scheduled_at": [t, t + pd.Timedelta(days=1), t, t, t],
        "player1_id": ["a", "b", "c", "c", "e"],
        "player2_id": ["b", "a", "d", "d", "f"],
        "winner_id": ["a", "a", "c", "d", "e"],
        "stats_json": [json.dumps({"p1_aces": 3}),
                       json.dumps({"p1_aces": 9, "p2_aces": 3, "p1_double_faults": 2, "junk": 1}),
                       "{}", "{}", "{}"],
    })


def test_plan_requires_same_week_players_and_winner_and_moves_oriented_stats():
    rows, _ = dd.plan_year(_frame(), 2024)
    assert [(r["remove_id"], r["keep_id"]) for r in rows] == [("hist-js:itf:1", "n1")]
    # hist-js p1 = native p2 -> swapped; existing p1_aces kept; junk dropped
    assert rows[0]["stat_additions"] == {"p2_aces": 9.0, "p2_double_faults": 2.0}


def test_rows_guard_allows_only_approved_removals():
    old = {"years": {"2024": {"rows": 10}}}
    assert_history_rows_monotonic(old, {"years": {"2024": {"rows": 9}}}, approved_removals={2024: {"x"}})
    with pytest.raises(ValueError):
        assert_history_rows_monotonic(old, {"years": {"2024": {"rows": 8}}}, approved_removals={2024: {"x"}})


def test_identity_guard_requires_exact_approved_set(tmp_path):
    t = datetime(2024, 3, 5, tzinfo=timezone.utc)
    base = pd.DataFrame({"match_id": ["a", "b", "c"], "player1_id": ["1", "3", "5"],
                         "player2_id": ["2", "4", "6"], "scheduled_at": [t, t, t]})
    base.to_parquet(tmp_path / "old.parquet")
    base[base.match_id != "b"].to_parquet(tmp_path / "new.parquet")
    assert_history_identities_conserved(tmp_path / "old.parquet", tmp_path / "new.parquet",
                                        year=2024, approved_removed_ids={"b"})
    with pytest.raises(ValueError):
        assert_history_identities_conserved(tmp_path / "old.parquet", tmp_path / "new.parquet", year=2024)
    with pytest.raises(ValueError):
        assert_history_identities_conserved(tmp_path / "old.parquet", tmp_path / "new.parquet",
                                            year=2024, approved_removed_ids={"c"})
