"""Offline browser: screenshot-equivalent GAMES/DOUBLES ROI + depth removal."""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        injected = "  window.resultsFinancialAudit={state,renderResults,resultsSummary};\n" + marker
        route.fulfill(content_type="application/javascript", body=source.replace(marker, injected))
    else:
        static_route(route)


def check_summary(page, expected):
    page.evaluate("""() => {
      document.getElementById('routePanel').innerHTML=
        resultsFinancialAudit.resultsSummary()+resultsFinancialAudit.renderResults();
    }""")
    metric = page.locator("#routePanel .metric-card strong").all_inner_texts()
    assert metric == expected, metric
    assert page.locator("#routePanel .results-table th").last.inner_text() == "Jednotky"
    assert page.locator("#routePanel .results-units-depth small").count() == 0
    text = page.locator("#routePanel .metric-cards").inner_text()
    assert "bez Short Odds" not in text


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, executable_path=os.getenv("BLINQ_BROWSER") or browser_path()
        )
        try:
            for width in (390, 1440):
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.resultsFinancialAudit && resultsFinancialAudit.state.ui")
                page.evaluate("""() => {
                  const s=resultsFinancialAudit.state;
                  document.getElementById('appShell').hidden=false;
                  document.getElementById('routePanel').hidden=false;
                  document.body.classList.add('blinq-route');
                  s.resultsPage=0;s.resultsPageSize=50;
                  s.resultsFilters={category:'games',window:'all',tour:'',surface:''};
                  const odds=[1.65,1.67,1.83,1.55,1.54];
                  s.feed.results=odds.map((o,i)=>{
                    const real=i===2;
                    return {
                      event_id:'games-'+i,tour:'WTA',
                      scheduled_at:'2026-09-26T12:00:00Z',
                      tournament:'Audit Games',
                      player1:{id:'a'+i,name:'A '+i},player2:{id:'b'+i,name:'B '+i},
                      market_publications:[{
                        section:'games',market:'games',selection:'Over 19.5 Games',
                        selection_id:'games:over:'+i,issued_at:'2026-09-25T10:00:00Z',
                        price_status:real?'priced_projection':'projection_only',
                        odds:real?o:null,
                        historical_display_placeholder_odds:real?null:o,
                        historical_display_placeholder_source:real?null:'synthetic_illustrative_not_bookmaker',
                        result:{status:'hit',correct:true,actual_count:23,
                           ...(real?{staked_units:100,profit_units:.83}:{})}
                      }]
                    }
                  });
                }""")
                # Legacy rows may carry a 100-sized stake scale while
                # profit_units is already normalized to the displayed 1u result.
                # Filter ROI must stay 83%, not be diluted to 0.83%.
                check_summary(page, ["5-0", "100.0%", "1.83", "83.0%", "+0.83u", "5"])
                # Existing illustrative units are deliberately retained in
                # individual rows; unlike the real quoted ROI sample they are NOT stakes.
                assert page.locator("#routePanel .results-units-depth b").count() == 5
                page.evaluate("""() => {
                  const s=resultsFinancialAudit.state;
                  s.resultsFilters.category='doubles';
                  s.feed.results=[1.4,1.8,1.36].map((odds,i)=>({
                    event_id:'doubles-'+i,tour:'WTA',
                    scheduled_at:'2026-09-26T12:00:00Z',tournament:'Audit Doubles',
                    prediction_family:'doubles',
                    player1:{id:'teamA'+i,name:'A / B'},
                    player2:{id:'teamB'+i,name:'C / D'},
                    market_publications:[{
                      section:'doubles',market:'match_winner',
                      selection_id:'teamA'+i,selection:'A / B',
                      issued_at:'2026-09-25T10:00:00Z',odds,
                      result:{status:'hit',correct:true,staked_units:100,profit_units:odds-1}
                    }]
                  }));
                }""")
                # Same contract for a filtered match-winner sample: 1u per
                # settled quoted pick regardless of legacy staked_units scale.
                check_summary(page, ["3-0", "100.0%", "1.52", "52.0%", "+1.56u", "3"])
                assert not errors, errors
                page.close()
            print("Real-browser Results financial consistency and no data-depth: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
