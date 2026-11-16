"""Real Chromium: Results hydration must not block first dashboard or alter loader.

Only deterministic local fixtures, no production credentials or CDB writes.
"""
import json
import os
import time
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import ORIGIN, WEB, browser_path, static_route


def result_row(event_id, days_ago):
    from datetime import datetime, timedelta, timezone, time as dt_time
    zone = ZoneInfo('Europe/Bratislava')
    betting_day = (datetime.now(zone) - timedelta(hours=6)).date()
    scheduled = datetime.combine(betting_day - timedelta(days=days_ago), dt_time(hour=12), tzinfo=zone).astimezone(timezone.utc)
    issued = scheduled - timedelta(hours=5)
    return {
        "event_id": event_id,
        "scheduled_at": scheduled.isoformat(),
        "tour": "ATP",
        "surface": "hard",
        "player1": {"id": event_id + "-p1", "name": "One"},
        "player2": {"id": event_id + "-p2", "name": "Two"},
        "market_publications": [{
            "section": "top_daily", "market": "match_winner",
            "selection_id": event_id + "-p1", "selection": "One",
            "issued_at": issued.isoformat(), "odds": 1.8,
            "result": {"correct": True, "staked_units": 1, "profit_units": 0.8},
        }],
    }


def main():
    full = [result_row("today", 0), result_row("recent", 1), result_row("history", 40)]
    for width in (390, 1440):
        requests = []
        def intercept(route):
            path = urlparse(route.request.url).path
            if path == "/app.js":
                source = (WEB / "app.js").read_text(encoding="utf-8")
                assert source.count("  boot();") == 1
                source = source.replace("  boot();", """
  window.lazyResultsTest={state,setRoute,loadRecentResults,loadCompleteResults,renderDashboardKpis,
    scheduleResultsPreload:()=>scheduleResultsPreload(feedGeneration),
    reuseHydratedResultsOnRefresh};
  boot();""")
                route.fulfill(content_type="application/javascript", body=source)
                return
            if path == "/api/v1/results":
                params = parse_qs(urlparse(route.request.url).query)
                scope = params.get("window_days", [""])[0]
                assert scope in ("1", "30", ""), scope
                requests.append((route.request, time.monotonic(), scope))
                assert params.get("limit") == ["500"], params
                assert params.get("page") == ["0"], params
                assert route.request.headers.get("x-blinq-access-token") == "fixture-token"
                rows = full[:1] if scope == "1" else full[:2] if scope == "30" else full
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "results": rows, "page": 0, "limit": 500,
                    "total": len(rows), "has_more": False, "snapshot": "fixture-snapshot",
                    **({"scope_days": int(scope)} if scope else {}),
                }))
                return
            static_route(route)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                executable_path=os.getenv("BLINQ_BROWSER") or browser_path()
            )
            try:
                context = browser.new_context(viewport={"width": width, "height": 900})
                context.route("**/*", intercept)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.lazyResultsTest && window.lazyResultsTest.state.ui")
                assert page.locator("#bootSplash img[src*='blinq-loader.gif']").count() in (0, 1)
                scheduled_at = time.monotonic()
                before = page.evaluate("""(row) => {
                  const t=window.lazyResultsTest;
                  localStorage.setItem('blinq_v4_session_epoch','fixture-epoch');
                  localStorage.setItem('blinq_v4_session',JSON.stringify({
                    provider:'firebase',access_token:'fixture-token',
                    refresh_token:'fixture-refresh',expires_at:Date.now()/1000+3600
                  }));
                  t.state.feed={
                    account:{id:'fixture-user',email:'user@example.test',plan:'admin',role:'admin',is_admin:true,status:'active'},
                    entitlements:{results:true,result_categories:['top_daily']},
                    upcoming:[],results:[row],results_boot_partial:true,
                    dashboard_kpi_cards:[],performance:{},model:{}
                  };
                  document.getElementById('appShell').hidden=false;
                  const dialog=document.getElementById('authDialog');
                  if(dialog.open)dialog.close();
                  t.setRoute('predictions',false);
                  const kpis=document.getElementById('dashboardKpis').textContent;
                  // Mobile: let the background timer hydrate without opening
                  // Results. Desktop: navigate immediately to cover the race.
                  if(window.innerWidth===390){
                    // Exercise the real page-load gate even though goto()
                    // already waited for networkidle in the test harness.
                    Object.defineProperty(document,'readyState',{configurable:true,get:()=> 'loading'});
                    t.scheduleResultsPreload();
                    delete document.readyState;
                  }else t.setRoute('results',false);
                  return {kpis,partial:t.state.feed.results_boot_partial};
                }""", full[0])
                assert before["partial"] is True, before
                assert before["kpis"].strip(), (width, before)
                if width == 390:
                    page.wait_for_timeout(350)
                    assert len(requests) == 0, "Background history started before the page load event"
                    page.evaluate("window.dispatchEvent(new Event('load'))")
                page.wait_for_function(
                    "window.lazyResultsTest.state.feed.results_today_ready === true",
                    timeout=15000,
                )
                assert len(requests) == 1 and requests[0][2] == "1", (width, requests)
                assert page.evaluate("window.lazyResultsTest.state.feed.results_boot_partial") is True
                if width == 390:
                    elapsed = requests[0][1] - scheduled_at
                    assert elapsed >= 4.8, ("Today Results preloaded before page-load delay", elapsed)
                if width == 390:
                    page.evaluate("window.lazyResultsTest.setRoute('results',false)")
                    assert len(requests) == 1, "Opening preloaded Results fetched history again"
                hydrated = page.evaluate("""() => ({
                  rows: window.lazyResultsTest.state.feed.results.map(x=>x.event_id),
                  rendered: document.getElementById('routePanel').textContent,
                  overflow: document.documentElement.scrollWidth-window.innerWidth
                })""")
                assert hydrated["rows"] == ["today"], (width, hydrated)
                # A fresh authorized bootstrap with the same ledger reuses
                # hydrated rows; revocation or changed revision fails closed.
                reuse = page.evaluate("""() => {
                  const t=window.lazyResultsTest, old=t.state.feed;
                  const next={
                    account:{...old.account},entitlements:{results:true},
                    results:[],results_boot_partial:true,results_snapshot:'fixture-snapshot'
                  };
                  const retained=t.reuseHydratedResultsOnRefresh(next);
                  const reused=next.results===old.results&&next.results_boot_partial===true
                    &&next.results_today_ready===true&&next.results_recent_ready===false;
                  const denied={
                    account:{...old.account},entitlements:{results:false},
                    results:[],results_boot_partial:true,results_snapshot:'fixture-snapshot'
                  };
                  const refused=t.reuseHydratedResultsOnRefresh(denied);
                  return {retained,reused,refused,deniedEmpty:denied.results.length===0};
                }""")
                assert reuse == {"retained": True, "reused": True,
                                 "refused": False, "deniedEmpty": True}, (width, reuse)
                # Today is the only initially transferred report; a broader
                # filter explicitly requests 30 days before full history.
                page.evaluate("""() => {
                  const t=window.lazyResultsTest;
                  t.state.resultsFilters.window='30';
                  t.setRoute('results',false);
                }""")
                page.wait_for_function(
                    "window.lazyResultsTest.state.feed.results_recent_ready === true",
                    timeout=15000,
                )
                assert len(requests) == 2 and requests[1][2] == "30", (width, requests)
                assert page.evaluate(
                    "window.lazyResultsTest.state.feed.results.map(r=>r.event_id)"
                ) == ["today", "recent"], width

                # All time remains complete and must never be inferred from
                # the day-only or 30-day scoped payload.
                page.evaluate("""() => {
                  const t=window.lazyResultsTest;
                  t.state.resultsFilters.window='all';
                  t.setRoute('results',false);
                }""")
                page.wait_for_function(
                    "window.lazyResultsTest.state.feed.results_boot_partial === false",
                    timeout=15000,
                )
                assert len(requests) == 3 and requests[2][2] == "", (width, requests)
                assert page.evaluate(
                    "window.lazyResultsTest.state.feed.results.map(r=>r.event_id)"
                ) == ["today", "recent", "history"], width
                assert hydrated["overflow"] <= 2, (width, hydrated["overflow"])
                assert not errors, (width, errors)
                context.close()
            finally:
                browser.close()
    print("BlinQ today-first 5s preload, on-demand 30/full, and session-safe reuse: PASS")


if __name__ == "__main__":
    main()
