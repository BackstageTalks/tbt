"""Exact-cell full-year Wimbledon import controls: no overwrite, side swap, no scope leakage."""
import json

import pandas as pd
import pytest

from scripts.import_wimbledon_2023_exact import patch

BASE = "f" * 64
FIELDS = ("p1_aces", "p2_aces", "p1_double_faults", "p2_double_faults")


def fixture():
    rows, observations = [], []
    for i in range(5):
        one, two = f"Player {i} A", f"Player {i} B"
        values = {f: 2 + i for f in FIELDS} if i >= 3 else {}
        row = {
            "match_id": f"match-{i}", "tour": "wta",
            "scheduled_at": pd.Timestamp("2023-07-12T11:00:00Z"),
            "player1_id": f"p-{i}-a", "player2_id": f"p-{i}-b",
            "player1_name": one, "player2_name": two,
            "tournament": "Wimbledon", "best_of": 3, "winner_id": f"p-{i}-a",
            "stats_json": json.dumps(values), "provider_context_json": '{"source":"baseline"}',
            "other_immutable": i,
        }
        rows.append(row)
        reverse = i == 1
        for field in FIELDS:
            side = 1 if field.startswith("p1_") else 2
            src_side = 3 - side if reverse else side
            val = 2 + i
            observations.append({
                "contract_version": "1.0.0",
                "source_id": "figshare_wimbledon_2023_momentum",
                "source_version": {"content_sha256": "19507e156e6ff307027d39e44000ac446a564f87b3c8d59a5225dc6d1674c512"},
                "canonical_match_id": f"match-{i}",
                "field": field, "value": val, "scope": "whole_match",
                "source_identity": {"original_player1": two if reverse else one,
                                    "original_player2": one if reverse else two},
                "player_orientation": {
                    "relation": "reversed" if reverse else "same",
                    "swapped": reverse, "canonical_subject": one if side == 1 else two,
                    "source_subject": one if side == 1 and src_side == 2 and reverse
                    else two if side == 2 and src_side == 1 and reverse
                    else one if side == 1 else two,
                },
                "import_eligibility": "candidate_after_package_review" if i < 3 else "blocked",
                "validation": {"state": "READY_MISSING" if i < 3 else "ALREADY_PRESENT",
                               "expected_original_value": None if i < 3 else val,
                               "validated_against_cdb_sha256": BASE},
            })
    return pd.DataFrame(rows), observations


def test_patches_only_twelve_missing_stats_and_no_other_cells():
    before, stage = fixture()
    after, result = patch(before, stage, baseline_sha=BASE)
    assert result["stats_fields_added"] == 12
    assert result["updated_matches"] == 3
    assert result["existing_stats_overwritten"] == 0
    assert list(before["stats_json"])[3:] == list(after["stats_json"])[3:]
    for i in range(3):
        assert json.loads(after.at[i, "stats_json"]) == {f: 2 + i for f in FIELDS}
        assert json.loads(before.at[i, "stats_json"]) == {}
    pd.testing.assert_frame_equal(before.drop(columns=["stats_json"]),
                                  after.drop(columns=["stats_json"]))


def test_block_overwrite_even_if_stage_claims_missing():
    before, stage = fixture()
    initial = json.loads(before.at[0, "stats_json"])
    initial["p1_aces"] = 99
    before.at[0, "stats_json"] = json.dumps(initial)
    with pytest.raises(ValueError):
        patch(before, stage, baseline_sha=BASE)


def test_block_reversed_source_subject_mismatch():
    before, stage = fixture()
    record = next(s for s in stage if s["canonical_match_id"] == "match-1"
                  and s["field"] == "p2_aces")
    record["player_orientation"]["source_subject"] = "wrong"
    with pytest.raises(ValueError):
        patch(before, stage, baseline_sha=BASE)


def test_block_stale_base_and_field_scope():
    before, stage = fixture()
    with pytest.raises(ValueError):
        patch(before, stage, baseline_sha="d" * 64)
    _, stage = fixture()
    stage[0]["scope"] = "point"
    with pytest.raises(ValueError):
        patch(before, stage, baseline_sha=BASE)


def test_block_source_conflicts_and_unlisted_fields():
    before, stage = fixture()
    stage[0]["validation"]["state"] = "CONFLICT"
    with pytest.raises(ValueError):
        patch(before, stage, baseline_sha=BASE)
    _, stage = fixture()
    stage[0]["field"] = "p1_return_points_won"
    with pytest.raises(ValueError):
        patch(before, stage, baseline_sha=BASE)


def test_block_stage_duplicates_and_canonical_identity_duplicates():
    before, stage = fixture()
    stage[0] = stage[1].copy()
    with pytest.raises(ValueError):
        patch(before, stage, baseline_sha=BASE)
    before, stage = fixture()
    before.at[1, "match_id"] = "match-0"
    with pytest.raises(ValueError):
        patch(before, stage, baseline_sha=BASE)
