"""Betting-day Results filter contract: 06:00 Europe/Bratislava by default."""
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
            "  window.bettingDayTest={state,filteredResults,renderResultsFilters,resultsSummary,wireResultsFilters,bratislavaBettingDayKey,resultPublicationMatchesWindow};\n"
            + marker,
        )
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


PUB = {
    "section": "top_daily",
    "market": "match_winner",
    "issued_at": "2026-09-26T18:00:00Z",
    "selection": "Player A",
    "selection_id": "p1",
    "model_probability": .68,
    "odds": 1.60,
    "price_status": "priced",
    "result": {"status": "hit", "correct": True, "staked_units": 1, "profit_units": .60},
}


def main():
    with sync_playwright() as pw:
        executable = os.getenv("BLINQ_BROWSER") or browser_path()
        browser = (
            pw.chromium.launch(headless=True, executable_path=executable)
            if executable else pw.chromium.launch(headless=True)
        )
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route("**/*", route_request)
            page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
            page.wait_for_function("window.bettingDayTest && bettingDayTest.state.ui")
            initial = page.evaluate("() => bettingDayTest.state.resultsFilters.window")
            assert initial == "all", initial
            rows = [
                ("before", "2026-09-27T03:59:59Z"),
                ("start", "2026-09-27T04:00:00Z"),
                ("inside", "2026-09-28T03:59:59Z"),
                ("after", "2026-09-28T04:00:00Z"),
            ]
            page.evaluate(
                """({rows,pub}) => {
                    const t=bettingDayTest,s=t.state;
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelector('#appShell').hidden=false;
                    s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active'};
                    s.feed.results=rows.map(([event_id,scheduled_at])=>({
                      event_id,tour:'ATP',surface:'hard',scheduled_at,tournament:'T',
                      player1:{id:'p1',name:'A'},player2:{id:'p2',name:'B'},
                      market_publications:[structuredClone(pub)]
                    }));
                    s.resultsFilters={category:'all',tour:'',surface:'',window:'custom',
                      dateFrom:'2026-09-27',dateTo:'2026-09-27',bettingDay:true};
                    const host=document.querySelector('#routePanel');
                    host.hidden=false;host.innerHTML=t.renderResultsFilters()+t.resultsSummary();
                    t.wireResultsFilters();
                }""",
                {"rows": rows, "pub": PUB},
            )
            result = page.evaluate("""() => {
                const t=bettingDayTest,s=t.state;
                const betting=t.filteredResults().map(row=>row.event_id);
                const checked=document.querySelector('#resultsBettingDay')?.checked;
                const sample=[...document.querySelectorAll('.metric-card')].at(-1)?.textContent||'';
                document.querySelector('#resultsBettingDay').click();
                const midnight=t.filteredResults().map(row=>row.event_id);
                return {betting,midnight,checked,sample,state:s.resultsFilters.bettingDay};
            }""")
            assert result["betting"] == ["start", "inside"], result
            assert result["checked"] is True, result
            assert "2" in result["sample"], result
            # Chromium CI runs in UTC: disabling Betting day restores the old
            # browser-local midnight behavior.
            assert result["midnight"] == ["before", "start"], result
            assert result["state"] is False, result

            today = page.evaluate("""() => {
                const t=bettingDayTest,s=t.state;
                const day=t.bratislavaBettingDayKey(Date.now(),6);
                const [y,m,d]=day.split('-').map(Number);
                const prevDate=new Date(Date.UTC(y,m-1,d-1));
                const prev=`${prevDate.getUTCFullYear()}-${String(prevDate.getUTCMonth()+1).padStart(2,'0')}-${String(prevDate.getUTCDate()).padStart(2,'0')}`;
                const basePub=structuredClone(s.feed.results[0].market_publications[0]);
                const mk=(event_id,betting_day,scheduled_at=new Date().toISOString())=>({
                  event_id,tour:'ATP',surface:'hard',scheduled_at,tournament:'T',winner_id:'p1',
                  betting:{market:'match_winner',selection_id:'p1'},
                  player1:{id:'p1',name:'A'},player2:{id:'p2',name:'B'},
                  market_publications:[{...structuredClone(basePub),betting_day}]
                });
                const beforeSix=day+'T02:00:00Z';
                const current=mk('current-day',day);
                const runtimeCurrent=mk('runtime-current',day);
                delete runtimeCurrent.market_publications[0].issued_at;
                runtimeCurrent.market_publications[0].result={
                  status:'hit',correct:true,runtime_source:'match_status_snapshot'
                };
                const staleExplicit=mk('before-six-but-explicit-current',day,beforeSix);
                s.feed.entitlements={daily_pick_count:64};
                s.feed.top_daily_picks=[
                  structuredClone(current),structuredClone(runtimeCurrent),structuredClone(staleExplicit)
                ];
                s.feed.results=[current,runtimeCurrent,staleExplicit,mk('previous-day',prev)];
                s.resultsFilters={category:'all',tour:'',surface:'',window:'today',
                  dateFrom:'',dateTo:'',bettingDay:true};
                const host=document.querySelector('#routePanel');
                host.innerHTML=t.renderResultsFilters()+t.resultsSummary();
                const ids=t.filteredResults().map(row=>row.event_id);
                const sample=[...document.querySelectorAll('.metric-card')].at(-1)?.textContent||'';
                return {ids,sample,window:s.resultsFilters.window};
            }""")
            assert today["ids"] == ["current-day", "runtime-current"], today
            assert today["window"] == "today", today
            assert "2/64" in today["sample"], today

            # A settled published Result can outlive the current daily offer.
            # Admin sees it even if a refresh removed that offer card; non-admin
            # still requires the original authorized current-offer cohort.
            archive = page.evaluate("""() => {
              const t=bettingDayTest,s=t.state;
              const source=structuredClone(s.feed.results[0]);
              const archived=structuredClone(source);
              archived.event_id='archived-value';
              archived.market_publications[0].section='value';
              archived.runtime_result_overlay=true;
              archived.archive_source='verified_match_status_snapshot';
              archived.market_publications[0].result.runtime_source='match_status_snapshot';
              const unpublished=structuredClone(source);
              unpublished.event_id='unpublished';
              delete unpublished.market_publications[0].issued_at;
              unpublished.market_publications[0].result.runtime_source='';
              s.feed.results.push(archived,unpublished);
              const admin=t.filteredResults().map(row=>row.event_id);
              const adminValue=t.filteredResults({...s.resultsFilters,category:'value'})
                .map(row=>row.event_id);
              s.feed.account={is_admin:false,role:'rookie',plan:'rookie',status:'active'};
              const member=t.filteredResults().map(row=>row.event_id);
              return {admin,adminValue,member};
            }""")
            assert "archived-value" in archive["admin"], archive
            assert archive["adminValue"] == ["archived-value"], archive
            assert "archived-value" not in archive["member"], archive
            assert "unpublished" not in archive["admin"], archive

            page.evaluate("""() => {
              document.querySelectorAll('dialog[open]').forEach(d=>d.close());
              const t=bettingDayTest;
              t.state.resultsFilters={category:'all',tour:'',surface:'',window:'custom',dateFrom:'2026-09-27',dateTo:'2026-09-27',bettingDay:true};
              document.querySelector('#routePanel').innerHTML=t.renderResultsFilters()+t.resultsSummary();
              t.wireResultsFilters();
            }""")
            page.locator('#resultsDateRange').click()
            page.locator('#resultsRangeDialog [data-range-day="2026-09-26"]').click()
            page.locator('#resultsRangeDialog [data-range-day="2026-09-28"]').click()
            page.locator('#resultsRangeDialog [data-range-apply]').click()
            dates=page.evaluate('() => bettingDayTest.state.resultsFilters')
            assert dates['dateFrom']=='2026-09-26' and dates['dateTo']=='2026-09-28',dates
            page.locator('#resultsRangeDialog').wait_for(state='detached')
            assert page.locator('#resultsDateFrom').get_attribute('type')=='hidden'
            page.locator('#resultsDateRange').click()
            page.locator('#resultsRangeDialog [data-range-clear]').click()
            assert page.evaluate('bettingDayTest.state.resultsFilters.window')=='all'
            ranges=page.evaluate("""() => {
              const match=bettingDayTest.resultPublicationMatchesWindow;
              const now=Date.parse('2026-10-04T14:00:00Z');
              const run=(at,days,enabled,clock=now)=>match({scheduled_at:at},{},{window:String(days),bettingDay:enabled},clock);
              return {
                before:run('2026-10-04T03:59:59Z',1,true),
                start:run('2026-10-04T04:00:00Z',1,true),
                end:run('2026-10-05T04:00:00Z',1,true),
                rolling:run('2026-10-03T15:00:00Z',1,false),
                aligned:run('2026-10-03T15:00:00Z',1,true),
                threeStart:run('2026-10-02T04:00:00Z',3,true),
                threeBefore:run('2026-10-02T03:59:59Z',3,true),
                winterBefore:run('2026-10-25T04:59:59Z',1,true,Date.parse('2026-10-25T12:00:00Z')),
                winterStart:run('2026-10-25T05:00:00Z',1,true,Date.parse('2026-10-25T12:00:00Z'))
              };
            }""")
            assert ranges=={'before':False,'start':True,'end':False,'rolling':True,'aligned':False,'threeStart':True,'threeBefore':False,'winterBefore':False,'winterStart':True},ranges
            assert not errors, errors
            print("Results current betting-day cohort + 06:00 custom filter contract: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
