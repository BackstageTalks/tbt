"""Regression: admin's ELITE opt-out must not show global 62 bets in Results."""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        source = source.replace(
            "  boot();",
            "  window.eliteCohortTest={state,todayPublishedPickCount,settledPublishedEntries,resultsSummary,bratislavaBettingDayKey,effectiveMemberResultRule};\n  boot();",
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
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.route("**/*", route_request)
            page.goto(ORIGIN)
            page.wait_for_function("window.eliteCohortTest")
            observed = page.evaluate("""() => {
              const t=eliteCohortTest,s=t.state;
              const day=t.bratislavaBettingDayKey(Date.now(),6);
              const make=(id,section,market)=>({
                event_id:id,scheduled_at:day+'T12:00:00Z',tour:'ATP',
                market_publications:[{
                  section,market,selection_id:'p1',selection:'A',
                  issued_at:day+'T07:00:00Z',betting_day:day,
                  price_status:'priced',odds:1.8,
                  result:{correct:true,staked_units:1,profit_units:0.8}
                }]
              });
              const rows=[
                ...Array.from({length:9},(_,i)=>make('top-'+i,'top_daily','match_winner')),
                ...Array.from({length:53},(_,i)=>make('ace-'+i,'ace_winner','most_aces'))
              ];
              const full=Object.fromEntries(['daily','ace_winner'].map(tab=>[tab,{
                enabled:true,display_state:'active',visible_picks:'ALL',row_overrides:{}
              }]));
              s.feed={account:{is_admin:true,role:'admin',plan:'admin',status:'active'},
                results:rows,member_result_rules:{elite:full,legend:full,goat:full},
                entitlements:{results_history_hours:null,result_categories:['top_daily','ace_winner']}};
              s.ui={dashboard:{daily_hub:{tabs:{
                daily:{enabled:true,plans:Object.fromEntries(['elite','legend','goat'].map(p=>[p,{visible_rows:'ALL',tab_enabled:true,display_state:'active'}]))},
                ace_winner:{enabled:true,plans:{
                  elite:{visible_rows:0,tab_enabled:false,display_state:'hidden'},
                  legend:{visible_rows:'ALL',tab_enabled:true,display_state:'active'},
                  goat:{visible_rows:'ALL',tab_enabled:true,display_state:'active'}
                }}
              }}}};
              s.resultsFilters={category:'all',window:'today',bettingDay:true,
                tour:'',surface:'',membership:'elite'};
              const counts=Object.fromEntries(['elite','legend','goat'].map(p=>[p,t.todayPublishedPickCount(p)]));
              const all=t.settledPublishedEntries(rows,'all',{window:'all'}).length;
              const elite=t.settledPublishedEntries(rows,'all',{window:'all',membership:'elite'});
              const legend=t.settledPublishedEntries(rows,'all',{window:'all',membership:'legend'});
              const summary=t.resultsSummary();
              return {counts,all,elite:elite.length,legend:legend.length,
                eliteAces:elite.filter(e=>e.publication.market==='most_aces').length,
                summaryHasNine:summary.includes('9/9')};
            }""")
            assert observed == {
                "counts": {"elite": 9, "legend": 62, "goat": 62},
                "all": 62, "elite": 9, "legend": 62,
                "eliteAces": 0, "summaryHasNine": True
            }, observed
            assert not errors, errors
            print("ELITE authorized sample 9/9; LEGEND and GOAT retain 62/62: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
