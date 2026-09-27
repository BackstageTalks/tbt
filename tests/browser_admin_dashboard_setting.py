"""Offline Chromium: admin KPI selections and unchanged three-card public layout."""
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
            "  window.dashboardHarness={state,renderAdminRoute,wireAdmin,renderDashboardKpis};\n"
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
                page.wait_for_function("window.dashboardHarness && dashboardHarness.state.ui")
                page.evaluate("""() => {
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelectorAll('dialog[open]').forEach(d=>d.close());
                    document.getElementById('appShell').hidden=false;
                    document.getElementById('routePanel').hidden=false;
                    document.body.classList.add('blinq-admin');
                    document.body.classList.remove('blinq-home');
                    const t=dashboardHarness;
                    t.state.route='admin';
                    t.state.adminTab='dashboard';
                    const host=document.getElementById('routePanel');
                    host.innerHTML=t.renderAdminRoute();
                    t.wireAdmin();
                }""")
                assert page.locator(".admin-dashboard-slot").count() == 3
                assert page.get_by_text("Dashboard setting").count() >= 1
                page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="metric"]').select_option("roi")
                page.locator('[data-admin-kpi-index="0"][data-admin-kpi-field="period"]').select_option("30")
                page.locator('[data-admin-kpi-index="1"][data-admin-kpi-field="period"]').select_option("180")
                page.locator('[data-admin-kpi-index="2"][data-admin-kpi-field="metric"]').select_option("yield_units")
                page.locator('[data-admin-kpi-index="2"][data-admin-kpi-field="period"]').select_option("365")
                settings = page.evaluate("dashboardHarness.state.ui.dashboard.kpi_cards")
                assert settings == [
                    {"metric": "roi", "period": "30"},
                    {"metric": "model_success", "period": "180"},
                    {"metric": "yield_units", "period": "365"},
                ], (width, settings)
                assert page.evaluate("""() => [...document.querySelectorAll('.admin-dashboard-slot')]
                    .every(el=>el.scrollWidth<=el.clientWidth+2)"""), width
                page.evaluate("""() => {
                    const h=dashboardHarness;
                    h.state.feed={
                      entitlements:{daily_pick_count:58},daily_picks:[{odds:1.86,surface:'hard'}],
                      dashboard_kpi_cards:[
                        {metric:'roi',period:'30',value:.125},
                        {metric:'model_success',period:'180',value:.703},
                        {metric:'yield_units',period:'365',value:5.75}
                      ],
                    };
                    h.renderDashboardKpis();
                }""")
                cards = page.locator("#dashboardKpis .dashboard-kpi")
                assert cards.count() == 3
                assert [c.locator("strong").inner_text() for c in cards.all()] == [
                    "12.5%", "70.3%", "+5.75u"
                ]
                assert page.locator("#dashboardKpis .dashboard-kpi p").count() == 0
                assert page.locator("#dashboardKpis .dashboard-kpi[title]").count() == 0
                # Unpublished configuration is not the new global default.
                page.evaluate("""() => {
                    const h=dashboardHarness;
                    h.state.ui.dashboard.kpi_cards=[
                      {metric:'today_picks',period:'today'},
                      {metric:'model_success',period:'auto'},
                      {metric:'avg_odds',period:'today'}
                    ];
                    h.state.feed.dashboard_kpi_cards=[
                      {metric:'today_picks',period:'today',value:null},
                      {metric:'model_success',period:'auto',value:.703},
                      {metric:'avg_odds',period:'today',value:null}
                    ];
                    h.renderDashboardKpis();
                }""")
                assert [c.locator("strong").inner_text() for c in cards.all()] == [
                    "58", "70.3%", "1.86"
                ]
                assert not errors, (width, errors)
                page.close()
            print("Admin Dashboard setting and unchanged public three-card runtime: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
