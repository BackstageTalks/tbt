"""Regression: 2/9 symptom must not hide pre-match Aces O/U settlement.

The Today cohort is derived from the signed selection/side/line publication,
not a top-level match winner id or unpriced display projection. No API calls.
"""
from urllib.parse import urlparse
import os

from playwright.sync_api import sync_playwright

from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        source = source.replace(
            marker,
            "  window.todayTierAudit={state,currentBettingDayPublishedKeys,filteredResults,"
            "settledPublishedEntries,memberResultCohort,localResultMetrics,"
            "bratislavaBettingDayKey};\n" + marker,
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
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route("**/*", route_request)
            page.goto(ORIGIN)
            page.wait_for_function("window.todayTierAudit")
            result = page.evaluate("""() => {
                const t=todayTierAudit,s=t.state;
                const day=t.b ratislavaBettingDayKey(Date.now(),6);
                const make=(h,m=0)=>day+'T'+String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')+':00Z';
                const winner=(event,section,odds,correct)=>{
                    const p={section,market:'match_winner',selection_id:'p2',
                      publication_status:'published',issued_at:make(6),odds,
                      price_status:'priced',result:{status:correct?'hit':'miss',
                        correct,staked_units:1,profit_units:correct?odds-1:-1,
                        runtime_source:'match_status_snapshot'}};
                    return {event_id:event,scheduled_at:make(12),player1:{id:'p1'},
                      player2:{id:'p2'},market_publications:[p]};
                };
                const ace=(event,selected,line,odds,actual,correct,finished=true)=>{
                    const p={section:'ace',market:'aces',projection_metric:'aces',
                      projection_scope:'player',selection_id:selected,
                      price_contract:'player_total_ou',ou_side:'over',market_line:line,
                      publication_status:'published',issued_at:make(6),price_status:'priced_projection',
                      odds,publication_key:'local-aces-ou-v1:'+event+':'+selected+':over:'+line,
                      ...(finished?{result:{status:correct?'hit':'miss',correct,actual_count:actual,
                        staked_units:1,profit_units:correct?odds-1:-1,
                        runtime_source:'match_status_snapshot'}}:{})};
                    const row={event_id:event,scheduled_at:make(12),player1:{id:selected},
                      player2:{id:'opp'+event},winner_id:'opp'+event,selection_id:selected,
                      projection:line+.5,market_publications:[p]};
                    return row;
                };
                const top=winner('top','top_daily',1.54,true);
                const value=winner('value','value',1.83,true);
                const aceRows=[
                  ace('mpt','a',12.5,1.75,26,true),
                  ace('hur','b',10.5,1.80,9,false),
                  ace('far','c',4.5,1.79,7,true),
                  ace('kar','d',7.5,1.72,7,false),
                  ace('pending1','e',6.5,1.7,null,null,false),
                  ace('pending2','f',5.5,1.7,null,null,false),
                  ace('pending3','g',7.5,1.7,null,null,false),
                ];
                // Real serving feed may lack a top-level ace market and have a
                // different winner_id. Settlements only retain signed publications.
                s.feed={account:{is_admin:false,status:'active',plan:'elite'},
                  entitlements:{result_categories:['top_daily','value','ace'],
                    daily_pick_count:9},daily_picks:[],
                  top_daily_picks:[top],value_picks:[value],
                  ace_picks:aceRows,prime_picks:[],doubles_picks:[],sg_picks:[],
                  results:[top,value,...aceRows.slice(0,4)],
                  member_result_rules:{elite:{
                    daily:{enabled:true,display_state:'active',visible_picks:'ALL'},
                    value:{enabled:true,display_state:'active',visible_picks:'ALL'},
                    ace:{enabled:true,display_state:'active',visible_picks:'ALL'},
                  }}};
                const filt={window:'today',bettingDay:true,category:'all',tour:'',surface:''};
                const eliteKeys=t.currentBettingDayPublishedKeys();
                const eliteRows=t.filteredResults(filt);
                const elite=t.settledPublishedEntries(eliteRows,'all',filt);
                const m=t.localResultMetrics(eliteRows,'all',filt);
                const fakeResult=ace('far','c',5.5,1.79,7,true);
                s.feed.results.push(fakeResult);
                const noWrongLine=t.settledPublishedEntries(t.filteredResults(filt),'all',filt)
                  .every(x=>!(x.publication.market_line===5.5&&x.row.event_id==='far'));
                s.feed.results.pop();
                // Administrative ELITE membership preview must match the
                // same cohort independently of the current display market.
                s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active'};
                const adminCohort=t.memberResultCohort('elite',day);
                const adminEntries=t.settledPublishedEntries(s.feed.results,'all',{...filt,membership:'elite'});
                // PRO and FREE never receive ELITE-only Aces rows from API.
                s.feed.account={is_admin:false,status:'active',plan:'pro'};
                s.feed.entitlements.result_categories=['top_daily','value'];
                s.feed.ace_picks=[];s.feed.results=[top,value];
                const pro=t.settledPublishedEntries(t.filteredResults(filt),'all',filt);
                s.feed.account={is_admin:false,status:'active',plan:'rookie'};
                s.feed.entitlements.result_categories=['top_daily'];
                s.feed.value_picks=[];s.feed.results=[top];
                const free=t.settledPublishedEntries(t.filteredResults(filt),'all',filt);
                return {eliteKeys:eliteKeys.size,elite:elite.length,
                  eliteWins:m.wins,eliteLosses:m.losses,
                  eliteProfit:Math.round(m.profit*100)/100,
                  adminCohort:adminCohort.size,admin:adminEntries.length,
                  pro:pro.length,free:free.length,noWrongLine,
                  eliteIds:elite.map(x=>x.row.event_id).sort()};
            }""".replace("b ratislava","bratislava"))
            assert result == {
                "eliteKeys":9,"elite":6,"eliteWins":4,"eliteLosses":2,
                "eliteProfit":1.91,"adminCohort":9,"admin":6,
                "pro":2,"free":1,"noWrongLine":True,
                "eliteIds":["far","hur","kar","mpt","top","value"]
            }, result
            assert not errors, errors
        finally:
            browser.close()


if __name__ == "__main__":
    main()
    print("All-tier Today published Results O/U identity: PASS")
