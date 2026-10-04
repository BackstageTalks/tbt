"""Admin membership cohort is selected before outcome and UI filters."""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path

def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source=(WEB/"app.js").read_text(encoding="utf-8")
        source=source.replace("  boot();", "  window.memberTest={state,memberResultCohort,settledPublishedEntries,localResultMetrics,renderResultsFilters,wireResultsFilters};\n  boot();")
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
            print("Admin membership cohort, pending slots, per-day limits and ROI: PASS")
        finally: browser.close()
if __name__=="__main__":main()

