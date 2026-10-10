"""Results category multiselect: real clicks, category union, no duplicate KPI bets."""
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
            body=source.replace(
                marker,
                "  window.resultsMultiTest={state,renderRoute,settledPublishedEntries};\n" + marker,
            ),
        )
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        executable = os.getenv("BLINQ_BROWSER") or browser_path()
        browser = pw.chromium.launch(headless=True, executable_path=executable) if executable else pw.chromium.launch(headless=True)
        try:
            for width in (390, 1440):
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.resultsMultiTest && resultsMultiTest.state.ui")
                page.evaluate("""() => {
                    const t=resultsMultiTest,s=t.state,when='2026-10-10T12:00:00Z';
                    const publication=(section,market,selection,correct=true)=>({
                        section,market,selection,selection_id:selection,
                        issued_at:'2026-10-10T08:00:00Z',
                        price_status:['aces','double_faults','sets','games'].includes(market)?'projection_only':'priced',
                        odds:market==='match_winner'?1.6:null,
                        result:{status:correct?'hit':'miss',correct,
                            staked_units:market==='match_winner'?1:null,
                            profit_units:market==='match_winner'?(correct ? 0.6 : -1):null}
                    });
                    const row=(event_id,pubs)=>({
                        event_id,tour:'WTA',surface:'hard',scheduled_at:when,tournament:'QA',
                        player1:{id:'p1',name:'Alice'},player2:{id:'p2',name:'Bob'},
                        market_publications:pubs
                    });
                    s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active'};
                    s.feed.results=[
                        row('shared',[publication('top_daily','match_winner','p1'),
                                      publication('value','match_winner','p1')]),
                        row('prime',[publication('prime','match_winner','p1')]),
                        row('ace',[publication('ace','aces','p1:aces')]),
                        row('df',[publication('double_faults','double_faults','p1:df')]),
                        row('sets',[publication('sets','sets','over:2.5')]),
                        row('games',[publication('games','games','over:20.5')])
                    ];
                    s.resultsFilters={category:'all',tour:'',surface:'',window:'all',
                                      dateFrom:'',dateTo:'',bettingDay:true};
                    s.resultsPage=0;
                    const authDialog=document.querySelector('#authDialog');
                    if(authDialog?.open)authDialog.close();
                    authDialog?.remove();
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelector('#appShell').hidden=false;
                    document.querySelector('#routePanel').hidden=false;
                    s.route='results';
                    t.renderRoute('results');
                }""")
                table = page.locator(".results-table tbody tr")
                assert table.count() == 6, (width, table.count())
                page.locator(".results-category-picker summary").click()
                page.locator('input[data-result-category="top_daily"]').check()
                assert table.count() == 1, (width, "TOP", table.count())
                page.locator('input[data-result-category="value"]').check()
                assert table.count() == 1, (width, "TOP+Value dedup", table.count())
                tags = page.locator(".results-table tbody tr:first-child .result-tag").all_inner_texts()
                assert tags == ["TOP", "Value"], (width, tags)
                for category, count in [("ace", 2), ("double_faults", 3), ("sets", 4), ("games", 5)]:
                    page.locator(f'input[data-result-category="{category}"]').check()
                    assert table.count() == count, (width, category, table.count())
                assert page.locator('.metric-card strong').last.inner_text() == '5', width
                page.locator('input[data-result-category="top_daily"]').uncheck()
                assert table.count() == 5
                assert page.locator(".results-table tbody tr .result-tag").all_inner_texts().count("TOP") == 0
                assert "Value" in page.locator(".results-table tbody tr .result-tag").all_inner_texts()
                page.locator('input[data-result-category="all"]').check()
                assert table.count() == 6
                assert page.locator('input[data-result-category="all"]').is_checked()
                assert not errors, (width, errors)
                page.close()
            print("Results category multi-select real-browser regression: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
