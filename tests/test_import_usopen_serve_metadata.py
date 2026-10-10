"""US Open sidecar -> CDB research marker safety and persistence tests."""
from datetime import datetime, timezone
from copy import deepcopy
import pytest
import json
import hashlib
import pandas as pd

from tbt.schemas import MatchRecord
from tbt.data.history_snapshot import write_snapshot, update_year_manifest, load_snapshot
from scripts.verify_usopen_serve_readback import verify

from scripts.import_usopen_serve_metadata import (
    ALLOWED, COUNT_FIELDS, DICT_FIELDS, MARKER_KEY, POLICY, SOURCE_NAME,
    SOURCE_BLOB, _stage_row, _serve, _signature, stage, write_local,
    write_exact_serve_markers,
)
from tbt.data.provider_context import minimize_provider_payload


class FakeMatch:
    match_id = "match1"
    tour = "atp"
    scheduled_at = datetime(2024, 8, 27, 12, tzinfo=timezone.utc)
    tournament = "US Open, New York"
    player1_id = "101"
    player2_id = "102"
    player1_name = "Alpha Tennis"
    player2_name = "Beta Tennis"
    def __init__(self):
        self.stats = {"p1_aces": 3}
        self.provider_payload = {"_tbt_provider_event_id": "event1"}


def serve():
    data = {}
    for key in ALLOWED:
        if key in DICT_FIELDS:
            data[key] = {"T": 1}
        elif key in COUNT_FIELDS:
            data[key] = 1
        elif key == "height_cm":
            data[key] = 185
        elif key == "ace_rate_per_serve_row":
            data[key] = .1
        elif key == "quality_label_mean":
            data[key] = 1.5
        elif key == "serve_duration_sec_mean":
            data[key] = 1.1
        elif key.startswith("speed_") or "serve_speed" in key:
            data[key] = 150.0
        else:
            data[key] = 1.0
    data["speed_kmh_max"] = 200.0
    return data


def raw():
    return {
        "schema": 2, "match_id": "match1", "source_match_id": "2024-usopen-1101",
        "source": SOURCE_NAME, "source_event": "US Open 2024",
        "feature_policy": POLICY, "license": "CC BY 4.0",
        "evidence": "unique canonical match, exact participants",
        "tour": "atp", "tournament": "US Open",
        "scheduled_date_utc": "2024-08-27", "player1_id": "101",
        "player2_id": "102", "player1_name": "Alpha Tennis", "player2_name": "Beta Tennis",
        "player1_serve": serve(), "player2_serve": serve(),
    }


def test_safe_stage_write_and_snapshot_roundtrip():
    match = FakeMatch()
    rows, counts = stage([match], [raw()])
    assert counts == {"source_rows": 1, "staged": 1}
    before_stats = dict(match.stats)
    years = write_local([match], rows)
    assert years == [2024]
    assert match.stats == before_stats
    assert match.provider_payload[MARKER_KEY]["source_ref_blob_sha"] == SOURCE_BLOB
    compact = minimize_provider_payload(match.provider_payload)
    assert compact[MARKER_KEY] == match.provider_payload[MARKER_KEY]
    assert compact["_tbt_provider_event_id"] == "event1"
    rows2, counts2 = stage([match], [raw()])
    assert rows2 == [] and counts2["already_present"] == 1


def test_rejects_identity_swap_and_wrong_year():
    match = FakeMatch()
    candidate = raw()
    candidate["player2_id"] = "999"
    with pytest.raises(ValueError, match="identity"):
        _stage_row(candidate, match)
    candidate = raw()
    candidate["scheduled_date_utc"] = "2025-08-27"
    with pytest.raises(ValueError, match="year"):
        _stage_row(candidate, match)


def test_rejects_broken_serve_counts_and_unverified_policy():
    candidate = serve()
    candidate["speed_observations"] = 5
    with pytest.raises(ValueError, match="denominator"):
        _serve(candidate)
    with pytest.raises(ValueError, match="schema"):
        _serve({"serve_rows": 1})
    candidate = raw()
    candidate["feature_policy"] = "prematch"
    with pytest.raises(ValueError, match="attribution"):
        _stage_row(candidate, FakeMatch())


def test_never_overwrites_existing_marker():
    m = FakeMatch()
    rows, _ = stage([m], [raw()])
    write_local([m], rows)
    with pytest.raises(ValueError, match="overwrite"):
        write_local([m], rows)
    m.provider_payload[MARKER_KEY]["source_match_id"] = "changed"
    with pytest.raises(ValueError, match="Conflicting"):
        stage([m], [raw()])


def test_rejects_duplicate_source_match_and_unpinned_context():
    with pytest.raises(ValueError, match="Duplicate"):
        stage([FakeMatch()], [raw(), raw()])
    m = FakeMatch()
    rows, _ = stage([m], [raw()])
    bad = deepcopy(rows)
    bad[0]["marker"]["source_ref_blob_sha"] = "fake"
    with pytest.raises(ValueError, match="provenance"):
        write_local([m], bad)


def test_exact_parquet_patch_preserves_every_unstaged_context(tmp_path):
    def build(mid, event):
        return MatchRecord(
            match_id=mid, tour="atp",
            scheduled_at=datetime(2024, 8, 27, 12, tzinfo=timezone.utc),
            player1_id="101", player1_name="Alpha Tennis",
            player2_id="102", player2_name="Beta Tennis",
            tournament="US Open", stats={"p1_aces": 4.0},
            provider_payload={"_tbt_provider_event_id": event},
        )

    first, second = build("m1", "e1"), build("m2", "e2")
    path = tmp_path / "history-2024.parquet"
    meta = write_snapshot([first, second], path)
    update_year_manifest(tmp_path, 2024, meta)
    # Preserve a legacy unknown context field. The ordinary MatchRecord
    # snapshot writer deliberately minimizes it; this import must NOT.
    frame = pd.read_parquet(path)
    frame.loc[frame.match_id == "m2", "provider_context_json"] = json.dumps({
        "_tbt_provider_event_id": "e2", "legacy_observation": {"safe": "keep"},
    })
    frame.loc[frame.match_id == "m1", "provider_context_json"] = json.dumps({
        "_tbt_provider_event_id": "e1", "legacy_source": "do-not-remove",
    })
    frame.to_parquet(path, engine="pyarrow", compression="zstd", index=False)
    update_year_manifest(tmp_path, 2024, {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size, "rows": 2,
    })
    before = load_snapshot(path)
    original_frame = pd.read_parquet(path)
    marker = {"schema": 1, "source_ref_blob_sha": SOURCE_BLOB,
              "source": SOURCE_NAME, "feature_policy": POLICY,
              "source_match_id": "test-source"}
    entry = {"schema": 1, "import_ready": True, "match_id": "m1",
             "canonical": _signature(first), "marker": marker}
    assert write_exact_serve_markers(tmp_path, [entry]) == [2024]
    after_frame = pd.read_parquet(path)
    assert before[0].stats == load_snapshot(path)[0].stats
    assert after_frame.columns.tolist() == original_frame.columns.tolist()
    assert after_frame.loc[after_frame.match_id == "m2"].equals(
        original_frame.loc[original_frame.match_id == "m2"]
    )
    current = json.loads(after_frame.loc[
        after_frame.match_id == "m1", "provider_context_json"].iloc[0])
    assert current["legacy_source"] == "do-not-remove"
    assert current[MARKER_KEY] == marker
    assert verify(before, load_snapshot(path), [entry])["enriched_matches"] == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        json.loads((tmp_path / "history_manifest.json").read_text())
        ["years"]["2024"]["sha256"]
    )


def test_exact_patch_rejects_mismatched_identity_without_changing_disk(tmp_path):
    first = MatchRecord(
        match_id="m1", tour="atp",
        scheduled_at=datetime(2024, 8, 27, 12, tzinfo=timezone.utc),
        player1_id="101", player1_name="Alpha Tennis",
        player2_id="102", player2_name="Beta Tennis",
        tournament="US Open",
        provider_payload={"_tbt_provider_event_id": "e1"},
    )
    path = tmp_path / "history-2024.parquet"
    meta = write_snapshot([first], path)
    update_year_manifest(tmp_path, 2024, meta)
    content_before = path.read_bytes()
    bad_sig = _signature(first)
    bad_sig["player1_id"] = "other"
    bad = {"schema": 1, "import_ready": True, "match_id": "m1",
           "canonical": bad_sig,
           "marker": {"source_ref_blob_sha": SOURCE_BLOB}}
    with pytest.raises(ValueError, match="identity changed"):
        write_exact_serve_markers(tmp_path, [bad])
    assert path.read_bytes() == content_before
