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
            # Android Chrome's "Desktop site" keeps mobile touch/UA but
            # switches to a wide layout viewport. Reproduce that separately
            # from normal narrow mobile and desktop Chromium.
            scenarios = [
                ("mobile", 390, False),
                ("android-desktop-site", 980, True),
                ("desktop", 1440, False),
            ]
            for scenario, width, android_desktop_site in scenarios:
                browser_options = {"viewport": {"width": width, "height": 900}}
                if android_desktop_site:
                    browser_options.update({
                        "is_mobile": True,
                        "has_touch": True,
                        "device_scale_factor": 2.75,
                        "user_agent": ("Mozilla/5.0 (Linux; Android 16; Mobile) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                                       "Chrome/143.0.0.0 Mobile Safari/537.36"),
                    })
                context = browser.new_context(**browser_options)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.resultsMultiTest && resultsMultiTest.state.ui")
                page.evaluate("""() => {
                    const t=resultsMultiTest,s=t.state,when=new Date().toISOString();
                    const publication=(section,market,selection,correct=true)=>({
                        section,market,selection,selection_id:selection,
                        issued_at:new Date(Date.now()-7200000).toISOString(),
                        price_status:['aces','most_aces','double_faults','sets','games'].includes(market)?'projection_only':'priced',
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
                        row('doubles',[publication('doubles','match_winner','p1')]),
                        row('ace',[publication('ace','aces','p1:aces')]),
                        row('df',[publication('double_faults','double_faults','p1:df')]),
                        row('sets',[publication('sets','sets','over:2.5')]),
                        row('games',[publication('games','games','over:20.5')])
                    ];
                    // Match the configurable category tabs shown on the home page.
                    s.ui=s.ui||{};
                    s.ui.dashboard=s.ui.dashboard||{};
                    s.ui.dashboard.daily_hub=s.ui.dashboard.daily_hub||{};
                    s.ui.dashboard.daily_hub.tab_order=[
                        'daily','value','ace','ace_winner','double_faults','sets','doubles','games','prime','see_all'
                    ];
                    s.resultsFilters={category:'all',tour:'',surface:'',window:'1',
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
                    document.body.classList.remove('blinq-home');
                    document.body.classList.add('blinq-route');
                    t.renderRoute('results');
                }""")
                table = page.locator(".results-table tbody tr")
                assert table.count() == 7, (scenario, table.count())
                expected_order = ['all', 'top_daily', 'value', 'ace', 'ace_winner', 'double_faults',
                                  'sets', 'doubles', 'games', 'prime']
                rendered_order = page.locator('.results-category-picker [data-result-category]').evaluate_all(
                    '(nodes) => nodes.map(node => node.dataset.resultCategory)'
                )
                assert rendered_order == expected_order, (scenario, rendered_order)
                select_order = page.locator('#resultsCategory option').evaluate_all(
                    '(nodes) => nodes.map(node => node.value)'
                )
                assert select_order == expected_order, (scenario, select_order)

                drawer = page.locator("[data-results-filter-toggle]")
                if android_desktop_site:
                    assert not drawer.is_visible(), scenario
                if drawer.is_visible():
                    drawer.click()
                    assert drawer.get_attribute("aria-expanded") == "true", width
                page.locator(".results-category-picker summary").click()
                # The open checkbox element must survive re-rendering: desktop
                # and Android desktop-site must support consecutive selections.
                page.evaluate("window.__resultsPicker= document.querySelector('.results-category-picker')")
                page.locator('input[data-result-category="top_daily"]').check()
                assert page.evaluate("document.querySelector('.results-category-picker') === window.__resultsPicker"), scenario
                assert table.count() == 1, (width, "TOP", table.count())
                page.locator('input[data-result-category="value"]').check()
                assert table.count() == 1, (width, "TOP+Value dedup", table.count())
                tags = page.locator(".results-table tbody tr:first-child .result-tag").all_inner_texts()
                assert tags == ["TOP", "Value"], (width, tags)
                for category, count in [("ace", 2), ("double_faults", 3), ("sets", 4), ("games", 5)]:
                    page.locator(f'input[data-result-category="{category}"]').check()
                    assert table.count() == count, (width, category, table.count())
                    assert page.evaluate("document.querySelector('.results-category-picker') === window.__resultsPicker"), (scenario, category)
                    if drawer.is_visible():
                        assert drawer.get_attribute('aria-expanded') == 'true', (width, category)
                # This is the screenshot's exact situation: six checked
                # categories exclude Doubles, so a successful filter may
                # legitimately show only TOP when other kinds have no results.
                assert table.count() == 5, (scenario, "selected six excluding doubles")
                assert page.locator('.metric-card strong').last.inner_text() == '5', scenario
                page.locator('input[data-result-category="doubles"]').check()
                assert table.count() == 6, (scenario, "including doubles")
                assert "Štvorhra" in page.locator(".results-table tbody .result-tag").all_inner_texts(), scenario
                assert page.locator('.results-category-picker summary').inner_text() == (
                    'TOP, Value, Esá, Dvojchyby, Sety, Štvorhra, Gamy'
                ), scenario

                # Simulate the reported mismatch: boxes visually remain
                # checked, but the previously serialized category is stale.
                # A checkbox change must recompute the union from the DOM.
                page.evaluate("resultsMultiTest.state.resultsFilters.category='top_daily'")
                page.locator('input[data-result-category="top_daily"]').uncheck()
                assert page.evaluate("resultsMultiTest.state.resultsFilters.category") == (
                    'value,ace,double_faults,sets,doubles,games'
                ), scenario
                assert table.count() == 6
                assert page.locator(".results-table tbody tr .result-tag").all_inner_texts().count("TOP") == 0
                assert "Value" in page.locator(".results-table tbody tr .result-tag").all_inner_texts()
                page.locator('input[data-result-category="all"]').check()
                assert table.count() == 7
                assert page.locator('input[data-result-category="all"]').is_checked()
                assert not errors, (width, errors)
                # VIAC ES is a real Results category after ESÁ, with its
                # own graded record/KPI sample even without bookmaker odds.
                page.evaluate("""() => {
                    const s=resultsMultiTest.state;
                    s.feed.results.push({
                        event_id:'ace-winner-qa',tour:'ATP',surface:'hard',
                        scheduled_at:new Date().toISOString(),tournament:'QA',
                        player1:{id:'a1',name:'Winner candidate'},
                        player2:{id:'a2',name:'Opponent'},
                        market_publications:[{
                          section:'ace_winner',market:'most_aces',
                          projection_metric:'most_aces',projection_scope:'player',
                          projection_subject:'Winner candidate',
                          selection:'Winner candidate',selection_id:'a1',
                          projection:8.0,opponent_projection:5.0,
                          price_status:'projection_only',price_contract:'player_superiority',
                          odds:null,issued_at:new Date(Date.now()-3600000).toISOString(),
                          result:{status:'hit',correct:true,actual_count:10,opponent_actual_count:3}
                        }]
                    });
                    s.resultsFilters.category='ace_winner';
                    s.resultsPage=0;
                    resultsMultiTest.renderRoute('results');
                }""")
                assert table.count() == 1, (scenario, "VIAC ES own Results row", table.count())
                assert "VIAC ES" in page.locator(".results-table tbody").inner_text().upper()
                assert page.locator(".metric-card strong").last.inner_text() == "1"
                assert not errors, (scenario, errors)
                # Full rendered Results DOM, using the actual frozen Telegram
                # publication shape, not only a standalone helper test.
                page.evaluate("""() => {
                    const s=resultsMultiTest.state;
                    s.feed.results=[{
                        event_id:'17427331',tour:'ATP',surface:'hard',
                        scheduled_at:new Date().toISOString(),tournament:'Charlottesville',
                        player1:{id:'presentation-mayo',name:'Aidan Mayo'},
                        player2:{id:'presentation-andrade',name:'Andres Andrade'},
                        market_publications:[{
                            section:'ace',market:'aces',selection_id:'309157',
                            selection:'Aidan Mayo Over 4.5 Aces',price_contract:'player_total_ou',
                            ou_side:'over',market_line:4.5,projection:5.67,
                            issued_at:new Date(Date.now()-3600000).toISOString(),
                            odds:1.70,price_status:'priced_projection',
                            result:{status:'hit',correct:true,void:false,
                                    reason:'retired_after_ou_decided',retirement_line_decided:true,
                                    runtime_source:'match_status_snapshot',
                                    actual_count:5,opponent_actual_count:0,
                                    staked_units:1,profit_units:0.7}
                        }]
                    }];
                    s.resultsFilters.category='ace';
                    s.resultsPage=0;
                    resultsMultiTest.renderRoute('results');
                }""")
                assert table.count() == 1, (scenario, "Mayo result missing")
                mayo_row = page.locator(".results-table tbody .results-match-player")
                opponent_row = page.locator(".results-table tbody .results-opponent")
                assert "Aidan Mayo" in mayo_row.inner_text()
                assert mayo_row.locator(".ace-leader-ball").count() == 1, (scenario, "Mayo leader ball missing in DOM")
                assert opponent_row.locator(".ace-leader-ball").count() == 0, (scenario, "Andrade incorrectly marked")
                ball = mayo_row.locator(".ace-leader-ball")
                assert ball.is_visible(), (scenario, "Mayo marker present but invisible")
                geometry = ball.evaluate("""svg => {
                    const r=svg.getBoundingClientRect(),row=svg.closest('.results-match-player').getBoundingClientRect();
                    const style=getComputedStyle(svg);
                    return {width:r.width,height:r.height,left:r.left,right:r.right,top:r.top,bottom:r.bottom,
                            rowLeft:row.left,rowRight:row.right,rowTop:row.top,rowBottom:row.bottom,
                            opacity:Number(style.opacity),display:style.display,visibility:style.visibility};
                }""")
                assert geometry["width"] >= 10 and geometry["height"] >= 10, (scenario, "Mayo icon collapsed", geometry)
                assert geometry["opacity"] > 0.5 and geometry["visibility"] == "visible" and geometry["display"] != "none", (scenario, "Mayo icon hidden", geometry)
                assert (geometry["left"] >= geometry["rowLeft"] - 1
                        and geometry["right"] <= geometry["rowRight"] + 1
                        and geometry["top"] >= geometry["rowTop"] - 1
                        and geometry["bottom"] <= geometry["rowBottom"] + 1), (scenario, "Mayo icon clipped outside row", geometry)
                page.evaluate("""() => {
                    const s=resultsMultiTest.state;
                    s.feed.results[0].market_publications[0].result.retirement_line_decided=false;
                    resultsMultiTest.renderRoute('results');
                }""")
                assert page.locator(".results-table .ace-leader-ball").count() == 0, (scenario, "unverified retirement marker")
                page.evaluate("""() => {
                    const s=resultsMultiTest.state;
                    s.feed.results[0].market_publications[0].result.retirement_line_decided=true;
                    resultsMultiTest.renderRoute('results');
                }""")
                assert mayo_row.locator(".ace-leader-ball").count() == 1, (scenario, "verified retirement leader restored")
                page.evaluate("""() => {
                    const s=resultsMultiTest.state;
                    s.feed.results[0].market_publications[0].result.opponent_actual_count=null;
                    resultsMultiTest.renderRoute('results');
                }""")
                assert page.locator(".results-table .ace-leader-ball").count() == 0, (scenario, "unknown opponent falsely marked")
                assert "súper —" in table.inner_text(), (scenario, "unknown stat rendered as false zero")
                assert not errors, (scenario, errors)
                context.close()
            print("Results category multi-select including Android Desktop site and 24h: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
