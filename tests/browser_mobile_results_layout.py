"""Phone/Tablet Results geometry + mobile filter behavior gate (offline Chromium)."""
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
            "  window.mobileGeometry={state,renderResultsFilters,resultsSummary,resultsOutcomeTabs,"
            "renderResults,wireResultsFilters,renderInsightBell};\n" + marker,
        )
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


FIXTURE = """() => {
  document.querySelector('#bootSplash')?.remove();
  document.querySelector('#cookieConsent')?.remove();
  document.querySelectorAll('dialog[open]').forEach(el=>el.close());
  document.querySelector('#appShell').hidden=false;
  const t=mobileGeometry,s=t.state;
  s.route='results';s.resultsFilterOpen=false;s.resultsDraftFilters=null;s.resultsOutcomeTab='all';
  s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active'};
  s.ui.notifications={...(s.ui.notifications||{}),enabled:true};
  s.resultsFilters={category:'all',tour:'',surface:'',window:'all',dateFrom:'',dateTo:'',bettingDay:true};
  s.resultsPage=0;s.resultsPageSize=50;
  s.feed.results=Array.from({length:7},(_,i)=>({
    event_id:'result-'+i,tour:i%2?'WTA':'ATP',surface:'clay',
    scheduled_at:'2026-09-27T14:00:00Z',
    tournament:'ITF M25 Sharm El Sheikh 4, Egypt, Qualification Round 1',
    tournament_city:'Sharm El Sheikh',
    player1:{id:'p1-'+i,name:'Alejandro Fernandez de la Cruz',country_code:'ESP'},
    player2:{id:'p2-'+i,name:'Maximiliano Alessandro Dimitrov',country_code:'BUL'},
    market_publications:[{
      section:i%2?'games':'top_daily',market:i%2?'games':'match_winner',
      issued_at:'2026-09-26T17:00:00Z',
      selection:i%2?'Over 22.5 Games':'Alejandro Fernandez de la Cruz',
      selection_id:i%2?'games-over':'p1-'+i,model_probability:.65,odds:1.7,
      price_status:i%2?'priced_projection':'priced',
      result:{status:i===1?'miss':'hit',correct:i!==1,staked_units:1,
        profit_units:i===1?-1:.7,...(i%2?{actual_count:25,projection:23.4}:{})}
    }]
  }));
  document.body.classList.remove('blinq-home','blinq-admin');
  document.body.classList.add('blinq-route');
  document.body.dataset.route='results';
  document.querySelector('#routePanel').hidden=false;
  document.querySelector('#routePanel').innerHTML=
    t.renderResultsFilters()+t.resultsSummary()+t.resultsOutcomeTabs()+
    '<div class="route-sub results-section-head results-section-clean">'+t.renderResults()+'</div>';
  window.BlinqUI.prepareRoute(document.querySelector('#routePanel'));
  t.wireResultsFilters();
  document.querySelector('#profileName').textContent='@BackstageTalks';
  const projects=document.querySelector('#projectGroupBar');
  projects.hidden=false;
  projects.innerHTML='<button class="project-group-chip is-purple is-active" type="button"><span>◆</span><strong>Platba PO</strong></button>';
  document.querySelector('#insightShortcut').hidden=false;
  document.querySelector('#topUpgradeButton').hidden=false;
  t.renderInsightBell();
}"""


def main():
    widths = (320, 360, 390, 430, 768, 900, 1024, 1440)
    with sync_playwright() as pw:
        executable = os.getenv("BLINQ_BROWSER") or browser_path()
        browser = pw.chromium.launch(headless=True, executable_path=executable) if executable else pw.chromium.launch(headless=True)
        try:
            for width in widths:
                height = 844 if width == 390 else 820
                page = browser.new_page(viewport={"width": width, "height": height})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.mobileGeometry && mobileGeometry.state.ui")
                page.evaluate(FIXTURE)
                page.wait_for_selector("#routePanel .results-table tbody tr")
                report = page.evaluate("""() => {
                  const q=s=>document.querySelector(s);
                  const visible=e=>!!e&&getComputedStyle(e).display!=='none'&&!e.hidden;
                  const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
                  const table=q('.results-table'),wrap=q('.results-table-wrap'),first=q('.results-table tbody tr');
                  const toggle=q('.results-mobile-filter-toggle'),bar=q('.results-filter-bar-v683'),nav=q('.mobile-tabs');
                  const projects=q('#projectGroupBar');
                  const controls=['#insightShortcut','#topUpgradeButton','#insightBell','#profileShell'].map(s=>q(s)).filter(visible).map(rect);
                  const kpis=[...document.querySelectorAll('.metric-card')].map(rect);
                  return {
                    docOverflow:document.documentElement.scrollWidth-innerWidth,
                    bodyOverflow:document.body.scrollWidth-innerWidth,
                    appOverflow:q('#appShell').scrollWidth-innerWidth,
                    table:rect(table),wrap:rect(wrap),first:rect(first),
                    tableDisplay:getComputedStyle(table).display,
                    minWidth:getComputedStyle(table).minWidth,
                    toggleVisible:visible(toggle),barDisplay:getComputedStyle(bar).display,
                    navVisible:visible(nav),projectsVisible:visible(projects),
                    outcomeVisible:visible(q('.results-outcome-tabs')),
                    controls,kpis,
                    headingVisible:visible(q('.results-mobile-heading')),
                    firstCardBottom:first.getBoundingClientRect().bottom,
                    navTop:nav?.getBoundingClientRect().top||Infinity,
                    tournamentWhiteSpace:getComputedStyle(q('.tournament-identity-copy>strong')).whiteSpace,
                  };
                }""")
                assert report["docOverflow"] <= 2, (width, report)
                assert report["bodyOverflow"] <= 2, (width, report)
                assert report["appOverflow"] <= 2, (width, report)
                if width <= 767:
                    assert report["toggleVisible"] and report["headingVisible"], (width, report)
                    assert report["barDisplay"] == "none", (width, report)
                    assert report["navVisible"] and not report["projectsVisible"], (width, report)
                    assert report["outcomeVisible"], (width, report)
                    assert report["tableDisplay"] == "block" and report["minWidth"] == "0px", (width, report)
                    assert report["first"]["right"] <= width + 2, (width, report)
                    assert all(c["width"] >= 43.5 and c["height"] >= 43.5 for c in report["controls"]), (width, report)
                    expected_cols = 2 if width < 360 else 3
                    tops = [round(k["top"], 1) for k in report["kpis"]]
                    assert len(set(tops[:expected_cols])) == 1, (width, tops)
                    if width == 390:
                        assert report["firstCardBottom"] <= report["navTop"] - 4, report
                        # Open drawer: it stays open through field edits and uses draft state.
                        page.click('[data-results-filter-toggle]')
                        page.select_option('#resultsCategory','top_daily')
                        state = page.evaluate("""() => ({
                          open:mobileGeometry.state.resultsFilterOpen,
                          applied:mobileGeometry.state.resultsFilters.category,
                          draft:mobileGeometry.state.resultsDraftFilters.category,
                          display:getComputedStyle(document.querySelector('.results-filter-bar-v683')).display
                        })""")
                        assert state == {"open": True, "applied": "all", "draft": "top_daily", "display": "grid"}, state
                        # Closing without Apply discards the draft.
                        page.click('[data-results-filter-toggle]')
                        state = page.evaluate("""() => ({
                          open:mobileGeometry.state.resultsFilterOpen,
                          applied:mobileGeometry.state.resultsFilters.category,
                          draft:mobileGeometry.state.resultsDraftFilters
                        })""")
                        assert state == {"open": False, "applied": "all", "draft": None}, state
                        # Re-open, Reset only changes draft; Apply commits and closes.
                        page.click('[data-results-filter-toggle]')
                        page.select_option('#resultsCategory','top_daily')
                        page.click('#resultsFilterReset')
                        reset = page.evaluate("""() => ({
                          applied:mobileGeometry.state.resultsFilters.category,
                          draft:mobileGeometry.state.resultsDraftFilters.category,
                          window:mobileGeometry.state.resultsDraftFilters.window
                        })""")
                        assert reset == {"applied": "all", "draft": "all", "window": "today"}, reset
                        page.select_option('#resultsCategory','top_daily')
                        page.click('#resultsFilterApply')
                        applied = page.evaluate("""() => ({
                          open:mobileGeometry.state.resultsFilterOpen,
                          applied:mobileGeometry.state.resultsFilters.category,
                          draft:mobileGeometry.state.resultsDraftFilters
                        })""")
                        assert applied == {"open": False, "applied": "top_daily", "draft": None}, applied
                elif width <= 900:
                    assert not report["toggleVisible"] and not report["headingVisible"], (width, report)
                    assert report["barDisplay"] == "grid", (width, report)
                    assert not report["navVisible"] and not report["projectsVisible"], (width, report)
                    assert not report["outcomeVisible"], (width, report)
                    assert report["tableDisplay"] == "table" and report["minWidth"] != "0px", (width, report)
                    assert report["wrap"]["right"] <= width + 2, (width, report)
                else:
                    assert not report["toggleVisible"] and not report["navVisible"], (width, report)
                    assert not report["outcomeVisible"], (width, report)
                    assert report["tableDisplay"] == "table", (width, report)
                assert not errors, (width, errors)
                page.close()
            print("Results phone 320/360/390/430 + tablet 768/900 + desktop 1024/1440: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
