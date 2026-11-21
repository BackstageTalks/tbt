"""Synthetic tests for sealed full-slate shadow, never live mutation."""
import importlib.util
from pathlib import Path

import pytest

from tbt.services.market_only_shadow_research import (
    prepare_all_singles_shadow_rows, load_shadow_params,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit_market_only_shadow_readonly.py"
spec = importlib.util.spec_from_file_location("audit_market_only_shadow", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
PARAMS = load_shadow_params(ROOT / "research/market_only_shadow/params_2026-11-20.json")


def fixture(n):
    return {
        "event_id": str(n), "model_version": "v1",
        "tour": "ATP" if n % 2 else "WTA", "prediction_family": "singles",
        "player1_id": f"a{n}", "player2_id": f"b{n}",
        "model_player1_probability": .81,
        "model_captured_at": "2026-11-21T08:00:00Z",
        "scheduled_at": "2026-11-21T12:00:00Z",
        "market_captured_at": "2026-11-21T09:00:00Z",
        "issued_at": "2026-11-21T10:00:00Z",
        "fair_player1": .79, "fair_player2": .21,
        "bookmaker": "book1",
        "category_at_capture": "TOP" if n % 5 == 0 else "ACCA",
        "source_provenance": "synthetic-test-only",
    }


def settled(n):
    return {
        "event_id": str(n), "status": "settled",
        "winner_id": f"a{n}" if n % 3 else f"b{n}",
        "settled_at": "2026-11-22T10:00:00Z",
    }


def test_399_valid_does_not_disclose_scores():
    snapshots = prepare_all_singles_shadow_rows(
        (fixture(n) for n in range(399)), PARAMS)
    result = audit.evaluate(snapshots, [settled(n) for n in range(399)])
    assert result["status"] == "WAIT_FOR_400_NEW_MATCHES"
    assert result["counts"]["valid_two_way_prestart_settled"] == 399
    assert "overall" not in result and "groups" not in result


def issuance(n):
    return {"event_id": str(n), "selection_id": f"a{n}",
            "day_utc": "2026-11-21", "shadow_issued_at": "2026-11-21T11:00:00Z",
            "selection_tier": "T0", "selection_basis": "rank_market",
            "receipt_id": f"receipt-{n}"}


def test_400_valid_opens_offline_analysis_without_refit():
    snapshots = prepare_all_singles_shadow_rows(
        (fixture(n) for n in range(400)), PARAMS)
    result = audit.evaluate(snapshots, [settled(n) for n in range(400)],
                            issued_shadow=[issuance(n) for n in range(400)])
    assert result["a0_daily_issuance"]["issued_receipts_verified"] is True
    assert result["a0_daily_issuance"]["issued_per_day"] == {"2026-11-21":400}
    assert result["overall"]["n"] == 400
    assert result["groups"]["ATP"]["n"] == 200
    assert result["groups"]["WTA"]["n"] == 200
    assert result["same_N_market_baseline"]["identical_market_calibrated_order"]
    assert result["decision"].startswith("REVIEW_ONLY")
    assert result["no_production_write"] is True
    assert result["no_refit"] is True


def test_missing_fair_and_pending_cannot_release_results():
    fixtures = [fixture(i) for i in range(400)]
    fixtures[0]["fair_player1"] = None
    snapshots = prepare_all_singles_shadow_rows(fixtures, PARAMS)
    result = audit.evaluate(snapshots, [settled(n) for n in range(399)])
    assert result["counts"]["valid_two_way_prestart_settled"] == 398
    assert result["status"] == "WAIT_FOR_400_NEW_MATCHES"


def test_forged_settlement_identity_is_refused():
    snapshots = prepare_all_singles_shadow_rows([fixture(0)], PARAMS)
    wrong = {"event_id": "0", "status": "settled",
             "winner_id": "someone_else",
             "settled_at": "2026-11-22T10:00:00Z"}
    with pytest.raises(ValueError, match="identity conflict"):
        audit.evaluate(snapshots, [wrong])


def test_before_freeze_predictions_are_not_counted():
    one = fixture(0)
    one["model_captured_at"] = "2026-11-20T22:00:00Z"
    snapshots = prepare_all_singles_shadow_rows([one], PARAMS)
    result = audit.evaluate(snapshots, [settled(0)])
    assert result["status"] == "WAIT_FOR_400_NEW_MATCHES"
    assert result["counts"]["valid_two_way_prestart_settled"] == 0


def test_duplicate_canonical_outcome_is_refused():
    snapshots = prepare_all_singles_shadow_rows([fixture(0)], PARAMS)
    with pytest.raises(ValueError, match="Duplicate"):
        audit.evaluate(snapshots, [settled(0), settled(0)])


def test_400_without_independent_issuance_blocks_all_metrics():
    snapshots = prepare_all_singles_shadow_rows(
        (fixture(n) for n in range(400)), PARAMS)
    result = audit.evaluate(snapshots, [settled(n) for n in range(400)])
    assert result["status"] == "BLOCKED_A0_ISSUANCE_NOT_VERIFIED"
    assert result["a0_daily_issuance"]["issued_receipts_verified"] is False
    assert "overall" not in result and "groups" not in result


def test_400_with_only_four_issued_shadows_blocks_result():
    fixtures = [fixture(i) for i in range(400)]
    for i in range(5, 400):
        fixtures[i]["scheduled_at"] = "2026-11-22T08:00:00Z"
    snapshots = prepare_all_singles_shadow_rows(fixtures, PARAMS)
    result = audit.evaluate(snapshots, [settled(n) for n in range(400)],
                            issued_shadow=[issuance(n) for n in range(400)])
    assert result["status"] == "BLOCKED_A0_DAILY_MINIMUM"
    assert result["a0_daily_issuance"]["computed_per_day"]["2026-11-21"] == 5
    # A0 on the next day would select 395; no outcome metrics can be exposed.
    assert "overall" not in result


def test_400_short_day_below_five_even_with_large_other_day():
    fixtures = [fixture(i) for i in range(400)]
    fixtures[399]["scheduled_at"] = "2026-11-22T08:00:00Z"
    snapshots = prepare_all_singles_shadow_rows(fixtures, PARAMS)
    result = audit.evaluate(snapshots, [settled(n) for n in range(400)])
    assert result["status"] == "BLOCKED_A0_DAILY_MINIMUM"
    assert result["a0_daily_issuance"]["shortfall_days"] == ["2026-11-22"]
    assert result["a0_daily_issuance"]["computed_per_day"]["2026-11-22"] == 1
    assert "overall" not in result


def test_incomplete_or_invalid_issued_receipts_fail_closed():
    snapshots = prepare_all_singles_shadow_rows(
        (fixture(n) for n in range(400)), PARAMS)
    settled_rows = [settled(n) for n in range(400)]
    incomplete = audit.evaluate(snapshots, settled_rows,
                                issued_shadow=[issuance(n) for n in range(399)])
    assert incomplete["status"] == "BLOCKED_A0_INCOMPLETE_ISSUANCE"
    assert "overall" not in incomplete
    wrong = [issuance(n) for n in range(400)]
    wrong[0]["shadow_issued_at"] = "2026-11-21T12:01:00Z"
    with pytest.raises(ValueError, match="pre-start"):
        audit.evaluate(snapshots, settled_rows, issued_shadow=wrong)
