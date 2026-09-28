"""Offline admin LIVE management at phone/desktop sizes; no paid API or real deletes."""
import os
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        source = source.replace(
            marker,
            "  window.adminLiveTest={state,renderAdminRoute,wireAdmin,"
            "loadAdminLiveResults,loadAdminInsights};\n" + marker,
        )
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, executable_path=os.getenv("BLINQ_BROWSER") or browser_path()
        )
        try:
            for width in (390, 1440):
                page = browser.new_page(viewport={"width": width, "height": 930})
                failures = []
                page.on("pageerror", lambda error: failures.append(str(error)))
                page.on("dialog", lambda dialog: dialog.accept())
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.adminLiveTest && adminLiveTest.state.ui")
                page.evaluate("""() => {
                    const h=adminLiveTest,s=h.state;
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelectorAll('dialog[open]').forEach(d=>d.close());
                    document.querySelector('#appShell').hidden=false;
                    document.querySelector('#routePanel').hidden=false;
                    document.body.classList.add('blinq-admin');
                    document.body.classList.remove('blinq-home');
                    s.route='admin';s.adminTab='insights';
                    s.adminInsightsError='';s.adminLiveResultsError='';
                    s.adminLiveResultsLoading=false;s.adminInsightsLoading=false;
                    window.__deletedInsights=[];window.__deletedResults=[];
                    const posts=[
                      {id:'msg-info-1',type:'vip',title:'Information',body:'General info',
                       levels:['rookie'],created_at:'2026-09-27T12:00:00Z',active:true},
                      {id:'live-watch-123',type:'live_watch',title:'Potential Comeback',body:'Watch',
                       levels:['elite'],created_at:'2026-09-27T13:00:00Z',active:true},
                      {id:'live-set2-123',type:'set2',title:'2. set LIVE',body:'Second-set signal',
                       levels:['elite'],created_at:'2026-09-27T13:30:00Z',active:true}
                    ];
                    const results=[
                      {id:'live-result-comeback-123',kind:'comeback',title:'Comeback',
                       event_id:'123',outcome:'win',settled_at:'2026-09-27T14:00:00Z'},
                      {id:'live-result-set2-123',kind:'set2',title:'Second-set',
                       event_id:'123',outcome:'loss',settled_at:'2026-09-27T14:02:00Z'}
                    ];
                    s.adminInsights=posts;s.adminLiveResults=results;
                    window.BlinqAuth.adminDeleteInsight=async id=>{
                      window.__deletedInsights.push(id);return {deleted:true};
                    };
                    window.BlinqAuth.adminDeleteLiveResult=async id=>{
                      window.__deletedResults.push(id);return {deleted:true};
                    };
                    window.BlinqAuth.adminInsights=async()=>({items:s.adminInsights});
                    window.BlinqAuth.adminLiveResults=async()=>({items:s.adminLiveResults});
                    document.querySelector('#routePanel').innerHTML=h.renderAdminRoute();
                    h.wireAdmin();
                }""")
                assert page.locator(".admin-live-management").count() == 1
                assert page.locator(".admin-live-management [data-admin-action='insight-delete']").count() == 2
                assert page.locator(".admin-live-management [data-admin-action='live-result-delete']").count() == 2
                assert page.locator(".admin-insight-list .admin-insight-row").count() == 1
                assert "2. set" in page.locator(".admin-live-management").inner_text()
                assert "Comeback" in page.locator(".admin-live-management").inner_text()
                # Delete one settled 2nd-set result only; posted alert stays.
                page.locator(
                    "[data-admin-action='live-result-delete']"
                    "[data-live-result-id='live-result-set2-123']"
                ).click()
                page.wait_for_function("window.__deletedResults.length===1")
                assert page.evaluate("window.__deletedResults[0]") == "live-result-set2-123"
                assert page.locator("[data-admin-live-result='live-result-set2-123']").count() == 0
                assert page.locator("[data-insight-id='live-set2-123']").count() > 0
                assert page.locator("[data-admin-live-result='live-result-comeback-123']").count() == 1
                # Delete only the LIVE 2nd-set alert next.
                page.locator(
                    "[data-admin-action='insight-delete']"
                    "[data-insight-id='live-set2-123']"
                ).click()
                page.wait_for_function("window.__deletedInsights.length===1")
                assert page.evaluate("window.__deletedInsights[0]") == "live-set2-123"
                assert page.locator("[data-insight-id='live-set2-123']").count() == 0
                assert page.locator("[data-insight-id='live-watch-123']").count() > 0
                assert page.locator(".admin-insight-list .admin-insight-row").count() == 1
                assert page.locator("[data-admin-live-result='live-result-comeback-123']").count() == 1
                if width == 390:
                    assert page.locator(".admin-live-results-columns").evaluate(
                        "(el) => getComputedStyle(el).gridTemplateColumns.split(' ').length === 1"
                    )
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth+2"
                    )
                assert not failures, (width, failures)
                page.close()
            print("Admin LIVE and 2nd-set independent result/post delete browser test: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
