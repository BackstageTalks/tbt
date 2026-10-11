"""Synthetic read-only WTA 2024 source to canonical overlap contract."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_tennisexplorer_wta2024_cdb_overlap import (
    canonical_rows, compare, result_side, source_players, name_format_diagnostics,
)


def src(**changes):
    row = {
        "category": "wta-single", "tour": "WTA", "date": "2024-04-01",
        "match_id": "txe-1", "tournament": "Sample Open",
        "side1_players_json": '["Świątek Iga"]',
        "side2_players_json": '["Player Two"]',
        "side1_sets_won": "2", "side2_sets_won": "0",
    }
    row.update(changes)
    return row


def cdb(**changes):
    row = {
        "match_id": "canonical-1", "tour": "wta", "scheduled_at": pd.Timestamp("2024-04-01T12:00:00Z"),
        "player1_id": "p1", "player1_name": "Świątek Iga", "player2_id": "p2",
        "player2_name": "Player Two", "winner_id": "p1", "tournament": "Sample Open",
        "status": "completed",
    }
    row.update(changes)
    return row


def test_exact_results_agree_and_no_write():
    x = compare([src()], [cdb()])
    assert x["counts"]["unique_match_winner_agreements"] == 1
    assert x["canonical_writes"] == 0
    assert x["independently_approved_missing_cdb_cells"] == 0
    assert x["source_proposals_exported"] is False


def test_orientation_reversed_preserved():
    x = compare([src(side1_players_json='["Player Two"]',
                     side2_players_json='["Świątek Iga"]',
                     side1_sets_won="0", side2_sets_won="2")], [cdb()])
    assert x["counts"]["unique_match_winner_agreements"] == 1


def test_name_pair_not_enough_without_tournament():
    x = compare([src(tournament="Entirely Different Open")], [cdb()])
    assert x["counts"]["not_exact_tournament"] == 1
    assert x["counts"].get("unique_match_winner_agreements", 0) == 0


def test_name_pair_not_enough_without_same_day():
    x = compare([src(date="2024-04-05")], [cdb()])
    assert x["counts"]["unmatched_exact_players_and_day"] == 1


def test_source_score_must_prove_winner_and_not_retirement():
    x = compare([src(side1_sets_won="1", side2_sets_won="0")], [cdb()])
    assert x["counts"]["unverifiable_source_winner"] == 1
    assert result_side(src(side1_sets_won="RET", side2_sets_won="0")) is None


def test_canonical_winner_conflict_quarantined():
    x = compare([src()], [cdb(winner_id="p2")])
    assert x["counts"]["canonical_winner_conflicts"] == 1
    assert x["counts"].get("unique_match_winner_agreements", 0) == 0


def test_canonical_null_winner_is_research_not_auto_written():
    x = compare([src()], [cdb(winner_id=None)])
    assert x["counts"]["canonical_winner_null_research_only"] == 1
    assert x["independently_approved_missing_cdb_cells"] == 0


def test_ambiguous_pair_same_day_same_tournament_rejected():
    x = compare([src()], [cdb(), cdb(match_id="canonical-2")])
    assert x["counts"]["ambiguous_canonical_events"] == 1


def test_duplicate_source_ids_and_competing_claims_quarantined():
    x = compare([src(), src(match_id="txe-2")], [cdb()])
    assert x["counts"]["duplicate_canonical_claim_source_rows"] == 2
    assert x["counts"]["unique_match_winner_agreements"] == 0
    y = compare([src(), src()], [cdb()])
    assert y["counts"]["missing_or_duplicate_source_id"] == 1
    assert y["counts"]["unique_match_winner_agreements"] == 1


def test_canonical_duplicate_match_id_fails_closed():
    with pytest.raises(ValueError, match="Duplicate canonical"):
        canonical_rows(pd.DataFrame([cdb(), cdb()]))


def test_doubles_and_missing_player_ids_excluded():
    x = compare([src(category="wta-double")], [cdb()])
    assert x["counts"]["wrong_source_tour_or_category"] == 1
    y = compare([src(side1_players_json='["A","B"]')], [cdb()])
    assert y["counts"]["incomplete_source_player_identity"] == 1


def test_unordered_full_tokens_reveal_reversed_source_name_order_without_links():
    rows=[src(side1_players_json='["Swiatek Iga"]')]
    diag=name_format_diagnostics(rows,[cdb()])
    assert diag["counts"]["unordered_full_token_pair_day_candidate_rows"] == 1
    assert diag["counts"]["unordered_full_token_pair_day_tournament_candidate_rows"] == 1
    assert diag["canonical_link_approved"] is False


def test_abbreviated_surname_initial_is_research_only():
    rows=[src(side1_players_json='["Swiatek I."]',
              side2_players_json='["Two P."]')]
    diag=name_format_diagnostics(rows,[cdb()])
    assert diag["counts"]["source_rows_containing_a_single_letter_token"] == 1
    assert diag["counts"]["surname_initial_pair_day_candidate_rows_research_only"] == 1
    assert diag["counts"]["surname_initial_pair_day_tournament_candidate_rows_research_only"] == 1
    assert diag["player_id_crosswalk_exported"] is False
    assert diag["new_cdb_cells_approved"] == 0


def test_surname_initial_same_pair_wrong_tournament_not_verified():
    rows=[src(tournament="Other tournament",
              side1_players_json='["Swiatek I."]',
              side2_players_json='["Two P."]')]
    diag=name_format_diagnostics(rows,[cdb()])
    assert diag["counts"]["surname_initial_pair_day_candidate_rows_research_only"] == 1
    assert diag["counts"].get("surname_initial_pair_day_tournament_candidate_rows_research_only",0)==0


def test_identical_surname_initial_collisions_rejected():
    rows=[src(side1_players_json='["Smith J."]',
              side2_players_json='["Smith J."]')]
    diag=name_format_diagnostics(rows,[cdb()])
    assert diag["counts"].get("surname_initial_pair_day_candidate_rows_research_only",0)==0
