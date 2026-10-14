"""Real Chromium regression for admin results page jump and cross-page selection."""
import os
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        route.fulfill(
            content_type="application/javascript",
            body=source.replace(marker, (
                "  window.adminTestUi={state,renderAdminRoute,wireAdmin};\n" + marker
            )),
        )
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        exe = os.getenv("BLINQ_BROWSER") or browser_path()
        browser = pw.chromium.launch(headless=True, executable_path=exe) if exe else pw.chromium.launch(headless=True)
        try:
            for width in (390, 1200, 1440):
                context = browser.new_context(viewport={"width": width, "height": 850})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.adminTestUi && adminTestUi.state.ui")
                page.evaluate("""() => {
                    const s=adminTestUi.state;
                    s.feed.account={is_admin:true,role:'admin',plan:'admin'};
                    document.body.classList.remove('blinq-home','blinq-route');
                    document.body.classList.add('blinq-admin');
                    s.route='admin';s.adminTab='testresults';
                    s.adminTestPage=0;s.adminTestSize=50;s.adminTestSelected=[];
                    s.adminTestData={excluded_total:0,items:Array.from({length:126},(_,i)=>({
                        id:String(i+1).padStart(64,'0'),event_id:String(i+1),
                        scheduled_at:'2026-10-11T11:00:00Z',
                        player1:'Player '+(i+1),player2:'Opponent',
                        section:i%10===0?'sets':'top_daily',
                        market:i%10===0?'sets':'match_winner',
                        selection:'Player '+(i+1),status:['hit','miss','void','pending'][i%4],odds:1.25+(i%5)*0.5,excluded:false,
                    }))};
                    const host=document.getElementById('routePanel');
                    document.getElementById('bootSplash')?.remove();
                    document.getElementById('cookieConsent')?.remove();
                    document.getElementById('authDialog')?.remove();
                    document.getElementById('appShell').hidden=false;
                    host.hidden=false;
                    host.innerHTML=adminTestUi.renderAdminRoute();
                    adminTestUi.wireAdmin();
                }""")
                assert page.locator(".admin-test-table tbody tr").count()==50, width
                page.locator('[data-admin-test-action="select-page"]').click()
                assert page.evaluate("adminTestUi.state.adminTestSelected.length")==50, width
                page.locator('[data-admin-test-action="next"]').click()
                assert page.locator('#adminTestGoPage').input_value()=='2', width
                assert page.evaluate("adminTestUi.state.adminTestSelected.length")==50, width
                page.locator('[data-admin-test-action="select-page"]').click()
                assert page.evaluate("adminTestUi.state.adminTestSelected.length")==100, width
                page.locator('#adminTestGoPage').fill('3')
                page.locator('[data-admin-test-action="go"]').click()
                assert page.locator('#adminTestGoPage').input_value()=='3', width
                assert page.locator(".admin-test-table tbody tr").count()==26, width
                assert page.evaluate("adminTestUi.state.adminTestSelected.length")==100, width
                page.locator('#adminTestGoPage').fill('999')
                page.locator('#adminTestGoPage').press('Enter')
                assert page.locator('#adminTestGoPage').input_value()=='3', width
                page.locator('[data-admin-test-size]').select_option('100')
                assert page.locator('#adminTestGoPage').input_value()=='1', width
                assert page.locator(".admin-test-table tbody tr").count()==100, width
                assert page.evaluate("adminTestUi.state.adminTestSelected.length")==100, width
                # Page 2 / 2: the "Prejsť" text must fit its own button, not the next-arrow target.
                page.locator('[data-admin-test-action="next"]').click()
                assert page.locator('#adminTestGoPage').input_value()=='2', width
                pager=page.evaluate("""() => {
                    const nav=document.querySelector('.admin-test-pager .results-pagination-nav');
                    const parts=[...nav.children].map(el=>el.getBoundingClientRect());
                    const go=nav.querySelector('[data-admin-test-action="go"]');
                    const box=go.getBoundingClientRect();
                    const collision=(a,b)=>a.left<b.right-1 && b.left<a.right-1 &&
                        a.top<b.bottom-1 && b.top<a.bottom-1;
                    return {
                        goWidth:box.width,
                        textFits:go.scrollWidth<=go.clientWidth+1,
                        overlaps:parts.some((a,i)=>parts.slice(i+1).some(b=>collision(a,b))),
                        buttonLabel:go.textContent.trim()
                    };
                }""")
                assert pager['goWidth']>=80, (width,pager)
                assert pager['textFits'] and not pager['overlaps'], (width,pager)
                page.locator('[data-admin-test-action="prev"]').click()
                assert page.locator('#adminTestGoPage').input_value()=='1', width
                page.locator('[data-admin-test-filter="category"]').select_option('sets')
                assert page.locator(".admin-test-table tbody tr").count()==13, width
                assert page.evaluate("adminTestUi.state.adminTestSelected.length")==100, width
                page.locator('[data-admin-test-action="clear"]').click()
                assert page.evaluate("adminTestUi.state.adminTestSelected.length")==0, width

                # New filters are independent of the existing inclusion/exclusion status.
                page.locator('[data-admin-test-action="reset-filters"]').click()
                assert page.locator(".admin-test-table tbody tr").count()==100, width
                page.locator('[data-admin-test-filter="outcome"]').select_option('loss')
                assert page.locator(".admin-test-table tbody tr").count()==32, width
                assert page.locator(".admin-test-outcome.is-loss").count()==32, width
                page.locator('[data-admin-test-filter="oddsMin"]').fill('2.25')
                page.locator('[data-admin-test-filter="oddsMin"]').press('Tab')
                page.locator('[data-admin-test-filter="oddsMax"]').fill('2.25')
                page.locator('[data-admin-test-filter="oddsMax"]').press('Tab')
                assert page.locator(".admin-test-table tbody tr").count()==6, width
                assert page.locator(".admin-test-odds").first.inner_text().strip()=='2,25', width
                page.locator('[data-admin-test-filter="oddsMin"]').fill('3.50')
                page.locator('[data-admin-test-filter="oddsMin"]').press('Tab')
                assert page.locator('.admin-test-filter-error').count()==1, width
                assert page.locator('.admin-test-empty').count()==1, width
                page.locator('[data-admin-test-action="reset-filters"]').click()
                assert page.locator(".admin-test-table tbody tr").count()==100, width
                assert page.locator('.admin-test-odds').count()==100, width
                visual=page.evaluate("""() => ({
                    head: parseFloat(getComputedStyle(document.querySelector('.admin-test-table th')).fontSize),
                    cell: parseFloat(getComputedStyle(document.querySelector('.admin-test-table td')).fontSize),
                    controls: [...document.querySelectorAll('.admin-test-filters input,.admin-test-filters select')].every(el =>
                        el.getBoundingClientRect().width >= 60 && el.getBoundingClientRect().right <= innerWidth+1),
                    scroll: document.querySelector('.admin-test-table-wrap').scrollWidth >
                            document.querySelector('.admin-test-table-wrap').clientWidth
                })""")
                assert visual['head']>=11 and visual['cell']>=12, (width,visual)
                assert visual['controls'], (width,visual)
                if width==390: assert visual['scroll'], (width,visual)
                assert not errors, (width,errors)
                context.close()
            print("Admin results filters, odds, outcome, responsive typography, jump and multi-select: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
