"""Regression fixtures for strict 2023 Wimbledon 60-cell add-only writer."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.audit_wimbledon_2023_cdb_stage import SOURCE_SHA, SIDECAR_SHA
from scripts.import_wimbledon_2023_extended_exact import ALLOWED, patch, read_stage

FIELDS = sorted(ALLOWED)
MATCHES = [
    ("Ons Jabeur", "Elena Rybakina"),
    ("Madison Keys", "Aryna Sabalenka"),
    ("Ons Jabeur", "Aryna Sabalenka"),
    ("Elina Svitolina", "Marketa Vondrousova"),
    ("Marketa Vondrousova", "Ons Jabeur"),
]
CDB_SHA = "a" * 64

def synthetic():
    canonical, observations = [], []
    for ix, names in enumerate(MATCHES):
        match_id = f"fixture-{ix}"
        stats = {"p1_aces": 3, "p2_double_faults": 2, "unrelated_existing": 9}
        canonical.append({
            "match_id": match_id, "tour": "wta",
            "scheduled_at": pd.Timestamp("2023-07-12T11:00:00Z"),
            "tournament": "Wimbledon",
            "player1_name": names[0], "player2_name": names[1],
            "player1_id": f"player-a-{ix}", "player2_id": f"player-b-{ix}",
            "stats_json": json.dumps(stats), "other_immutable_field": "KEEP",
        })
        for field in FIELDS:
            side = 1 if field.startswith("p1_") else 2
            value = 0 if "break_points_won" in field else 2
            observations.append({
                "contract_version": "1.0.0",
                "source_id": "figshare_wimbledon_2023_momentum",
                "source_version": {"content_sha256": SOURCE_SHA},
                "source_record_id": f"{match_id}:whole_match:{field}",
                "canonical_match_id": match_id,
                "source_identity": {
                    "original_player1": names[0], "original_player2": names[1], "tour": "WTA"},
                "field": field, "value": value, "unit": "count", "scope": "whole_match",
                "available_at": None,
                "model_eligibility": "postmatch_only_for_future_matches",
                "provenance": {"raw_content_sha256": SOURCE_SHA, "license_basis": "CC BY 4.0"},
                "match_evidence": {"ambiguity_candidates": 1},
                "player_orientation": {
                    "relation": "same", "swapped": False,
                    "canonical_subject": names[0] if side == 1 else names[1]},
                "validation": {
                    "state": "READY_MISSING", "validated_against_cdb_sha256": CDB_SHA,
                    "expected_original_value": None},
                "import_eligibility": "candidate_after_package_review",
            })
    return pd.DataFrame(canonical), observations

def test_exact_sixty_additions_preserve_all_other_values():
    before, rows = synthetic()
    after, report = patch(before, rows, CDB_SHA)
    assert report == {
        "changed_matches": 5, "added_values": 60,
        "existing_values_overwritten": 0, "canonical_rows": 5}
    assert len(FIELDS) == 12
    pd.testing.assert_frame_equal(before.drop(columns=["stats_json"]), after.drop(columns=["stats_json"]))
    for i in range(5):
        old = json.loads(before.at[i, "stats_json"])
        new = json.loads(after.at[i, "stats_json"])
        assert new.items() >= old.items()
        assert len(new) == len(old) + 12
        assert new["p1_break_points_won"] == 0

@pytest.mark.parametrize("bad", [
    lambda rows: rows[0].update(field="p1_aces"),
    lambda rows: rows[0].update(value=201),
    lambda rows: rows[0].update(value=float("nan")),
    lambda rows: rows[0].update(value=True),
    lambda rows: rows[0].update(available_at="2023-07-01T12:00:00Z"),
    lambda rows: rows[0]["validation"].update(validated_against_cdb_sha256="b" * 64),
    lambda rows: rows[0]["player_orientation"].update(swapped=True),
    lambda rows: rows[0]["source_identity"].update(original_player1="Someone else"),
    lambda rows: rows[0]["provenance"].update(license_basis="unknown"),
    lambda rows: rows[0]["validation"].update(expected_original_value=0),
])
def test_unsafe_observation_fails_closed(bad):
    before, stage = synthetic()
    stage = copy.deepcopy(stage)
    bad(stage)
    with pytest.raises((ValueError, AssertionError)):
        patch(before, stage, CDB_SHA)

def test_conflict_rejected_no_overwrite():
    before, rows = synthetic()
    before.at[0, "stats_json"] = json.dumps({"p1_winners": 99})
    with pytest.raises(ValueError):
        patch(before, rows, CDB_SHA)

def test_duplicate_observation_rejected():
    before, rows = synthetic()
    rows[-1] = copy.deepcopy(rows[0])
    with pytest.raises(ValueError):
        patch(before, rows, CDB_SHA)

def test_current_source_sha_and_five_complete_tapes_required(tmp_path: Path):
    _, rows = synthetic()
    path = tmp_path / "observations.jsonl"
    path.write_text("\n".join(json.dumps(v) for v in rows), encoding="utf-8")
    report = {
        "status": "read_only_classified", "production_mutated": False,
        "write_authorized": False, "model_promoted": False,
        "source_sha256": SOURCE_SHA, "sidecar_sha256": SIDECAR_SHA,
        "observation_rows": 60, "quarantined_matches": 0,
        "baseline_control_fields_already_present": 20,
        "counts": {
            "linked_matches_compared": 5, "tape_complete_matches": 5,
            "READY_MISSING": 60, "CONFLICT": 0, "UNRESOLVED": 0},
    }
    assert len(read_stage(path, report)) == 60
    bad = copy.deepcopy(report)
    bad["counts"]["READY_MISSING"] = 59
    with pytest.raises(ValueError):
        read_stage(path, bad)
    bad = copy.deepcopy(report)
    bad["baseline_control_fields_already_present"] = 19
    with pytest.raises(ValueError):
        read_stage(path, bad)
    bad = copy.deepcopy(report)
    bad["quarantined_matches"] = 1
    with pytest.raises(ValueError):
        read_stage(path, bad)

def test_existing_ace_df_control_is_never_mutated():
    before, rows = synthetic()
    after, _ = patch(before, rows, CDB_SHA)
    for i in range(5):
        values = json.loads(after.at[i,"stats_json"])
        assert values["p1_aces"] == 3
        assert values["p2_double_faults"] == 2
        assert values["unrelated_existing"] == 9
