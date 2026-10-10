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
