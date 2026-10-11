"""Focused fail-closed WTA 2024 score import regression tests (no provider calls)."""
from __future__ import annotations
import copy
import json

import pandas as pd
import pytest

from stage_txe_wta2024_scores import (
    classify, full_name, result_slugs, score_values, FIELD_NAMES,
)
from import_txe_wta2024_scores_exact import patch, read_stage


def mock():
    row = {
        "category": "wta-single", "match_id": "987654", "date": "2024-06-10",
        "tournament": "Stockholm WTA", "side1_player_slugs_json": '["alice-one"]',
        "side2_player_slugs_json": '["bob-two"]',
        "side1_sets_won": "2", "side2_sets_won": "0",
    }
    for n, (a, b) in enumerate(((6, 4), (6, 3)), 1):
        row[f"set{n}_side1"], row[f"set{n}_side2"] = str(a), str(b)
    detail = {"source": "TennisExplorer", "match_id": "987654",
        "players": [
            {"name": "Alice One", "profile_url": "https://www.tennisexplorer.com/player/alice-one/"},
            {"name": "Bob Two", "profile_url": "https://www.tennisexplorer.com/player/bob-two/"},
        ]}
    frame = pd.DataFrame([{
        "match_id": "cdb-987654", "tour": "wta", "scheduled_at": pd.Timestamp("2024-06-10T13:00Z"),
        "player1_id": "player:one", "player1_name": "Alice One",
        "player2_id": "player:two", "player2_name": "Bob Two",
        "winner_id": "player:one", "tournament": "WTA Stockholm", "status": "completed",
        "stats_json": '{"total_sets":2}',
    }])
    return [row], [detail], frame


def test_source_score_and_fullname_anchor():
    rows, details, frame = mock()
    stage, bad, stats = classify(rows, details, frame, "1"*64)
    assert bad == [] and stats["exact_fullname_anchors"] == 1
    assert stats["unique_crosswalk_slugs"] == 2
    assert stats["staged_matches"] == 1 and stats["staged_fields"] == 10
    assert stage[0]["additions"]["total_games"] == 19
    assert stage[0]["additions"]["p1_first_set_won"] == 1
    assert stage[0]["additions"]["p2_first_set_won"] == 0
    assert stage[0]["additions"]["p1_games_won"] == 12
    assert stage[0]["additions"]["p2_games_won"] == 7
    assert stage[0]["additions"]["deciding_set"] == 0
    assert len(FIELD_NAMES) == 11
    updated, patches = patch(frame, stage)
    assert len(patches) == 1
    assert json.loads(updated.loc[0, "stats_json"])["total_sets"] == 2
    with pytest.raises(ValueError, match="overwrite"):
        patch(updated, stage)


def test_swapped_orientation_with_correlated_winner():
    rows, details, frame = mock()
    frame.at[0, "player1_id"], frame.at[0, "player2_id"] = "player:two", "player:one"
    frame.at[0, "player1_name"], frame.at[0, "player2_name"] = "Bob Two", "Alice One"
    stage, bad, _ = classify(rows, details, frame, "1"*64)
    assert not bad and stage[0]["additions"]["p1_sets_won"] == 0
    assert stage[0]["additions"]["p2_sets_won"] == 2
    assert stage[0]["additions"]["p1_games_won"] == 7


def test_winner_conflict_or_tournament_mismatch_rejects():
    rows, details, frame = mock()
    frame.at[0, "winner_id"] = "player:two"
    stage, _, counts = classify(rows, details, frame, "1"*64)
    assert not stage and not counts.get("staged_fields", 0)
    frame.at[0, "winner_id"] = "player:one"
    frame.at[0, "tournament"] = "Valladolid"
    stage, _, counts = classify(rows, details, frame, "1"*64)
    assert not stage and not counts.get("staged_fields", 0)


def test_source_slug_profile_conflict_rejects():
    rows, details, frame = mock()
    details[0]["players"][0]["profile_url"] = "https://www.tennisexplorer.com/player/wrong-slug/"
    stage, bad, counts = classify(rows, details, frame, "1"*64)
    assert not stage and not bad and counts["detail_identity_incomplete"] == 1


def test_score_must_be_whole_match_and_not_retirement():
    rows, _, _ = mock()
    assert score_values(rows[0]) is not None
    for mutation in [
        {"side1_sets_won": "RET"},
        {"set2_side1": ""},
        {"set2_side2": "7"},
        {"set2_side1": "5", "set2_side2": "5"},
        {"set1_side1": "7", "set1_side2": "2"},
        {"side1_sets_won": "1"},
        {"set3_side1": "6", "set3_side2": "3"},
    ]:
        altered = dict(rows[0], **mutation)
        assert score_values(altered) is None, altered


def test_stats_conflict_quarantines_whole_match():
    rows, details, frame = mock()
    frame.at[0, "stats_json"] = '{"total_sets":3}'
    stage, bad, counts = classify(rows, details, frame, "1"*64)
    assert not stage and bad[0]["reason"] == "existing_score_conflict"
    assert counts["matches_quarantined_existing_score_conflict"] == 1
    assert counts["missing_fields_blocked_by_conflict"] == 10


def test_competing_source_claim_for_same_match_quarantined():
    rows, details, frame = mock()
    dupe = dict(rows[0], match_id="987655")
    other = dict(details[0], match_id="987655")
    stage, bad, counts = classify(rows+[dupe], details+[other], frame, "1"*64)
    assert not stage and counts["competing_source_matches"] == 1
    assert len(bad) == 2


def test_duplicate_source_record_aborts():
    rows, details, frame = mock()
    with pytest.raises(ValueError, match="Duplicate/missing"):
        classify(rows + rows, details, frame, "1"*64)


def test_score_stage_source_hash_and_non_null_precondition(tmp_path):
    rows, details, frame = mock()
    staged, _, counts = classify(rows, details, frame, "a"*64)
    p = tmp_path / "stage.jsonl"
    p.write_text(json.dumps(staged[0])+"\n")
    from stage_txe_wta2024_scores import sha256, SOURCE_SHA
    report = {"schema":1, "status":"read_only_score_delta", "cdb_sha256":"a"*64,
              "source_sha256":SOURCE_SHA,"year":2024,"stage_sha256":sha256(p),
              "production_mutated":False,"model_trained":False,"counts":counts}
    r = tmp_path / "report.json"
    r.write_text(json.dumps(report))
    checked, _ = read_stage(p,r,"a"*64)
    assert len(checked)==1
    with pytest.raises(ValueError,match="Stale"):
        read_stage(p,r,"b"*64)
    checked[0]["additions"]["p2_games_won"] = 999
    p.write_text(json.dumps(checked[0])+"\n")
    report["stage_sha256"] = sha256(p)
    r.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Invalid historical"):
        read_stage(p,r,"a"*64)
