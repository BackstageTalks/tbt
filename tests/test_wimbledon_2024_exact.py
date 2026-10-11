"""No-network synthetic regression for Wimbledon 2024 add-only CDB adapter."""
from __future__ import annotations
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from stage_wimbledon_2024_cdb import classify, count, digest
from import_wimbledon_2024_exact import _patch, _validated_stage
from stage_wimbledon_2024_cdb import MATCH_SHA, POINT_SHA


def sample():
    frame = pd.DataFrame([{
        "match_id": "canonical-1", "tour": "atp",
        "scheduled_at": pd.Timestamp("2024-07-01T12:00:00Z"),
        "tournament": "Wimbledon", "player1_id": "id1", "player2_id": "id2",
        "player1_name": "Alice", "player2_name": "Bob",
        "stats_json": json.dumps({"p1_aces": 1}),
    }])
    # Deliberately reversed source orientation; 0 is a valid observed count.
    match = {
        "match_id": "2024-wimbledon-1101", "Year": "2024",
        "Player1Name": "Bob", "Player2Name": "Alice",
        "Player1Ace": "0", "Player1DoubleFault": "1",
        "Player1UnforcedError": "3", "Player1NetPoint": "4",
        "Player1NetPointWon": "2",
        "Player2Ace": "1", "Player2DoubleFault": "0",
        "Player2UnforcedError": "2", "Player2NetPoint": "6",
        "Player2NetPointWon": "5",
    }
    points = [{
        "match_id": "2024-wimbledon-1101", "SetNumber": "1",
        "GameNumber": "1", "PointNumberInGame": "1", "PointServerPlayer": "1",
        "IsAcePoint": "0", "IsDoubleFaultPoint": "1",
    }, {
        "match_id": "2024-wimbledon-1101", "SetNumber": "1",
        "GameNumber": "1", "PointNumberInGame": "2", "PointServerPlayer": "2",
        "IsAcePoint": "1", "IsDoubleFaultPoint": "0",
    }]
    return frame, match, points


def test_true_zero_swap_and_null_only_stage():
    frame, raw, points = sample()
    stage, quarantine, metrics = classify([raw], points, frame, "a" * 64)
    assert not quarantine
    assert metrics["clean_matches"] == metrics["staged_matches"] == 1
    assert metrics["staged_fields"] == 9
    assert stage[0]["swapped"] is True
    assert stage[0]["additions"]["p2_double_faults"] == 1
    assert stage[0]["additions"]["p1_double_faults"] == 0
    assert stage[0]["additions"]["p2_net_points_won"] == 2
    assert stage[0]["expected_original_null_fields"] == sorted(stage[0]["additions"])
    result, delta = _patch(frame, stage)
    assert delta["canonical-1"]["p1_double_faults"] == 0
    assert json.loads(result.at[0, "stats_json"])["p1_aces"] == 1
    assert result.at[0, "match_id"] == frame.at[0, "match_id"]
    with pytest.raises(ValueError, match="overwrite"):
        _patch(result, stage)


def test_source_conflict_is_whole_match_quarantine():
    frame, raw, points = sample()
    frame.at[0, "stats_json"] = json.dumps({"p1_aces": 100})
    stage, quarantine, metrics = classify([raw], points, frame, "a" * 64)
    assert stage == []
    assert metrics["conflicting_matches"] == 1
    assert metrics["missing_on_conflicting_matches"] == 9
    assert quarantine[0]["reason"] == "canonical_stat_conflict"


def test_incomplete_or_malformed_point_tape_quarantined():
    frame, raw, points = sample()
    stage, quarantine, _ = classify([raw], points[:1], frame, "a" * 64)
    assert stage == [] and quarantine[0]["reason"] == "point_or_match_value_inconsistent"
    points.append(dict(points[0]))
    stage, quarantine, _ = classify([raw], points, frame, "a" * 64)
    assert stage == [] and quarantine[0]["reason"] == "point_or_match_value_inconsistent"


def test_duplicate_source_matches_rejected():
    frame, raw, points = sample()
    with pytest.raises(ValueError, match="Duplicate source"):
        classify([raw, raw], points, frame, "a" * 64)


def test_counts_missing_negative_and_noninteger():
    for bad in ("", "-1", "nan", "inf", "2.5", "1001", None):
        with pytest.raises(ValueError):
            count(bad)
    assert count("0") == 0 and count("10.0") == 10


def test_identity_drift_and_non_null_source_validation():
    frame, raw, points = sample()
    stage, _, _ = classify([raw], points, frame, "a" * 64)
    frame.at[0, "player1_id"] = "different"
    with pytest.raises(ValueError, match="identity/context drift"):
        _patch(frame, stage)
    frame.at[0, "player1_id"] = "id1"
    stage[0]["additions"]["p1_aces"] = 7
    with pytest.raises(ValueError, match="non-null CDB overwrite"):
        _patch(frame, stage)


def test_stage_digest_and_proof_guards(tmp_path):
    frame, raw, points = sample()
    stage, _, metrics = classify([raw], points, frame, "a" * 64)
    p = tmp_path / "stage.jsonl"
    p.write_text(json.dumps(stage[0]) + "\n")
    r = tmp_path / "report.json"
    report = {
        "schema": 1, "status": "prepared_for_isolated_replay",
        "write_performed": False, "model_trained": False, "year": 2024,
        "cdb_sha256": "a" * 64, "match_sha256": MATCH_SHA, "points_sha256": POINT_SHA,
        "stage_sha256": digest(p), "stage_has_conflicts": False,
        "counts": metrics,
    }
    r.write_text(json.dumps(report))
    rows, _ = _validated_stage(p, r, "a" * 64)
    assert len(rows) == 1
    with pytest.raises(ValueError, match="stale"):
        _validated_stage(p, r, "b" * 64)
    report["stage_has_conflicts"] = True
    r.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="conflicting"):
        _validated_stage(p, r, "a" * 64)
