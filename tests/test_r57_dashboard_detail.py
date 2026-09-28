"""R57 dashboard count and cleaned match detail contracts."""
from pathlib import Path

from tbt.services.entitlements import entitlement_manifest, filter_feed_for_access


ROOT = Path(__file__).resolve().parents[1]


def _pick(event, winner="player-a", *, market=None, selection=None, surface="hard"):
    row = {
        "event_id": event,
        "winner_id": winner,
        "surface": surface,
        "betting": {"odds": 1.60},
    }
    if market:
        row["market"] = market
    if selection:
        row["selection_id"] = selection
    return row


def _published_market_fixture():
    top = _pick("match-1")
    return {
        "top_daily_picks": [top, _pick("match-2")],
        "prime_picks": [dict(top)],  # the SAME published pick; count only once
        "value_picks": [_pick("match-3")],
        "ace_picks": [
            _pick("match-1", market="aces", selection="over-9.5"),
            _pick("match-1", market="double_faults", selection="under-4.5"),
            _pick("match-extra", market="aces", surface="unknown"),
        ],
        "doubles_picks": [_pick("match-4", market="doubles")],
        "sg_picks": [
            _pick("match-1", market="games", selection="over-21.5"),
            _pick("match-1", market="sets", selection="over-2.5"),
        ],
        "upcoming": [],
        "results": [],
    }


def test_dashboard_count_all_real_markets_without_double_counting_see_all():
    payload = _published_market_fixture()
    for plan in ("rookie", "pro", "elite", "admin"):
        manifest = entitlement_manifest({"status": "active", "plan": plan}, payload)
        assert manifest["daily_pick_count"] == 8
        assert manifest["sections"]["daily"]["total"] == 2
        assert manifest["sections"]["prime"]["total"] == 1
        # Legacy TOP alias and SEE ALL must not inflate the public KPI.
        assert manifest["sections"]["top_daily"]["total"] == 2


def test_dashboard_count_does_not_expose_locked_pick_rows():
    payload = _published_market_fixture()
    redacted, manifest = filter_feed_for_access(
        payload, {"status": "active", "plan": "rookie", "id": "r57-rookie"}
    )
    assert manifest["daily_pick_count"] == 8
    assert len(redacted["prime_picks"]) <= 1
    assert not redacted["doubles_picks"]
    assert not redacted["sg_picks"]


def test_same_event_different_match_winner_counts_as_two_bets():
    payload = _published_market_fixture()
    payload["prime_picks"].append(_pick("match-1", winner="player-b"))
    manifest = entitlement_manifest({"status": "active", "plan": "admin"}, payload)
    assert manifest["daily_pick_count"] == 9


def test_dashboard_uses_server_unique_count_and_preserves_title():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    dashboard = app.split("function renderDashboardKpis()", 1)[1].split(
        "function highlightRow()", 1
    )[0]
    assert "state.feed?.entitlements?.daily_pick_count" in dashboard
    assert "DNEŠNÉ PREDIKCIE" in dashboard
    assert "String(totalToday),'',''" in dashboard
    assert "['daily','prime','value','ace','double_faults','doubles','games','sets']" in dashboard
    assert "totalToday=Math.max(Number(dailyEnt?.total)" not in dashboard


def test_match_detail_has_clean_context_and_nonoverlapping_header_actions():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    css = (ROOT / "web/blinq-app.css").read_text(encoding="utf-8")
    context = app.split("function renderMotivationPanel(", 1)[1].split(
        "function dashboardDailyRows()", 1
    )[0]
    motivation = app.split("function motivationContext(", 1)[1].split(
        "function renderMotivationPanel(", 1
    )[0]
    assert "<small>CONTEXT</small>" not in context
    assert "Point-in-time · pred zápasom" not in context
    assert "note:'Elo'" not in motivation
    assert "Povrchový fit" in motivation
    final = css.split("R57: match detail header action space", 1)[1]
    assert ".match-dialog>.dialog-close" in final
    assert "position:absolute!important" in final
    assert "padding-right:58px!important" in final
    assert "grid-template-columns:minmax(0,1fr) auto!important" in final
    assert "@media(max-width:760px)" in final
    assert ".blinq-detail-popout .match-popout-button{display:none!important}" in final
