"""Real Chromium: Results hydration must not block first dashboard or alter loader.

Only deterministic local fixtures, no production credentials or CDB writes.
"""
import json
import os
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import ORIGIN, WEB, browser_path, static_route


def result_row(event_id, days_ago):
    from datetime import datetime, timedelta, timezone
    scheduled = datetime.now(timezone.utc) - timedelta(days=days_ago)
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
    full = [result_row("recent", 1), result_row("history", 40)]
    for width in (390, 1440):
        requests = []
        def intercept(route):
            path = urlparse(route.request.url).path
            if path == "/app.js":
                source = (WEB / "app.js").read_text(encoding="utf-8")
                assert source.count("  boot();") == 1
                source = source.replace("  boot();", """
  window.lazyResultsTest={state,setRoute,loadCompleteResults,renderDashboardKpis,
    scheduleResultsPreload:()=>scheduleResultsPreload(feedGeneration)};
  boot();""")
                route.fulfill(content_type="application/javascript", body=source)
                return
            if path == "/api/v1/results":
                requests.append(route.request)
                params = parse_qs(urlparse(route.request.url).query)
                assert params.get("limit") == ["500"], params
                assert params.get("page") == ["0"], params
                assert route.request.headers.get("x-blinq-access-token") == "fixture-token"
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "results": full, "page": 0, "limit": 500,
                    "total": len(full), "has_more": False, "snapshot": "fixture-snapshot"
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
                before = page.evaluate("""(row) => {
                  const t=window.lazyResultsTest;
                  localStorage.setItem('blinq_v4_session_epoch','fixture-epoch');
                  localStorage.setItem('blinq_v4_session',JSON.stringify({
                    provider:'firebase',access_token:'fixture-token',
                    refresh_token:'fixture-refresh',expires_at:Date.now()/1000+3600
                  }));
                  t.state.feed={
                    account:{plan:'admin',role:'admin',is_admin:true,status:'active'},
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
                  if(window.innerWidth===390)t.scheduleResultsPreload();
                  else t.setRoute('results',false);
                  return {kpis,partial:t.state.feed.results_boot_partial};
                }""", full[0])
                assert before["partial"] is True, before
                assert before["kpis"].strip(), (width, before)
                if width == 390:
                    page.wait_for_timeout(350)
                    assert len(requests) == 0, "Background history started before the delay"
                page.wait_for_function(
                    "window.lazyResultsTest.state.feed.results_boot_partial === false",
                    timeout=15000,
                )
                assert len(requests) == 1, (width, len(requests))
                if width == 390:
                    page.evaluate("window.lazyResultsTest.setRoute('results',false)")
                    assert len(requests) == 1, "Opening preloaded Results fetched history again"
                hydrated = page.evaluate("""() => ({
                  rows: window.lazyResultsTest.state.feed.results.map(x=>x.event_id),
                  rendered: document.getElementById('routePanel').textContent,
                  overflow: document.documentElement.scrollWidth-window.innerWidth
                })""")
                assert hydrated["rows"] == ["recent", "history"], (width, hydrated)
                assert hydrated["overflow"] <= 2, (width, hydrated["overflow"])
                assert not errors, (width, errors)
                context.close()
            finally:
                browser.close()
    print("BlinQ 390px background preload + 1440px immediate Results navigation: PASS")


if __name__ == "__main__":
    main()
