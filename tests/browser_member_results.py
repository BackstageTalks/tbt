"""Admin membership cohort is selected before outcome and UI filters."""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path

def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source=(WEB/"app.js").read_text(encoding="utf-8")
        source=source.replace("  boot();", "  window.memberTest={state,memberResultCohort,settledPublishedEntries,localResultMetrics,renderResultsFilters,renderResults,resultsSummary,wireResultsFilters,todayPublishedPickCount,effectiveMemberResultRule,bratislavaBettingDayKey};\n  boot();")
        route.fulfill(content_type="application/javascript",body=source)
    else: static_route(route)

def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=os.getenv("BLINQ_BROWSER") or browser_path())
        try:
            page=browser.new_page(viewport={"width":390,"height":844})
            errors=[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.route("**/*",route_request)
            page.goto(ORIGIN)
            page.wait_for_function("window.memberTest")
            result=page.evaluate("""() => {
              const t=memberTest;
              const row=(id,day,pos,correct,section='top_daily')=>({event_id:id,scheduled_at:day+'T12:00:00Z',tour:pos===1?'ATP':'WTA',market_publications:[{section,market:'match_winner',selection_id:'p1',selection:'A',issued_at:day+'T07:00:00Z',betting_day:day,offer_position:pos,odds:2,price_status:'priced',result:correct===null?{}:{correct,staked_units:1,profit_units:correct?1:-1}}]});
              t.state.feed={account:{is_admin:true},results:[row('pending','2026-10-01',1,null),row('loss','2026-10-01',2,false),row('winner','2026-10-01',3,true),row('next-day','2026-10-02',1,true),row('prime','2026-10-01',1,true,'prime')],member_result_rules:{elite:{daily:{enabled:true,display_state:'active',visible_picks:2,selection_mode:'first'},prime:{enabled:true,display_state:'active',visible_picks:1,selection_mode:'first'}}}};
              const filters={membership:'elite',window:'all'};
              const selected=t.settledPublishedEntries(t.state.feed.results,'all',filters).map(x=>x.row.event_id).sort();
              const limited=t.settledPublishedEntries(t.state.feed.results.filter(x=>x.tour==='WTA'),'all',filters).map(x=>x.row.event_id);
              const m=t.localResultMetrics(t.state.feed.results,'all',filters);
              const all=t.settledPublishedEntries(t.state.feed.results,'all',{window:'all'}).length;
              const html=t.renderResultsFilters();
              // Simulate the explicit Results category entitlements returned by the API.
              t.state.feed.entitlements={result_categories:['top_daily','prime']};
              t.state.feed.account={is_admin:false};
              const hidden=!t.renderResultsFilters().includes('resultsMembership');
              const regular=t.settledPublishedEntries(t.state.feed.results,'all',filters).length;
              return {selected,limited,roi:m.roi,profit:m.profit,all,hidden,regular,controls:html.includes('resultsMembership')};
            }""")
            assert result=={"selected":["loss","next-day","prime"],"limited":["loss"],"roi":1/3,"profit":1,"all":4,"hidden":True,"regular":4,"controls":True},result
            assert not errors,errors
            combined=page.evaluate("""() => {
              const t=memberTest;
              const rows=t.state.feed.results;
              const top=t.settledPublishedEntries(rows,'top_daily',{window:'all'});
              const prime=t.settledPublishedEntries(rows,'prime',{window:'all'});
              const multi=t.settledPublishedEntries(rows,'top_daily,prime',{window:'all'});
              const html=t.renderResultsFilters();
              return {count:multi.length,expected:top.length+prime.length,checkboxes:html.includes('data-result-category')};
            }""")
            assert combined['count']==combined['expected'] and combined['checkboxes'],combined
            # Regression: "All published" is a category, not ALL membership.
            # A missing ELITE rules payload must never masquerade as 0-0.
            diagnostics=page.evaluate("""() => {
              const t=memberTest,s=t.state;
              s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active'};
              s.resultsFilters={category:'all',tour:'',surface:'',window:'all',
                bettingDay:true,membership:'elite'};
              const label=t.renderResultsFilters().match(/results-mobile-filter-current">([^<]*)</)?.[1]||'';
              const baseline=t.settledPublishedEntries(s.feed.results,'all',
                {...s.resultsFilters,membership:''}).length;
              s.feed.member_result_rules={};
              const missing=t.renderResults();
              const record=t.resultsSummary();
              s.feed.member_result_rules={elite:{
                daily:{enabled:false,display_state:'hidden',visible_picks:0},
                prime:{enabled:false,display_state:'hidden',visible_picks:0}}};
              const ruledOut=t.renderResults();
              const original=s.feed.results;
              s.feed.results=[];
              s.resultsFilters.window='today';
              const unsettled=t.renderResults();
              s.feed.results=original;
              s.feed.results_archive_unavailable=true;
              const unavailable=t.renderResults();
              return {label,baseline,missing,record,ruledOut,unsettled,unavailable};
            }""")
            assert 'ELITE' in diagnostics['label'],diagnostics
            assert diagnostics['baseline']==4,diagnostics
            assert 'Pravidlá' in diagnostics['missing'],diagnostics
            assert '>—<' in diagnostics['record'],diagnostics
            assert '4 vyhodnotených' in diagnostics['ruledOut'],diagnostics
            assert '06:00–06:00' in diagnostics['unsettled'],diagnostics
            assert 'Archív' in diagnostics['unavailable'],diagnostics
            assert not errors,errors
            # Real members must get their personal Admin-authorized denominator,
            # not the global 62-match total exposed to the dashboard.
            member_total=page.evaluate("""() => {
              const t=memberTest,s=t.state;
              s.feed={
                account:{is_admin:false,role:'user',plan:'pro',status:'active'},
                entitlements:{daily_pick_count:62,member_daily_pick_count:2,
                  result_categories:['top_daily']},
                results:[]
              };
              s.resultsFilters={category:'all',tour:'',surface:'',
                window:'today',bettingDay:true};
              return {count:t.todayPublishedPickCount(),
                sample:t.resultsSummary().includes('0/2')};
            }""")
            assert member_total == {'count':2,'sample':True},member_total
            narrowed=page.evaluate("""() => {
              const t=memberTest,s=t.state,day=t.bratislavaBettingDayKey(Date.now(),6);
              const make=(i,market)=>({event_id:market+'-'+i,scheduled_at:day+'T12:00:00Z',
                market_publications:[{section:market==='most_aces'?'ace_winner':'top_daily',
                  market,selection_id:'p1',issued_at:day+'T07:00:00Z',betting_day:day,
                  price_status:'priced',odds:1.8,result:{correct:true,profit_units:0.8,staked_units:1}}]});
              const data=[...Array.from({length:9},(_,i)=>make(i,'match_winner')),
                ...Array.from({length:53},(_,i)=>make(i,'most_aces'))];
              const rule={enabled:true,display_state:'active',visible_picks:'ALL',row_overrides:{}};
              s.feed={account:{is_admin:true,plan:'admin'},results:data,
                member_result_rules:Object.fromEntries(['elite','legend','goat'].map(p=>[p,{daily:rule,ace_winner:rule}]))};
              s.ui={dashboard:{daily_hub:{tabs:{
                daily:{enabled:true,plans:{elite:{visible_rows:'ALL',tab_enabled:true},
                  legend:{visible_rows:'ALL'},goat:{visible_rows:'ALL'}}},
                ace_winner:{enabled:true,plans:{elite:{tab_enabled:false,visible_rows:0,display_state:'hidden'},
                  legend:{visible_rows:'ALL'},goat:{visible_rows:'ALL'}}}
              }}}};
              const counts=Object.fromEntries(['elite','legend','goat'].map(p=>[p,t.todayPublishedPickCount(p)]));
              const elite=t.settledPublishedEntries(data,'all',{window:'all',membership:'elite'});
              return {counts,elite:elite.length,aceInElite:elite.some(x=>x.publication.market==='most_aces')};
            }""")
            assert narrowed=={'counts':{'elite':9,'legend':62,'goat':62},'elite':9,'aceInElite':False},narrowed
            print("Admin membership cohort, pending slots, mobile scope and empty-state diagnostics: PASS")
        finally: browser.close()
if __name__=="__main__":main()

