"""Fail-closed tape and field classification regression fixtures."""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.audit_wimbledon_2023_cdb_stage import classify, tape_completeness, clean_binary, validated_best_of


def tape():
    # Small fabricated tape to test gate mechanics, not tennis realism.
    return pd.DataFrame([
        dict(player1="Jane", player2="Lucy", point_no=1, p1_points_won=1,
             p2_points_won=0, point_victor=1, server=1, serve_no=1,
             p1_ace=1, p2_ace=0, p1_double_fault=0, p2_double_fault=0,
             p1_break_pt=0, p2_break_pt=0, game_victor=1, set_victor=1),
        dict(player1="Jane", player2="Lucy", point_no=2, p1_points_won=2,
             p2_points_won=0, point_victor=1, server=1, serve_no=2,
             p1_ace=0, p2_ace=0, p1_double_fault=0, p2_double_fault=0,
             p1_break_pt=0, p2_break_pt=0, game_victor=1, set_victor=1),
    ])


def test_only_verified_complete_tape_and_missing_cell_can_be_ready():
    assert classify(4, None, []) == (
        "READY_MISSING", ["verified_complete_tape_and_absent_canonical_cell"]
    )
    state, reasons = classify(4, None, ["nonexhaustive_point_sequence"])
    assert state == "UNRESOLVED" and "nonexhaustive_point_sequence" in reasons
    assert classify(None, None, [])[0] == "UNRESOLVED"


def test_no_overwrite_and_conflict_are_distinct():
    assert classify(2, 2, [])[0] == "ALREADY_PRESENT"
    assert classify(2, 3, [])[0] == "CONFLICT"
    assert classify(2, True, [])[0] == "UNRESOLVED"
    assert classify(2, -1, [])[0] == "UNRESOLVED"
    assert classify(0, None, [])[0] == "READY_MISSING"


def test_gap_in_source_point_numbers_blocks_complete_match():
    g = tape()
    g.at[1, "point_no"] = 3
    assert "nonexhaustive_point_sequence" in tape_completeness(g, 3, 1)


def test_missing_point_flag_is_unknown_not_zero():
    g = tape()
    g.at[1, "p1_ace"] = float("nan")
    issues = tape_completeness(g, 3, 1)
    assert "missing_or_invalid_point_flags:p1_ace" in issues
    assert clean_binary(float("nan")) is None


def test_unknown_best_of_blocks_aggregate():
    issues = tape_completeness(tape(), None, 1)
    assert "unknown_match_format" in issues


def test_invalid_set_result_blocks_aggregate():
    g = tape()
    g.at[1, "set_victor"] = 0
    assert "missing_or_excess_terminal_set" in tape_completeness(g, 3, 1)


def test_reject_nonbinary_event_flags():
    assert clean_binary(2) is None
    assert clean_binary(-1) is None
    assert clean_binary("junk") is None
    assert clean_binary(0) == 0
    assert clean_binary(1) == 1


def test_script_has_no_cdb_publisher():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] /
              "scripts/audit_wimbledon_2023_cdb_stage.py").read_text()
    assert "upload_bundle(" not in script
    assert "write_year_partition(" not in script
    assert "create_release(" not in script
    assert '"production_mutated": False' in script
    assert '"write_authorized": False' in script


def test_side_two_terminal_winner_is_understood_not_rejected_as_nonbinary():
    group = pd.DataFrame([
        dict(player1="Jane", player2="Lucy", point_no=i,
             p1_points_won=0, p2_points_won=i, point_victor=2,
             server=2, serve_no=1, p1_ace=0, p2_ace=0,
             p1_double_fault=0, p2_double_fault=0,
             p1_break_pt=0, p2_break_pt=0, game_victor=2,
             set_victor=2 if i in (6, 12) else 0)
        for i in range(1, 13)
    ])
    assert tape_completeness(group, 3, 2) == []


def test_wimbledon_wta_2023_format_can_use_contemporaneous_official_wta_proof():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    m=SimpleNamespace(tour="wta",tournament="Wimbledon, London",
                      scheduled_at=datetime(2023,7,13,tzinfo=timezone.utc),
                      best_of=None)
    assert validated_best_of(m)==3
    m.best_of=5
    assert validated_best_of(m) is None
    m.best_of=None
    m.tour="atp"
    assert validated_best_of(m) is None
    m.tour="wta"
    m.scheduled_at=datetime(2024,7,13,tzinfo=timezone.utc)
    assert validated_best_of(m) is None
