from datetime import datetime, timedelta, timezone
from pathlib import Path

from tbt.services.entitlements import filter_feed_for_access

ROOT = Path(__file__).resolve().parents[1]


def _result(hours_ago: int):
    now = datetime.now(timezone.utc)
    return {
        "event_id": f"r{hours_ago}",
        "scheduled_at": (now - timedelta(hours=hours_ago)).isoformat(),
        "result": {"correct": True},
    }


def _payload():
    return {
        "prime_picks": [], "top_daily_picks": [], "value_picks": [],
        "ace_picks": [], "sg_picks": [], "doubles_picks": [], "upcoming": [],
        "results": [_result(12), _result(36), _result(72)],
        "performance": {"roi": 1.23},
        "dashboard_model_success": {"accuracy": .714},
    }


def test_result_history_is_server_limited_by_plan():
    rookie, rm = filter_feed_for_access(_payload(), {"status": "active", "plan": "rookie"})
    pro, pm = filter_feed_for_access(_payload(), {"status": "active", "plan": "pro"})
    elite, em = filter_feed_for_access(_payload(), {"status": "active", "plan": "elite"})
    assert rm["results_history_hours"] == 24 and len(rookie["results"]) == 1
    assert pm["results_history_hours"] == 48 and len(pro["results"]) == 2
    assert em["results_history_hours"] is None and len(elite["results"]) == 3
    assert rookie["performance"] == {} and pro["performance"] == {}
    assert elite["performance"] == {"roi": 1.23}
    assert rookie["dashboard_model_success"] == {"accuracy": .714}
    assert pro["dashboard_model_success"] == {"accuracy": .714}


def test_short_odds_stays_separate_from_public_top():
    from tbt.services.entitlements import filter_feed_for_access

    def row(event_id, odds, probability):
        return {
            "event_id": event_id, "pick": event_id, "odds": odds, "probability": probability,
            "player1": {"name": "A", "probability": probability},
            "player2": {"name": "B", "probability": 1 - probability},
        }

    payload = {
        "prime_picks": [row("prime-only", 1.55, .90)],
        "top_daily_picks": [row("top", 1.70, .75), row("value-dup", 1.90, .73)],
        "value_picks": [row("value-dup", 1.90, .73)],
        "ace_picks": [], "sg_picks": [], "doubles_picks": [], "upcoming": [], "results": [],
    }
    data, manifest = filter_feed_for_access(payload, {"status": "active", "plan": "elite"})
    assert [item["event_id"] for item in data["daily_picks"]] == ["top"]
    assert manifest["sections"]["daily"]["total"] == 1


def test_public_prediction_board_matches_final_product_tabs():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    render = app.split("function renderDailyHub(){", 1)[1].split("function marketPreviewCard", 1)[0]
    assert "['daily','prime','value','ace','double_faults','doubles','games','sets','see_all']" in render
    assert "{daily:'TOP',prime:'SHORT ODDS',value:'VALUE',ace:'ESA',double_faults:'DVOJCHYBY',doubles:'DOUBLES',games:'GAMES',sets:'SETS',see_all:'SEE ALL'}" in app
    assert "if(tab==='daily'){" in app and "state.feed?.daily_picks" in app
    assert "if(tab==='ace')return marketRows('ace').filter(row=>offerSurfaceEligible(row)&&String(row?.market||'').toLowerCase()==='aces');" in app
    assert "if(tab==='doubles')return marketRows('doubles').filter(offerSurfaceEligible);" in app
    assert "dailyHubIsComingSoon(tab){return false;}" in app
    assert "marketRows('sg').filter(row=>offerSurfaceEligible(row)&&String(row?.market||'').toLowerCase()===tab)" in app


def test_admin_is_visibly_reduced_to_three_sections():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    route = app.split("function renderAdminRoute(){", 1)[1].split("function rerenderAdmin", 1)[0]
    assert "['accounts','Účty','Prístup · platnosť']" in route
    assert "['banners','Bannery','Hero · pozadie']" in route
    assert "['insights','Info & LIVE','Správy · radar']" in route
    assert "campaigns" not in route


def test_dashboard_filter_is_defined_and_used_by_daily_hub():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "function dashboardFilteredRows(rows){" in app
    filter_block = app.split("function dashboardFilteredRows(rows){", 1)[1].split("function dailyHubTabLabel", 1)[0]
    assert "state.dashboardSearch" in filter_block
    assert "state.dailyHubTournament" in filter_block
    assert "dailyHubDateFrom" not in filter_block
    assert "dailyHubDateTo" not in filter_block
    render = app.split("function renderDailyHub(){", 1)[1].split("function marketPreviewCard", 1)[0]
    assert "rows=dashboardFilteredRows(sourceRows)" in render
