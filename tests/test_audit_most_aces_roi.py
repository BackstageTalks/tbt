from copy import deepcopy

from audit_most_aces_roi import audit
from tbt.services.most_aces_pricing import PRICE_BASIS
from tbt.services.dashboard_kpis import published_results_metrics


def feed():
    return {"results": [{"event_id": "one", "scheduled_at": "2026-11-08T12:00:00Z",
        "market_publications": [{"publication_key": "one-A", "market": "most_aces",
            "section": "ace_winner", "selection_id": "A", "price_contract": "player_superiority",
            "issued_at": "2026-11-08T10:00:00Z", "price_status": "priced_projection",
            "price_basis": PRICE_BASIS, "odds": 1.6,
            "result": {"status": "hit", "correct": True, "staked_units": 1, "profit_units": .6}}]}]}


def test_empty_is_not_a_successful_production_verification():
    result = audit({"results": []})
    assert result["status"] == "INSUFFICIENT_SETTLED_EVIDENCE"
    assert result["roi"] is None


def test_unpriced_most_aces_never_enters_financial_kpis():
    data = feed()
    data["results"][0]["market_publications"][0]["price_status"] = "projection_only"
    metrics = published_results_metrics(data, "all")
    assert metrics["wins"] == 1
    assert metrics["stake_count"] == 0
    assert metrics["roi"] is None


def test_frozen_win_and_loss_accounting_and_duplicate():
    data = feed()
    loss = deepcopy(data["results"][0])
    loss["event_id"] = "two"
    p = loss["market_publications"][0]
    p["publication_key"] = "two-A"
    p["result"].update(status="miss", correct=False, profit_units=-1)
    data["results"] += [loss, deepcopy(loss)]
    result = audit(data)
    assert result["status"] == "VERIFIED_ACCOUNTING"
    assert result["settled_priced"] == 2
    assert abs(result["roi"] + .2) < 1e-9
    assert result["counts"]["identical_duplicates"] == 1


def test_changed_quote_fails_even_if_result_still_says_win():
    data = feed()
    data["results"][0]["market_publications"][0]["odds"] = 1.7
    assert audit(data)["errors"] == {"frozen_quote_accounting_mismatch": 1}


def test_late_issuance_and_conflicting_duplicates_fail():
    data = feed()
    p = data["results"][0]["market_publications"][0]
    p["issued_at"] = "2026-11-08T12:00:00Z"
    assert audit(data)["status"] == "FAIL"
    data = feed()
    duplicate = deepcopy(data["results"][0])
    duplicate["market_publications"][0]["odds"] = 1.7
    data["results"].append(duplicate)
    assert audit(data)["errors"]["conflicting_duplicate"] == 1


def test_unissued_pending_void_do_not_inflate_roi():
    for updates in ({"issued_at": None}, {"result": {}}, {"result": {"status": "void", "correct": None}}):
        data = feed()
        data["results"][0]["market_publications"][0].update(updates)
        assert audit(data)["status"] == "INSUFFICIENT_SETTLED_EVIDENCE"

def test_malformed_unrelated_archive_rows_never_crash_financial_readback():
    data = {"results": [None, "legacy", {"market_publications": "malformed"},
                        {"market_publications": [42, "legacy"]}]}
    result = audit(data)
    assert result["status"] == "INSUFFICIENT_SETTLED_EVIDENCE"
    assert result["roi"] is None and result["settled_priced"] == 0


def test_malformed_issued_most_aces_result_fails_closed():
    data = feed()
    data["results"][0]["market_publications"][0]["result"] = "not-a-ledger"
    result = audit(data)
    assert result["status"] == "FAIL"
    assert result["errors"] == {"invalid_result_payload": 1}
    assert result["roi"] is None
