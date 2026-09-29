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
            "  window.infoHarness={state,renderAdminRoute,wireAdmin,dailyHubRow,wireDailyHub,renderInsightDrawer,renderInsightBell,setInsightDrawer,loadInsights};\n"
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

                # INFO minimum is a composer default only. Exact per-message
                # audience may include FREE/ROOKIE even when the default starts at PRO.
                page.evaluate("""() => {
                    const h=infoHarness;
                    h.state.ui.notifications.info_min_level='pro';
                    h.state.ui.notifications.info_default_levels=['pro','elite','legend','goat'];
                    h.state.adminInsightEditingId='';
                    document.getElementById('routePanel').innerHTML=h.renderAdminRoute();
                    h.wireAdmin();
                }""")
                rookie=page.locator('input[name="insight_level"][value="rookie"]')
                assert rookie.is_enabled() and not rookie.is_checked()
                page.locator('[data-audience-preset="all"]').click()
                assert rookie.is_enabled() and rookie.is_checked()
                assert page.locator('input[name="insight_level"][value="pro"]').is_checked()
                page.locator("#adminInsightTitle").fill("INFO pre všetkých")
                page.locator("#adminInsightBody").fill("Správa pre presne zvolené publikum.")
                page.locator('#adminInsightForm button[type="submit"]').click()
                page.wait_for_function("window.__infoSent.length===2")
                assert "rookie" in page.evaluate("window.__infoSent[1].levels")

                # End-to-end offline contract: one newly published VIP/INFO
                # message for ROOKIE must appear BOTH in the unread bell and
                # inside the INFO drawer after its own authenticated refresh.
                # This caught the ternary that filtered out every INFO item.
                page.evaluate("""async () => {
                    const h=infoHarness;
                    h.state.feed.account={
                      ...(h.state.feed.account||{}),
                      plan:'rookie',role:'user',is_admin:false,status:'active'
                    };
                    h.state.previewPlan=null;
                    h.state.insightChannel='info';
                    h.state.insightFilter='all';
                    h.state.insights=[];
                    window.BlinqAuth.insights=async()=>({
                      items:[{
                        id:'new-rookie-message',
                        ...window.__infoSent[0],
                        created_at:new Date().toISOString(),
                        read:false,pinned:false
                      }],
                      unread:1
                    });
                    await h.loadInsights(true);
                    h.setInsightDrawer(true,'info');
                }""")
                page.wait_for_function("infoHarness.state.insights?.length===1&&!infoHarness.state.insightsLoading")
                # Header shows only the BlinQ Info title, not a duplicate
                # green BLINQ INFO eyebrow. LIVE retains its own marker.
                eyebrow=page.locator("#insightDrawerEyebrow")
                assert eyebrow.is_hidden()
                assert page.locator("#insightDrawerTitle").inner_text()=="BlinQ Info"
                page.evaluate("""() => {
                    const h=infoHarness;
                    h.state.insightChannel='live';
                    h.renderInsightDrawer();
                }""")
                assert eyebrow.is_visible()
                assert eyebrow.inner_text()=="BLINQ LIVE"
                page.evaluate("""() => {
                    const h=infoHarness;
                    h.state.insightChannel='info';
                    h.renderInsightDrawer();
                }""")
                assert eyebrow.is_hidden()
                assert page.locator("#insightUnread").inner_text()=="1"
                assert page.locator("#insightDrawerStatus").inner_text().find("1 správ")>=0
                assert page.locator("#insightDrawerStatus").inner_text().find("1 neprečítaných")>=0
                rows=page.locator("#insightDrawerList .insight-feed-item")
                assert rows.count()==1
                assert "Krátka správa pre členov" in rows.first.inner_text()
                assert "Test zobrazenia a API kontraktu." in rows.first.inner_text()
                assert page.locator("#insightDrawerList .insight-feed-empty").count()==0
                # LIVE subtab rules must not hide INFO, even when LIVE data
                # or an unrelated message type is present in local state.
                page.evaluate("""() => {
                    const h=infoHarness;
                    h.state.liveRadarTab='results';
                    h.state.insights.push({
                      id:'live-for-elite',type:'alert',title:'LIVE only',
                      body:'should not appear in INFO',
                      levels:['elite'],read:false
                    });
                    h.renderInsightDrawer();
                }""")
                assert rows.count()==1
                assert "LIVE only" not in page.locator("#insightDrawerList").inner_text()
                page.locator('[data-insight-filter="unread"]').first.dispatch_event("click")
                assert rows.count()==1
                page.locator('[data-insight-filter="pinned"]').first.dispatch_event("click")
                assert rows.count()==0
                page.locator('[data-insight-filter="all"]').first.dispatch_event("click")
                assert rows.count()==1
                assert not errors, (width, errors)
                page.evaluate("""() => {
                    infoHarness.setInsightDrawer(false);
                    infoHarness.state.feed.account={
                      ...infoHarness.state.feed.account,role:'admin',is_admin:true,
                      plan:'admin'
                    };
                }""")

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
            print("INFO ROOKIE bell/drawer, send flow, audience minima and SG Detail: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
