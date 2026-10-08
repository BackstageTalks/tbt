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
                # Wait for the app's asynchronous boot/auth path to finish so it
                # cannot replace the manually mounted comparator during typing.
                page.wait_for_function("document.getElementById('bootSplash') === null")
                page.evaluate("""() => {
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelectorAll('dialog[open]').forEach(d=>d.close());
                    document.getElementById('appShell').hidden=false;
                    document.getElementById('routePanel').hidden=false;
                    const h=window.comparatorHarness;
                    h.state.route='compare';
                    h.state.comparator=null;
                    window.comparatorSearchCalls=[];
                    window.BlinqAuth.comparatorPlayers=async(query,tour) => {
                        window.comparatorSearchCalls.push({query,tour});
                        return {players:[
                            {player_id:'atp:novak',name:'Novak Djokovic',tour:'atp',matches_seen:100},
                            {player_id:'atp:novic',name:'Novak Novic',tour:'atp',matches_seen:8}
                        ]};
                    };
                    document.getElementById('routePanel').innerHTML=h.renderComparatorRoute();
                    h.wireComparator();
                }""")
                page.locator("#comparatorPlayer0").fill("Nov")
                page.wait_for_timeout(1200)
                diagnostic = page.evaluate("""() => ({
                    route: comparatorHarness.state.route,
                    seq: comparatorHarness.state.comparator?.searchSeq,
                    rows: comparatorHarness.state.comparator?.search?.[0],
                    query: document.querySelector('#comparatorPlayer0')?.value,
                    html: document.querySelector('#comparatorSearch0')?.innerHTML,
                    calls: window.comparatorSearchCalls
                })""")
                assert page.locator(".comparator-search-results button").count() == 2, (
                    width, diagnostic, errors
                )
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
                # Fragmented canonical identities: collapse the visual row,
                # preserve each player ID and never combine match counts.
                page.evaluate("""() => {
                    window.BlinqAuth.comparatorPlayers=async(query) => ({
                        players:query.toLowerCase().includes('norr')?[
                            {player_id:'norrie-main',name:'Cameron Norrie',tour:'atp',rank:27,matches_seen:598},
                            {player_id:'norman-1',name:'Simon Norman',tour:'atp',matches_seen:37},
                            {player_id:'norrie-other',name:'Cameron Norrie',tour:'atp',rank:27,matches_seen:8},
                        ]:[
                            {player_id:'svrcina-old',name:'Svrčina D.',aliases:['Dalibor Svrcina'],tour:'atp',rank:99,matches_seen:83},
                            {player_id:'svrcina-main',name:'Dalibor Svrčina',tour:'atp',rank:91,matches_seen:330},
                        ]
                    });
                }""")
                page.locator("#comparatorPlayer0").fill("norr")
                page.get_by_role("button", name="Cameron Norrie").wait_for()
                assert page.locator("#comparatorSearch0 .comparator-search-primary").count() == 2
                assert page.locator("#comparatorSearch0 .comparator-search-alternative").count() == 0
                assert page.locator("#comparatorSearch0 .comparator-search-primary").first.get_attribute("data-player-id") == "norrie-main"
                assert "598 zápasov v DB" in page.locator("#comparatorSearch0").inner_text()
                assert page.locator("#comparatorSearch0 [data-player-id='norrie-other']").count() == 0
                page.locator("#comparatorSearch0 [data-comparator-expand]").click()
                assert page.locator("#comparatorSearch0 .comparator-search-alternative").count() == 1
                assert page.locator("#comparatorSearch0 [data-player-id='norrie-other']").count() == 1
                assert "8 zápasov v DB" in page.locator("#comparatorSearch0").inner_text()
                page.locator("#comparatorSearch0 .comparator-search-primary").first.click()
                assert page.evaluate("comparatorHarness.state.comparator.players[0].player_id") == "norrie-main"

                page.locator("#comparatorPlayer1").fill("svrc")
                page.get_by_role("button", name="Dalibor Svrčina").wait_for()
                assert page.locator("#comparatorSearch1 .comparator-search-primary").count() == 1
                assert page.locator("#comparatorSearch1 .comparator-search-primary").first.get_attribute("data-player-id") == "svrcina-main"
                assert page.locator("#comparatorSearch1 .comparator-search-alternative").count() == 0
                page.locator("#comparatorSearch1 [data-comparator-expand]").click()
                assert page.locator("#comparatorSearch1 .comparator-search-alternative").count() == 1
                assert "Svrčina D." in page.locator("#comparatorSearch1 .comparator-search-alternates").inner_text()
                page.locator("#comparatorSearch1 .comparator-search-primary").first.click()
                assert page.evaluate("comparatorHarness.state.comparator.players[1].player_id") == "svrcina-main"
                assert not errors, (width, errors)
                page.close()
            print("Comparator player search click, errors, stale result and mobile: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
