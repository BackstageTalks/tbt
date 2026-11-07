"""Monthly analytics must agree with Results today (06:00 Bratislava, tier, units)."""
import os
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        source = source.replace(marker, (
            "  window.monthlyParityTest={state,bratislavaBettingDayKey,bratislavaBoundaryTimestamp,"
            "monthlyPerformanceState,monthlyMetricRows,monthlyMetricSummary,monthlyRecordDay,"
            "renderMonthlyPerformance,localResultMetrics,filteredResults,settledPublishedEntries};\n"
            + marker
        ))
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        executable = os.getenv("BLINQ_BROWSER") or browser_path()
        browser = (pw.chromium.launch(headless=True, executable_path=executable)
                   if executable else pw.chromium.launch(headless=True))
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route("**/*", route_request)
            page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
            page.wait_for_function("window.monthlyParityTest && monthlyParityTest.state.ui")
            result = page.evaluate("""() => {
              const t=monthlyParityTest,s=t.state;
              const today=t.bratislavaBettingDayKey(Date.now(),6);
              const start=t.bratislavaBoundaryTimestamp(today,6);
              const prev=t.bratislavaBettingDayKey(start-1000,6);
              const issued=new Date(start+10*60000).toISOString();
              const pub=(day,section='top_daily',profit=.60)=>({
                publication_status:'published',section,market:'match_winner',
                issued_at:issued,betting_day:day,selection_id:'p1',
                selection:'Player A',odds:1.6,price_status:'priced',
                result:{status:'hit',correct:true,staked_units:100,profit_units:profit}
              });
              const mk=(event_id,when,day,section='top_daily')=>({
                event_id,tour:'ATP',surface:'hard',scheduled_at:new Date(when).toISOString(),
                player1:{id:'p1',name:'Player A'},player2:{id:'p2',name:'Player B'},
                market_publications:[pub(day,section)]
              });
              const valid=mk('valid-today',start+30*60000,today);
              valid.market_publications.push(pub(today,'value'));
              const beforeSix=mk('before-six',start-2*3600000,prev);
              const stale=mk('stale-issuance',start+60*60000,prev);
              s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active'};
              s.feed.results=[beforeSix,valid,stale];
              s.feed.results_exclusions_unavailable=false;
              s.feed.member_result_rules={elite:{
                daily:{enabled:true,display_state:'active',visible_picks:'ALL',row_overrides:{}},
                value:{enabled:true,display_state:'active',visible_picks:'ALL',row_overrides:{}}
              }};
              s.feed.daily_picks=[];
              s.feed.top_daily_picks=[];
              s.feed.value_picks=[];
              s.ui.dashboard=s.ui.dashboard||{};
              s.ui.dashboard.daily_hub=s.ui.dashboard.daily_hub||{};
              s.ui.dashboard.daily_hub.tabs={daily:{enabled:true,exclude_from_stats:false},
                value:{enabled:true,exclude_from_stats:false}};
              s.monthlyPerformance={
                month:today.slice(0,7),level:'elite',view:'report',fullscreen:true,
                filtersExpanded:false,
                sections:['top_daily','prime','value','doubles','ace','double_faults','sets','games'],
                tour:'',surface:'',minOdds:'',maxOdds:'',outcomes:['win','loss','void']
              };
              const f={category:'all',tour:'',surface:'',window:'today',bettingDay:true,
                membership:'elite'};
              const todayRows=t.filteredResults(f);
              const results=t.settledPublishedEntries(todayRows,'all',f);
              const actual=t.localResultMetrics(todayRows,'all',f);
              const monthRows=t.monthlyMetricRows('elite');
              const summary=t.monthlyMetricSummary(monthRows,'elite');
              const todayRowsInMonth=summary.all.filter(x=>t.monthlyRecordDay(x.row)===today);
              const html=t.renderMonthlyPerformance();
              document.body.classList.remove('blinq-home');
              document.body.classList.add('blinq-admin');
              const host=document.querySelector('#routePanel');
              document.querySelector('#bootSplash')?.remove();
              document.querySelector('#cookieConsent')?.remove();
              document.querySelector('#appShell').hidden=false;
              host.hidden=false;host.innerHTML=html;
              const table=host.querySelector('.monthly-focused-table');
              const tableVisible=!!table&&table.querySelectorAll('thead th').length===4;
              const parity=host.querySelector('.monthly-parity-note')?.textContent||'';
              const screen=host.querySelector('.monthly-performance');
              const left=screen?.getBoundingClientRect().left;
              const right=screen?.getBoundingClientRect().right;
              const lastColumnRight=table?.querySelector('thead th:last-child')?.getBoundingClientRect().right;
              const alignment=getComputedStyle(screen?.querySelector('.monthly-stat')).textAlign;
              // Compare a one-category VALUE selection. Its duplicate was
              // deduplicated only after the actual category was selected.
              s.monthlyPerformance.sections=['value'];
              const vf={...f,category:'value'};
              const valueResults=t.localResultMetrics(t.filteredResults(vf),'value',vf);
              const valueMonth=t.monthlyMetricSummary(t.monthlyMetricRows('elite'),'elite','value');
              // Confirm global stats exclusion is shared rather than silently counted.
              s.monthlyPerformance.sections=['top_daily'];
              s.ui.dashboard.daily_hub.tabs.daily.exclude_from_stats=true;
              const tf={...f,category:'top_daily'};
              const excludedResults=t.localResultMetrics(t.filteredResults(tf),'top_daily',tf);
              const excludedMonth=t.monthlyMetricRows('elite');
              return {
                today,prev,resultIds:results.map(x=>x.row.event_id),
                resultWin:actual.wins,resultLoss:actual.losses,resultProfit:actual.profit,
                monthTodayWin:todayRowsInMonth.filter(x=>x.outcome==='win').length,
                monthTodayProfit:summary.daily.get(today)||0,
                monthBefore:summary.daily.get(prev)||0,
                fullProfit:summary.profit,
                reporting:html.includes('06:00–06:00'),
                parity,tableVisible,left,right,lastColumnRight,alignment,
                valueResultWin:valueResults.wins,valueMonthWin:valueMonth.wins,
                valueResultProfit:valueResults.profit,valueMonthProfit:valueMonth.profit,
                excludedResultWin:excludedResults.wins,excludedMonthCount:excludedMonth.length
              };
            }""")
            assert result["resultIds"] == ["valid-today"], result
            assert result["resultWin"] == result["monthTodayWin"] == 1, result
            assert result["resultLoss"] == 0, result
            assert abs(result["resultProfit"] - .60) < 1e-9, result
            assert abs(result["monthTodayProfit"] - result["resultProfit"]) < 1e-9, result
            if result["today"][:7] == result["prev"][:7]:
                assert abs(result["monthBefore"] - .60) < 1e-9, result
            assert result["reporting"] and result["tableVisible"], result
            assert "Overené:" in result["parity"] and "1/0/0" in result["parity"], result
            assert 0 <= result["left"] < result["right"] <= 391, result
            assert result["lastColumnRight"] <= 391, result
            assert result["alignment"] == "center", result
            assert result["valueResultWin"] == result["valueMonthWin"] == 1, result
            assert abs(result["valueResultProfit"] - result["valueMonthProfit"]) < 1e-9, result
            assert result["excludedResultWin"] == result["excludedMonthCount"] == 0, result
            assert not errors, errors
            print("PASS: 06:00 betting day, ELITE parity, 1u, dedup, exclusions, mobile grid")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
