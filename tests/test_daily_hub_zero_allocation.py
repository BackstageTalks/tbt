"""Daily Offer zero allocations never change with market-data availability."""
import json
from pathlib import Path

from tbt.services.entitlements import filter_feed_for_access

ROOT=Path(__file__).resolve().parents[1]
UI=json.loads((ROOT/"web/ui-config.json").read_text(encoding="utf-8"))
MARKETS=("ace","double_faults","doubles","sets","games")
LEVELS=("rookie","pro","elite","legend","goat")


def _row(market, index):
    return {
        "event_id":f"{market}-{index}","market":market,
        "surface":"hard","scheduled_at":"2026-10-25T17:00:00Z",
        "pick":"Alpha","odds":1.80,
        "player1":{"id":"1","name":"Alpha","probability":.7},
        "player2":{"id":"2","name":"Beta","probability":.3},
    }


def _payload(n):
    return {
        "top_daily_picks":[],"daily_picks":[],"prime_picks":[],"value_picks":[],
        "ace_picks":[_row(k,i) for k in ("aces","double_faults") for i in range(n)],
        "sg_picks":[_row(k,i) for k in ("sets","games") for i in range(n)],
        "doubles_picks":[_row("doubles",i) for i in range(n)],
        "results":[],"upcoming":[],
    }


def test_every_level_entitlement_uses_exact_admin_rule_regardless_of_provider_counts():
    for level in LEVELS:
        for rows in (0,3):
            payload,manifest=filter_feed_for_access(
                _payload(rows),{"plan":level,"status":"active","id":f"u-{level}"},UI
            )
            for category in MARKETS:
                rule=UI["dashboard"]["daily_hub"]["tabs"][category]["plans"][level]
                section=manifest["sections"][category]
                assert section["visible_picks"]==rule["visible_rows"],(level,category,rows)
                assert section["blur_remaining"]==rule["blur_remaining"],(level,category,rows)
                assert section["total"]==rows,(level,category,rows)
                assert section["display_state"]=="active",(level,category,rows)
                if level in ("rookie","pro"):
                    assert section["returned"]==0,(level,category,rows)
                    assert section["locked_count"]==rows,(level,category,rows)
                else:
                    assert section["returned"]==rows,(level,category,rows)
            if level in ("rookie","pro"):
                assert not payload["doubles_picks"],level
                assert not payload["ace_picks"],level
                assert not payload["sg_picks"],level


def test_zero_row_access_displays_lock_without_pretending_provider_rows_exist():
    app=(ROOT/"web/app.js").read_text(encoding="utf-8")
    assert "function dailyHubAccessLocked(tab,ent,sourceCount)" in app
    assert "function dailyHubIncludedButUnavailable(tab,ent,sourceCount)" in app
    assert "const zeroAllocation=raw!==''&&raw!=='ALL'&&Number(raw)===0" in app
    assert "const locked=!coming&&dailyHubAccessLocked(tab,ent,dailyHubRows(tab).length)" in app
    assert "if(!out.length&&dailyHubAccessLocked(tab,ent,sourceRows.length))" in app
    assert "const currentIndex=membershipHierarchy.indexOf(accountPlan());" in app
