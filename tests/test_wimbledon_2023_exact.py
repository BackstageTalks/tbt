"""Wimbledon exact-cell CDB import safety regression cases."""
from __future__ import annotations
import copy
import json

import pandas as pd
import pytest

from scripts.audit_wimbledon_2023_cdb_stage import SOURCE_SHA
from scripts.import_wimbledon_2023_exact import patch, read_stage


FIELDS = ["p1_aces", "p2_aces", "p1_double_faults", "p2_double_faults"]
NAMES = [("Ons Jabeur", "Elena Rybakina"), ("Madison Keys", "Aryna Sabalenka"),
         ("Ons Jabeur", "Aryna Sabalenka"), ("Test Alpha", "Test Beta"),
         ("Test Gamma", "Test Delta")]


def fixture():
    records, stage = [], []
    for ix, (p1, p2) in enumerate(NAMES):
        mid = "test-match-" + str(ix)
        existing = {} if ix < 3 else dict.fromkeys(FIELDS, 2)
        records.append({
            "match_id": mid, "tour": "wta", "scheduled_at": pd.Timestamp("2023-07-12T11:00:00Z"),
            "tournament": "Wimbledon", "player1_name": p1, "player2_name": p2,
            "player1_id": "a-" + str(ix), "player2_id": "b-" + str(ix),
            "stats_json": json.dumps(existing), "other_immutable_field": "KEEP",
        })
        for field in FIELDS:
            ready = ix < 3
            stage.append({
                "contract_version": "1.0.0", "source_id": "figshare_wimbledon_2023_momentum",
                "source_version": {"content_sha256": SOURCE_SHA}, "canonical_match_id": mid,
                "source_identity": {"original_player1": p1, "original_player2": p2, "tour": "WTA"},
                "field": field, "value": 2, "unit": "count", "scope": "whole_match",
                "available_at": None, "model_eligibility": "postmatch_only_for_future_matches",
                "provenance": {"raw_content_sha256": SOURCE_SHA, "license_basis": "CC BY 4.0"},
                "match_evidence": {"ambiguity_candidates": 1},
                "player_orientation": {"relation": "same", "swapped": False,
                                       "canonical_subject": p1 if field.startswith("p1_") else p2},
                "validation": {"validated_against_cdb_sha256": "a" * 64,
                               "state": "READY_MISSING" if ready else "ALREADY_PRESENT",
                               "expected_original_value": None if ready else 2},
                "import_eligibility": "candidate_after_package_review" if ready else "blocked",
            })
    return pd.DataFrame(records), stage


def test_only_twelve_missing_stats_add_and_every_unstaged_cell_preserved():
    before, stage = fixture()
    after, counts = patch(before, stage, "a" * 64)
    assert counts == {"changed_matches": 3, "added_values": 12,
                      "existing_values_overwritten": 0, "canonical_rows": 5}
    assert json.loads(before.iloc[0].stats_json) == {}
    assert json.loads(after.iloc[0].stats_json) == dict.fromkeys(FIELDS, 2)
    pd.testing.assert_frame_equal(before.iloc[3:], after.iloc[3:])
    pd.testing.assert_frame_equal(before.drop(columns=["stats_json"]),
                                  after.drop(columns=["stats_json"]))


@pytest.mark.parametrize("transform", [
    lambda r: r.update(value=3),
    lambda r: r.update(field="p1_winners"),
    lambda r: r["source_version"].update(content_sha256="0" * 64),
    lambda r: r.update(available_at="2023-07-11T00:00:00Z"),
    lambda r: r["player_orientation"].update(swapped=True),
    lambda r: r["validation"].update(validated_against_cdb_sha256="0" * 64),
    lambda r: r["source_identity"].update(original_player1="Unknown"),
    lambda r: r.update(unit="percent"),
])
def test_invalid_staged_values_are_fail_closed(transform):
    before, stage = fixture()
    stage = copy.deepcopy(stage)
    transform(stage[0])
    with pytest.raises((ValueError, AssertionError)):
        patch(before, stage, "a" * 64)


def test_existing_conflict_does_not_overwrite():
    before, stage = fixture()
    before.at[3, "stats_json"] = json.dumps(dict.fromkeys(FIELDS, 3))
    with pytest.raises(ValueError):
        patch(before, stage, "a" * 64)


def test_missing_changed_identity_rejected():
    before, stage = fixture()
    before.at[0, "match_id"] = "unknown"
    with pytest.raises(ValueError):
        patch(before, stage, "a" * 64)


def test_duplicate_source_identity_rejected():
    before, stage = fixture()
    stage[-1] = copy.deepcopy(stage[0])
    with pytest.raises(ValueError):
        # Separate stage reader must also enforce all twenty source-canonical cells.
        # The writer rejects duplicates before allowing physical publication.
        patch(before, stage, "a" * 64)


def test_stage_report_counts_are_required(tmp_path):
    _, stage = fixture()
    source = tmp_path / "observations.jsonl"
    source.write_text("\n".join(json.dumps(item) for item in stage))
    report = {"status": "read_only_classified", "production_mutated": False,
              "write_authorized": False, "model_promoted": False,
              "source_sha256": SOURCE_SHA,
              "sidecar_sha256": "8c9b00eb96582cb5bfe3449b0bdb2dffbfb11d3fc387e54e142d645e6d43e316",
              "observation_rows": 20,
              "counts": {"linked_matches_compared": 5, "tape_complete_matches": 5,
                         "READY_MISSING": 12, "ALREADY_PRESENT": 8}}
    assert len(read_stage(source, report)) == 20
    report["counts"]["READY_MISSING"] = 11
    with pytest.raises(ValueError):
        read_stage(source, report)
