"""Offline Chromium: INFO composer and real Sets/Games projection Detail action."""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        injected = (
            "  window.infoHarness={state,renderAdminRoute,wireAdmin,dailyHubRow,wireDailyHub};\n"
            + marker
        )
        route.fulfill(content_type="application/javascript", body=source.replace(marker, injected))
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, executable_path=os.getenv("BLINQ_BROWSER") or browser_path()
        )
        try:
            for width in (390, 1440):
                page = browser.new_page(viewport={"width": width, "height": 950})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.infoHarness && infoHarness.state.ui")
                page.evaluate("""() => {
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelectorAll('dialog[open]').forEach(d => d.close());
                    document.getElementById('appShell').hidden=false;
                    document.getElementById('routePanel').hidden=false;
                    document.body.classList.add('blinq-admin');
                    document.body.classList.remove('blinq-home');
                    const h=infoHarness;
                    h.state.route='admin';h.state.adminTab='insights';
                    h.state.adminInsights=[];
                    h.state.ui.notifications={
                      ...(h.state.ui.notifications||{}),enabled:true,
                      live_min_level:'elite',info_min_level:'rookie',
                      info_default_levels:['rookie','pro']
                    };
                    window.__infoSent=[];
                    window.BlinqAuth.adminCreateInsight=async payload=>{
                      window.__infoSent.push(payload);
                      return {id:'test-info',...payload};
                    };
                    window.BlinqAuth.adminInsights=async()=>({
                      items:window.__infoSent.map((item,i)=>({id:'test-info-'+i,...item}))
                    });
                    window.BlinqAuth.insights=async()=>({items:[],unread:0});
                    document.getElementById('routePanel').innerHTML=h.renderAdminRoute();
                    h.wireAdmin();
                }""")
                assert page.locator("#adminInsightForm").count() == 1
                assert "Predvolené INFO od" in page.locator(".admin-insights-section").inner_text()
                assert page.locator('input[name="insight_level"][value="rookie"]').is_checked()
                assert page.locator('input[name="insight_level"][value="rookie"]').is_enabled()
                page.locator("#adminInsightTitle").fill("Krátka správa pre členov")
                page.locator("#adminInsightBody").fill("Test zobrazenia a API kontraktu.")
                page.locator('#adminInsightForm button[type="submit"]').click()
                page.wait_for_function("window.__infoSent.length===1")
                page.wait_for_function("infoHarness.state.adminInsights?.length===1")
                created = page.evaluate("window.__infoSent[0]")
                assert created["type"] == "vip" and created["title"] == "Krátka správa pre členov"
                assert created["levels"] == ["rookie", "pro"]
                assert page.locator(".admin-insight-row").count() == 1

                # A configured INFO minimum must be enforced before submit;
                # the old 'all' preset must not create a request the API rejects.
                page.evaluate("""() => {
                    const h=infoHarness;
                    h.state.ui.notifications.info_min_level='pro';
                    h.state.ui.notifications.info_default_levels=['pro','elite','legend','goat'];
                    h.state.adminInsightEditingId='';
                    document.getElementById('routePanel').innerHTML=h.renderAdminRoute();
                    h.wireAdmin();
                }""")
                rookie=page.locator('input[name="insight_level"][value="rookie"]')
                assert rookie.is_disabled() and not rookie.is_checked()
                page.locator('[data-audience-preset="all"]').click()
                assert rookie.is_disabled() and not rookie.is_checked()
                assert page.locator('input[name="insight_level"][value="pro"]').is_checked()
                page.locator("#adminInsightTitle").fill("INFO od PRO")
                page.locator("#adminInsightBody").fill("Správa pre povolené publikum.")
                page.locator('#adminInsightForm button[type="submit"]').click()
                page.wait_for_function("window.__infoSent.length===2")
                assert "rookie" not in page.evaluate("window.__infoSent[1].levels")

                # Sets/Games have a real detail modal. Verify that SEE ALL has
                # a working Detail button, not a static MODEL chip in its place.
                page.evaluate("""() => {
                    const h=infoHarness;
                    const row={
                      event_id:'game-test',_hub_source:'games',
                      scheduled_at:new Date(Date.now()+3600000).toISOString(),
                      tour:'ATP',tournament:'Test Tournament',surface:'hard',
                      player1:{id:'p1',name:'Player One'},
                      player2:{id:'p2',name:'Player Two'},
                      projection:19.6,projection_confidence:.78,
                      projection_unit:'count',reference_projection:20.5,
                      pick:'Over 16.5 Games',selection:'Over 16.5 Games'
                    };
                    h.state.feed.upcoming=[row];h.state.dailyHubTab='see_all';
                    document.getElementById('predictionsView').hidden=false;
                    const host=document.getElementById('dailyHub');
                    host.innerHTML='<table><tbody>'+h.dailyHubRow(row,'see_all',false,0)+'</tbody></table>';
                    h.wireDailyHub();
                }""")
                assert page.locator('#dailyHub .hub-projection-badge').count() == 0
                button=page.locator('#dailyHub button[data-sg-projection]')
                assert button.count()==1 and button.inner_text()=="Detail"
                button.dispatch_event("click")
                page.wait_for_function("document.querySelector('#matchDialog')?.open")
                assert page.locator('#matchDialog .sg-detail-shell').count()==1
                assert not errors, (width, errors)
                page.close()
            print("INFO send flow, audience minima, and SG Detail button: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
