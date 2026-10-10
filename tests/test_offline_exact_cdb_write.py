"""Historical source importer must not change unrelated CDB rows or legacy fields."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import shutil

import pandas as pd
import pytest

from scripts.offline_exact_cdb_write import (
    write_exact_stats_partition, verify_persisted,
)
from scripts.import_offline_linked_serve_return import _signature
from tbt.data.history_snapshot import load_snapshot, update_year_manifest, write_snapshot
from tbt.schemas import MatchRecord


def match(mid, stats=None):
    return MatchRecord(
        match_id=mid, tour="atp",
        scheduled_at=datetime(2018, 7, 15, 12, tzinfo=timezone.utc),
        player1_id="p1", player1_name="Alpha",
        player2_id="p2", player2_name="Beta",
        winner_id="p1", tournament="Wimbledon", status="completed",
        stats=stats or {},
        provider_payload={"_tbt_provider_event_id": "event-" + mid},
    )


def prepare(tmp_path):
    original = tmp_path / "original"
    working = tmp_path / "working"
    original.mkdir()
    working.mkdir()
    first, second = match("first", {"p1_aces": 5.0}), match("other", {"p2_aces": 8.0})
    path = original / "history-2018.parquet"
    metadata = write_snapshot([first, second], path)
    update_year_manifest(original, 2018, metadata)
    frame = pd.read_parquet(path)
    frame.loc[frame.match_id == "other", "provider_context_json"] = json.dumps({
        "_tbt_provider_event_id": "event-other",
        "legacy_details": {"must": "remain"},
    })
    frame.to_parquet(path, engine="pyarrow", compression="zstd", index=False)
    update_year_manifest(original, 2018, {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size, "rows": 2,
    })
    for path in original.iterdir():
        shutil.copy2(path, working / path.name)
    return original, working


def test_exact_additions_preserve_unstaged_parquet_and_verify_disk(tmp_path):
    original, working = prepare(tmp_path)
    before = load_snapshot(original / "history-2018.parquet")
    after = deepcopy(before)
    after[0].stats["p1_service_points_won"] = 0.63
    original_frame = pd.read_parquet(original / "history-2018.parquet")
    result = write_exact_stats_partition(working, 2018, after, {"first"})
    assert result == {
        "year": 2018, "matches_checked": 2,
        "enriched_matches": 1, "added_values": 1, "existing_values_overwritten": 0,
    }
    new_frame = pd.read_parquet(working / "history-2018.parquet")
    assert new_frame.loc[new_frame.match_id == "other"].equals(
        original_frame.loc[original_frame.match_id == "other"]
    )
    assert new_frame.columns.tolist() == original_frame.columns.tolist()
    stage = [{"schema": 1, "import_ready": True, "match_id": "first",
              "canonical": _signature(before[0]),
              "incoming_stats": {"p1_service_points_won": 0.63}}]
    verified = verify_persisted(original, working, stage, [2018])
    assert verified["enriched_matches"] == 1
    assert verified["added_values"] == 1
    assert verified["canonical_rows_checked"] == 2
    manifest = json.loads((working / "history_manifest.json").read_text())
    assert manifest["years"]["2018"]["sha256"] == hashlib.sha256(
        (working / "history-2018.parquet").read_bytes()
    ).hexdigest()


def test_conflicting_original_stats_rejected_without_disk_mutation(tmp_path):
    original, working = prepare(tmp_path)
    before = load_snapshot(original / "history-2018.parquet")
    after = deepcopy(before)
    after[0].stats["p1_aces"] = 99.0
    path = working / "history-2018.parquet"
    original_bytes = path.read_bytes()
    with pytest.raises(ValueError, match="Existing canonical statistic changed"):
        write_exact_stats_partition(working, 2018, after, {"first"})
    assert path.read_bytes() == original_bytes


def test_unstaged_change_and_identity_swap_are_rejected(tmp_path):
    original, working = prepare(tmp_path)
    before = load_snapshot(original / "history-2018.parquet")
    after = deepcopy(before)
    after[0].stats["p1_service_points_won"] = 0.63
    after[1].tournament = "Wrong"
    with pytest.raises(ValueError, match="Unstaged match mutated"):
        write_exact_stats_partition(working, 2018, after, {"first"})
    after = deepcopy(before)
    after[0].stats["p1_service_points_won"] = 0.63
    after[0].player1_id = "wrong"
    with pytest.raises(ValueError, match="identity or context change"):
        write_exact_stats_partition(working, 2018, after, {"first"})


def test_full_readback_rejects_unstaged_overwrite(tmp_path):
    original, working = prepare(tmp_path)
    rows = load_snapshot(original / "history-2018.parquet")
    stage = [{"schema": 1, "import_ready": True, "match_id": "first",
              "canonical": _signature(rows[0]),
              "incoming_stats": {"p1_service_points_won": 0.63}}]
    changed = deepcopy(rows)
    changed[0].stats["p1_aces"] = 500.0
    write_snapshot(changed, working / "history-2018.parquet")
    with pytest.raises(ValueError, match="Unstaged/missing persisted stats"):
        verify_persisted(original, working, stage, [2018])
