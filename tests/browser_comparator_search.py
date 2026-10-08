"""Offline Chromium regression for live comparator name suggestions."""
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
            "  window.comparatorHarness={state,renderComparatorRoute,wireComparator};\n"
            + marker,
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
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function(
                    "window.comparatorHarness && comparatorHarness.state.ui"
                )
                page.evaluate("""() => {
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.getElementById('appShell').hidden=false;
                    document.getElementById('routePanel').hidden=false;
                    const h=window.comparatorHarness;
                    h.state.route='compare';
                    h.state.comparator=null;
                    window.BlinqAuth.comparatorPlayers=async() => ({
                        players:[
                            {player_id:'atp:novak',name:'Novak Djokovic',tour:'atp',matches_seen:100},
                            {player_id:'atp:novic',name:'Novak Novic',tour:'atp',matches_seen:8}
                        ]
                    });
                    document.getElementById('routePanel').innerHTML=h.renderComparatorRoute();
                    h.wireComparator();
                }""")
                page.locator("#comparatorPlayer0").fill("Nov")
                page.locator(".comparator-search-results button").first.wait_for()
                assert page.locator(".comparator-search-results button").count() == 2
                page.locator(".comparator-search-results button").first.click()
                assert page.locator("#comparatorPlayer0").input_value() == "Novak Djokovic"
                assert page.locator(".comparator-player-confirmed").count() == 1

                # API errors need inline feedback without destroying input focus.
                page.evaluate("""() => {
                    window.BlinqAuth.comparatorPlayers=async()=>{
                        const error=new Error('rate_limited');error.status=429;throw error;
                    };
                }""")
                page.locator("#comparatorPlayer1").fill("Rafe")
                page.locator("#comparatorSearch1 [role=alert]").wait_for()
                assert "Priveľa vyhľadávaní" in page.locator("#comparatorSearch1").inner_text()

                # Out-of-order results from the previous query must never overwrite
                # the newest suggestion list.
                page.evaluate("""() => {
                    window.pendingComparatorQueries={};
                    window.BlinqAuth.comparatorPlayers=(q)=>new Promise(resolve=>{
                        window.pendingComparatorQueries[q]=resolve;
                    });
                }""")
                page.locator("#comparatorPlayer1").fill("Rafa")
                page.wait_for_function("Boolean(window.pendingComparatorQueries.Rafa)")
                page.locator("#comparatorPlayer1").fill("Rafael")
                page.wait_for_function("Boolean(window.pendingComparatorQueries.Rafael)")
                page.evaluate("""() => {
                    window.pendingComparatorQueries.Rafael({players:[
                        {player_id:'atp:nadal',name:'Rafael Nadal',tour:'atp',matches_seen:500},
                        {player_id:'atp:rafael2',name:'Rafael Silva',tour:'atp',matches_seen:7}
                    ]});
                }""")
                page.get_by_role("button", name="Rafael Nadal").wait_for()
                page.evaluate("""() => {
                    window.pendingComparatorQueries.Rafa({players:[
                        {player_id:'atp:stale',name:'Stale Rafa',tour:'atp',matches_seen:5}
                    ]});
                }""")
                page.wait_for_timeout(100)
                assert page.get_by_role("button", name="Rafael Nadal").count() == 1
                assert page.get_by_role("button", name="Stale Rafa").count() == 0
                page.get_by_role("button", name="Rafael Nadal").click()
                assert page.locator("#comparatorPlayer1").input_value() == "Rafael Nadal"
                assert page.locator(".comparator-player-confirmed").count() == 2
                assert not errors, (width, errors)
                page.close()
            print("Comparator player search click, errors, stale result and mobile: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
