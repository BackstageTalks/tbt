"""US Open sidecar -> CDB research marker safety and persistence tests."""
from datetime import datetime, timezone
from copy import deepcopy
import pytest

from scripts.import_usopen_serve_metadata import (
    ALLOWED, COUNT_FIELDS, DICT_FIELDS, MARKER_KEY, POLICY, SOURCE_NAME,
    SOURCE_BLOB, _stage_row, _serve, stage, write_local,
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
