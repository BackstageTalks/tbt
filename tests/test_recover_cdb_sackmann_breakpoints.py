from copy import deepcopy
from datetime import datetime, timezone

import pytest

from recover_cdb_sackmann_breakpoints import (
    FIELDS, POLICY, SOURCE_REVISION, candidate, source_match_id, stage,
    write_local, _source_rates,
)
from import_historical_match_foundation import _stats
from tbt.schemas import MatchRecord

from pathlib import Path
import csv


def original():
    return {
        "tourney_id": "2020-101", "tourney_date": "20200106",
        "match_num": "42", "round": "F", "winner_id": "1001",
        "loser_id": "1002", "winner_name": "Alpha One",
        "loser_name": "Beta Two", "score": "6-4 6-4", "best_of": "3",
        "w_svpt": "64", "w_SvGms": "10", "w_1stIn": "40",
        "w_1stWon": "30", "w_2ndWon": "14", "w_bpSaved": "3",
        "w_bpFaced": "5", "w_ace": "5", "w_df": "2",
        "l_svpt": "65", "l_SvGms": "10", "l_1stIn": "41",
        "l_1stWon": "25", "l_2ndWon": "12", "l_bpSaved": "2",
        "l_bpFaced": "7", "l_ace": "4", "l_df": "3",
    }


def canonical(row=None):
    row = row or original()
    path = Path("atp_matches_2020.csv")
    mid, kind = source_match_id("atp", path, row, 2)
    return MatchRecord(
        match_id=mid, tour="atp",
        scheduled_at=datetime(2020, 1, 6, 12, tzinfo=timezone.utc),
        player1_id="hist-js:atp:1001", player2_id="hist-js:atp:1002",
        player1_name="Alpha One", player2_name="Beta Two",
        winner_id="hist-js:atp:1001", status="completed",
        stats=_stats(row),
        provider_payload={
            "_tbt_provider_event_id": mid,
            "_tbt_source_category_name": "historical_" + kind,
            "_tbt_statistics": {"source": "jeff_sackmann_match_snapshot:" + path.name},
        },
    )


def test_proven_native_ids_and_conversion_values():
    row = original()
    m = canonical(row)
    record, reason = candidate(m, row, "atp", Path("atp_matches_2020.csv"), 2, "a" * 64)
    assert reason == "staged" and record["policy"] == POLICY
    assert set(record["additions"]) == FIELDS
    assert record["additions"]["p1_break_point_return_win"] == pytest.approx(5 / 7)
    assert record["additions"]["p2_break_point_return_win"] == pytest.approx(2 / 5)
    assert record["source"]["commit"] == SOURCE_REVISION
    assert not (set(record["additions"]) & {"p1_break_points_won", "p2_break_points_won"})


def test_source_ids_are_required_even_with_same_names_and_match_id():
    row, m = original(), canonical()
    m.player2_id = "sofascore:1002"
    assert candidate(m, row, "atp", Path("atp_matches_2020.csv"), 2, "x")[1] == "lineage_rejected"
    m = canonical()
    m.provider_payload["_tbt_statistics"]["source"] = "other_source"
    assert candidate(m, row, "atp", Path("atp_matches_2020.csv"), 2, "x")[1] == "lineage_rejected"


def test_zero_bp_denominator_is_missing_not_zero():
    row = original()
    row["l_bpFaced"] = "0"
    row["l_bpSaved"] = "0"
    assert _source_rates(row) == {"p2_break_point_return_win": 2 / 5}
    m = canonical(row)
    staged, reason = candidate(m, row, "atp", Path("atp_matches_2020.csv"), 2, "x")
    assert reason == "staged" and staged["additions"] == {"p2_break_point_return_win": 2 / 5}


def test_reject_wrong_score_stats_and_known_conflicts():
    row = original()
    row["score"] = "6-4 4-6 RET"
    assert _source_rates(row) == {}
    row = original()
    row["l_bpSaved"] = "8"
    assert _source_rates(row) == {}
    row = original()
    m = canonical(row)
    m.stats["p1_break_point_return_win"] = 0.1
    assert candidate(m, row, "atp", Path("atp_matches_2020.csv"), 2, "x")[1] == "existing_bp_conflict"
    m = canonical(row)
    m.stats["p2_break_point_serve_win"] = 0.9
    assert candidate(m, row, "atp", Path("atp_matches_2020.csv"), 2, "x")[1] == "counterpart_bp_conflict"
    m = canonical(row)
    m.stats["p2_aces"] = 77
    assert candidate(m, row, "atp", Path("atp_matches_2020.csv"), 2, "x")[1] == "source_snapshot_conflict"


def _build_source(root, rows):
    path = root / "atp" / "atp_matches_2020.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(original()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_stage_duplicate_quarantine_and_no_unrelated_match(tmp_path):
    row = original()
    _build_source(tmp_path, [row, row])
    stage_rows, counts, hashes = stage([canonical()], tmp_path)
    assert stage_rows == []
    assert counts["duplicate_source_target_quarantined"] == 1
    assert counts["staged_matches"] == 0
    assert len(hashes) == 1


def test_local_replay_is_null_only_and_idempotent(tmp_path):
    row = original()
    _build_source(tmp_path, [row])
    m = canonical()
    staged, counts, _ = stage([m], tmp_path)
    assert counts["new_stat_values"] == 2
    years = write_local([m], staged, tmp_path)
    assert years == [2020]
    assert m.stats["p1_break_point_return_win"] == pytest.approx(5 / 7)
    assert stage([m], tmp_path)[0] == []
    assert m.stats.get("p1_break_points_won") is None


def test_source_sha_and_cdb_baseline_change_block_write(tmp_path):
    row = original()
    path = _build_source(tmp_path, [row])
    m = canonical()
    staged, _, _ = stage([m], tmp_path)
    m2 = deepcopy(m)
    m2.stats["p1_aces"] = 8.0
    with pytest.raises(ValueError, match="changed since stage"):
        write_local([m2], staged, tmp_path)
    row["l_bpFaced"] = "8"
    _build_source(tmp_path, [row])
    with pytest.raises(ValueError, match="changed since stage"):
        write_local([m], staged, tmp_path)


def test_legacy_break_points_won_counts_never_changed(tmp_path):
    row = original()
    _build_source(tmp_path, [row])
    m = canonical()
    m.stats["p1_break_points_won"] = 5.0
    staged, _, _ = stage([m], tmp_path)
    write_local([m], staged, tmp_path)
    assert m.stats["p1_break_points_won"] == 5.0


def test_cdb_orientation_and_score_change_rejected():
    row = original()
    m = canonical(row)
    m.winner_id = m.player2_id
    assert candidate(m, row, "atp", Path("atp_matches_2020.csv"), 2, "x")[1] == "lineage_rejected"
    m = canonical(row)
    row = dict(row, winner_name="Someone Else")
    assert candidate(m, row, "atp", Path("atp_matches_2020.csv"), 2, "x")[1] == "lineage_rejected"


def test_exact_provider_collision_gate_stages_only_unambiguous_and_preserves_full_readback(monkeypatch):
    import recover_cdb_sackmann_breakpoints as bp

    calls = []
    monkeypatch.setattr(bp, "_load", lambda directory, **kwargs: calls.append(kwargs) or [])
    for mode in ("stage", "write", "verify"):
        assert bp.load_canonical_for_mode(
            Path("/offline/canonical"), mode=mode,
            isolate_provider_collisions=True, expected_provider_quarantine=6,
        ) == []
    assert len(calls) == 3
    assert all(call["isolate_provider_collisions"] is True for call in calls)
    assert all(call["expected_provider_quarantine"] == 6 for call in calls)
    assert calls[0]["include_quarantined_for_full_readback"] is False
    assert calls[1]["include_quarantined_for_full_readback"] is True
    assert calls[2]["include_quarantined_for_full_readback"] is True


def test_breakpoint_quarantine_opt_in_is_fail_closed(monkeypatch):
    import recover_cdb_sackmann_breakpoints as bp

    monkeypatch.setattr(bp, "_load", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not read")))
    for opts in (
        dict(mode="stage", isolate_provider_collisions=True, expected_provider_quarantine=0),
        dict(mode="write", isolate_provider_collisions=False, expected_provider_quarantine=6),
        dict(mode="verify", isolate_provider_collisions=True, expected_provider_quarantine=21),
        dict(mode="unapproved", isolate_provider_collisions=True, expected_provider_quarantine=6),
    ):
        with pytest.raises(ValueError):
            bp.load_canonical_for_mode(Path("/offline/canonical"), **opts)
