"""Read-only Results archive category aggregation: no identities, no mutation."""
from datetime import datetime, timezone
from copy import deepcopy

from tbt.services.results_archive import read_only_archive_category_counts


def test_readback_counts_only_settled_current_betting_day_and_selected_categories():
    today=datetime(2026,10,10,22,0,tzinfo=timezone.utc)
    def row(eid, category, scheduled, published_day=None, correct=True):
        p={"section":category,"market":"match_winner",
           "issued_at":"2026-10-10T05:00:00Z",
           "selection_id":"p1","result":{"status":"hit","correct":correct}}
        if published_day:p["betting_day"]=published_day
        return {"event_id":eid,"scheduled_at":scheduled,"market_publications":[p]}
    records=[
        row("top","top_daily","2026-10-10T12:00:00Z", "2026-10-10"),
        row("value","value","2026-10-10T13:00:00Z", "2026-10-10"),
        row("doubles","doubles","2026-10-10T14:00:00Z","2026-10-10"),
        row("prime","prime","2026-10-10T15:00:00Z", "2026-10-10"),
        row("stale","top_daily","2026-10-10T17:00:00Z","2026-10-09"),
        row("past","top_daily","2026-10-09T17:00:00Z","2026-10-09"),
        row("future","value","2026-10-11T05:30:00Z","2026-10-11"),
    ]
    for item in (records[4], records[5]):
        item["market_publications"][0]["issued_snapshot"]="malformed-string"
    before=deepcopy(records)
    a=read_only_archive_category_counts(records,now=today)
    assert a["betting_day"]=="2026-10-10",a
    assert a["persisted_settled_all_time"]==7,a
    assert a["persisted_settled_today"]==4,a
    assert a["persisted_selected_today"]==2,a
    assert a["excluded_betting_day_mismatch"]==1,a
    assert a["persisted_by_category_today"]=={"doubles":1,"prime":1,"top_daily":1,"value":1},a
    assert records==before
    assert not any("event_id" in str(k) or "selection" in str(k) for k in a)
    # After 06:00 in Bratislava, Sunday belongs to its own betting day.
    b=read_only_archive_category_counts(records,now=datetime(2026,10,11,8,tzinfo=timezone.utc))
    assert b["betting_day"]=="2026-10-11" and b["persisted_settled_today"]==1,b


if __name__=="__main__":
    test_readback_counts_only_settled_current_betting_day_and_selected_categories()
    print("Results archive aggregate-only readback contract: PASS")

def _settled_ace_winner_record():
    from tbt.services.most_aces_pricing import PRICE_BASIS
    return {
        "event_id": "issued-most-aces-one",
        "scheduled_at": "2026-11-09T12:00:00Z",
        "market_publications": [{
            "publication_key": "most-aces-one",
            "section": "ace_winner", "market": "most_aces",
            "selection_id": "p1", "price_contract": "player_superiority",
            "publication_status": "published",
            "issued_at": "2026-11-09T05:00:00Z",
            "price_status": "priced_projection",
            "price_basis": PRICE_BASIS, "odds": 1.6,
            "result": {"status": "hit", "correct": True,
                       "staked_units": 1, "profit_units": 0.6},
        }],
    }


def test_durable_archive_uses_same_frozen_issued_accounting_as_feed_audit():
    from tbt.services.most_aces_roi_accounting import audit
    rows = [_settled_ace_winner_record()]
    original = deepcopy(rows)
    at = datetime(2026, 11, 9, 14, 45, tzinfo=timezone.utc)
    result = read_only_archive_category_counts(rows, now=at)
    finance = result["ace_winner_finance"]
    assert result["persisted_by_category_all_time"]["ace_winner"] == 1
    assert finance["source"] == "durable_results_archive"
    assert finance["status"] == "VERIFIED_ACCOUNTING"
    assert finance["settled_priced"] == 1
    assert finance["wins"] == 1 and finance["losses"] == 0
    assert abs(finance["roi"] - 0.6) < 1e-9
    assert finance["roi"] == audit({"results": rows})["roi"]
    assert finance["member_render_verified"] is False
    assert finance["provider_requests"] == 0
    assert rows == original
    assert not any(secret in str(finance) for secret in ("issued-most-aces-one", "most-aces-one", "p1"))


def test_durable_archive_does_not_invent_roi_for_unpriced_or_void_records():
    at = datetime(2026, 11, 9, 14, 45, tzinfo=timezone.utc)
    entry = _settled_ace_winner_record()
    entry["market_publications"][0]["price_status"] = "projection_only"
    result = read_only_archive_category_counts([entry], now=at)
    finance = result["ace_winner_finance"]
    assert result["persisted_by_category_all_time"]["ace_winner"] == 1
    assert finance["settled_priced"] == 0
    assert finance["roi"] is None
    assert finance["status"] == "INSUFFICIENT_SETTLED_EVIDENCE"
    assert finance["counts"]["settled_unpriced"] == 1


def test_durable_archive_rejects_tampered_frozen_profit_without_roe_claim():
    at = datetime(2026, 11, 9, 14, 45, tzinfo=timezone.utc)
    entry = _settled_ace_winner_record()
    entry["market_publications"][0]["result"]["profit_units"] = 0.8
    finance = read_only_archive_category_counts([entry], now=at)["ace_winner_finance"]
    assert finance["status"] == "FAIL"
    assert finance["settled_priced"] == 0
    assert finance["roi"] is None
    assert finance["profit_units"] is None
    assert finance["errors"] == {"frozen_quote_accounting_mismatch": 1}
