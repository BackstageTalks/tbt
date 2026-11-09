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
            "  window.bettingDayTest={state,filteredResults,renderResultsFilters,resultsSummary,todayPublishedPickCount,wireResultsFilters,renderRoute,bratislavaBettingDayKey,resultPublicationMatchesWindow,currentBettingDayPublishedKeys,memberResultCohort,settledPublishedEntries,renderResults,aceLeaderHintHtml,projectionOddsHtml};\n"
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
              const previousAccount=s.feed.account;
              s.feed.account={is_admin:false,role:'rookie',plan:'rookie',status:'active'};
              const member=t.filteredResults().map(row=>row.event_id);
              s.feed.account=previousAccount;
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
            # An empty Today selection must not silently display all time.
            empty_today=page.evaluate("""() => {
                const t=bettingDayTest,s=t.state;
                const settled=structuredClone(s.feed.results[0]);
                const prev=t.bratislavaBettingDayKey(Date.now()-2*86400000,6);
                settled.scheduled_at=prev+'T12:00:00Z';
                settled.market_publications[0].betting_day=prev;
                s.feed.results=[settled];
                s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active'};
                s.resultsFilters={category:'all',tour:'',surface:'',window:'today',
                    dateFrom:'',dateTo:'',bettingDay:true};
                s.route='results';
                t.renderRoute('results');
                const text=document.querySelector('#routePanel')?.textContent||'';
                return {period:s.resultsFilters.window,rows:t.filteredResults().length,
                    empty:text.includes('Pre zvolené filtre nie sú dostupné vyhodnotené predikcie.'),
                    selector:document.querySelector('#resultsWindow')?.value};
            }""")
            assert empty_today=={'period':'today','rows':0,'empty':True,'selector':'today'},empty_today

            # A membership selection must scope today's published denominator
            # to the member cohort, not the entire 50-80 pick daily offer.
            membership = page.evaluate("""() => {
                const t=bettingDayTest,s=t.state;
                const day=t.bratislavaBettingDayKey(Date.now(),6);
                const previous=t.bratislavaBettingDayKey(Date.now()-86400000,6);
                const row=(id,dayKey,section,correct,position,scheduled=dayKey+'T12:00:00Z')=>({
                  event_id:id,tour:'ATP',surface:'hard',scheduled_at:scheduled,
                  market_publications:[{
                    section,market:'match_winner',selection_id:'p1',
                    selection:'Player A',issued_at:dayKey+'T07:00:00Z',
                    betting_day:dayKey,offer_position:position,
                    odds:2,price_status:'priced',
                    result:correct===null?{}:{
                      correct,status:correct?'hit':'miss',staked_units:1,
                      profit_units:correct?1:-1
                    }
                  }]
                });
                s.feed={
                  account:{is_admin:true,role:'admin',plan:'admin'},
                  entitlements:{daily_pick_count:58},
                  member_result_rules:{
                    elite:{
                      daily:{enabled:true,display_state:'active',visible_picks:2,selection_mode:'first'},
                      prime:{enabled:true,display_state:'active',visible_picks:1,selection_mode:'first'}
                    },
                    pro:{
                      daily:{enabled:true,display_state:'active',visible_picks:1,selection_mode:'first'}
                    }
                  },
                  results:[
                    row('pending',day,'top_daily',null,1),
                    row('won',day,'top_daily',true,2),
                    row('not-allocated',day,'top_daily',true,3),
                    row('prime',day,'prime',false,1),
                    row('old',previous,'top_daily',true,1),
                    row('stale-timestamp',day,'top_daily',true,4,previous+'T12:00:00Z')
                  ]
                };
                s.feed.top_daily_picks=[{
                  ...s.feed.results[0],market:'match_winner',selection_id:'p1',
                  betting:{selection_id:'p1'},issued_at:day+'T07:00:00Z'
                }];
                s.ui.dashboard.daily_hub.tabs={};
                s.resultsFilters={
                  category:'all',tour:'',surface:'',window:'today',
                  dateFrom:'',dateTo:'',bettingDay:true,membership:'elite'
                };
                const eliteCount=t.todayPublishedPickCount('elite');
                const eliteHtml=t.resultsSummary();
                const sampleOf=html=>{
                  const host=document.createElement('div');
                  host.innerHTML=html;
                  return [...host.querySelectorAll('.metric-card strong')].at(-1)?.textContent.trim();
                };
                // Matching the current 06:00 betting day by date must not
                // drop the published ELITE denominator from Today.
                s.resultsFilters={...s.resultsFilters,window:'custom',
                  dateFrom:day,dateTo:day};
                const eliteCustomSample=sampleOf(t.resultsSummary());
                s.resultsFilters.dateFrom=previous;
                s.resultsFilters.dateTo=previous;
                const historicalSample=sampleOf(t.resultsSummary());
                s.resultsFilters.dateFrom=day;
                s.resultsFilters.dateTo=day;
                s.resultsFilters.bettingDay=false;
                const calendarSample=sampleOf(t.resultsSummary());
                s.resultsFilters={...s.resultsFilters,window:'today',
                  dateFrom:'',dateTo:'',bettingDay:true};
                const proCount=t.todayPublishedPickCount('pro');
                s.resultsFilters.membership='';
                const allCount=t.todayPublishedPickCount();
                const allHtml=t.resultsSummary();
                return {
                  eliteCount,proCount,allCount,
                  eliteCustomSample,historicalSample,calendarSample,
                  eliteFraction:eliteHtml.includes('2/3'),
                  eliteDescription:eliteHtml.includes('dnešných ELITE pickov'),
                  eliteNoGlobal:!eliteHtml.includes('2/58'),
                  allFraction:allHtml.includes('3/58')
                };
            }""")
            assert membership == {
                "eliteCount":3,"proCount":1,"allCount":58,
                "eliteCustomSample":"2/3","historicalSample":"1",
                "calendarSample":"2",
                "eliteFraction":True,"eliteDescription":True,
                "eliteNoGlobal":True,"allFraction":True
            },membership

            # Replay the complete issued morning cohort: 3 TOP, 1 VALUE,
            # 5 ACES. The superseding Aces O/U message was sent pre-match.
            # Both access filtering and the Admin membership previews must
            # use the same immutable 9 bets, not only the settled two winners.
            morning = page.evaluate("""() => {
                const t=bettingDayTest,s=t.state;
                const day=t.bratislavaBettingDayKey(Date.now(),6);
                const at=(hh,mm)=>day+'T'+hh+':'+mm+':00Z';
                const base=(event,section,market,id,position,scheduled,settled,odds=1.8,line=null,ace=false)=>{
                  const pub={
                    section,market,selection_id:id,selection:'Issued player',
                    issued_at:at(ace?'09':'05',ace?'27':'37'),
                    publication_status:'published',
                    betting_day:day,offer_position:position,
                    odds,price_status:ace?'priced_projection':'priced',
                    ...(ace?{projection_scope:'player',projection_metric:'aces',
                      price_contract:'player_total_ou',ou_side:'over',market_line:line}:{}),
                    result:settled===null?{}:{correct:settled,status:settled?'hit':'miss',
                      staked_units:1,profit_units:settled?odds-1:-1}
                  };
                  return {
                    event_id:event,scheduled_at:scheduled,tour:'ATP',surface:'hard',
                    player1:{id},player2:{id:'opp-'+event},
                    selection_id:id,winner_id:'opp-'+event,
                    betting:{selection_id:id},
                    // The production ace source row has no flat .market,
                    // but the issued result publication has all O/U fields.
                    ...(ace?{}:{market:'match_winner'}),
                    market_publications:[pub]
                  };
                };
                const rows=[
                  base('17456690','top_daily','match_winner','307383',1,at('21','20'),null,1.549451),
                  base('17471474','top_daily','match_winner','199488',2,at('19','55'),null,1.510204),
                  base('17467283','top_daily','match_winner','52229',3,at('11','30'),true,1.540541),
                  base('17470634','value','match_winner','409907',1,at('17','00'),true,1.833333),
                  base('17468525','ace','aces','289146',1,at('11','10'),true,1.75,12.5,true),
                  base('17449526','ace','aces','158896',2,at('10','00'),false,1.80,10.5,true),
                  base('17456687','ace','aces','372310',3,at('21','00'),null,1.60,6.5,true),
                  base('17467964','ace','aces','270414',4,at('13','00'),true,1.79,4.5,true),
                  base('17457727','ace','aces','341853',5,at('15','00'),false,1.72,7.5,true)
                ];
                const archived=structuredClone(rows);
                // Archive contract carries parser metadata missing from the
                // original flat daily row. A difference must not hide results.
                const offer=structuredClone(rows).map(r=>{
                  const copy={...r};
                  delete copy.market_publications;
                  delete copy.market;
                  return copy;
                });
                s.feed={
                  account:{is_admin:true,role:'admin',plan:'admin',status:'active'},
                  entitlements:{daily_pick_count:9},
                  member_result_rules:{
                    elite:{
                      daily:{enabled:true,display_state:'active',visible_picks:3,selection_mode:'first'},
                      value:{enabled:true,display_state:'active',visible_picks:1,selection_mode:'first'},
                      ace:{enabled:true,display_state:'active',visible_picks:5,selection_mode:'first'}
                    },
                    pro:{
                      daily:{enabled:true,display_state:'active',visible_picks:2,selection_mode:'first'},
                      value:{enabled:true,display_state:'active',visible_picks:1,selection_mode:'first'},
                      ace:{enabled:true,display_state:'active',visible_picks:2,selection_mode:'first'}
                    },
                    rookie:{
                      daily:{enabled:true,display_state:'active',visible_picks:1,selection_mode:'stable_random'},
                      value:{enabled:true,display_state:'active',visible_picks:1,selection_mode:'stable_random'},
                      ace:{enabled:true,display_state:'active',visible_picks:0}
                    },
                    legend:{
                      daily:{enabled:true,display_state:'active',visible_picks:'ALL',selection_mode:'first'},
                      value:{enabled:true,display_state:'active',visible_picks:'ALL',selection_mode:'first'},
                      ace:{enabled:true,display_state:'active',visible_picks:'ALL',selection_mode:'first'}
                    },
                    goat:{
                      daily:{enabled:true,display_state:'active',visible_picks:'ALL',selection_mode:'first'},
                      value:{enabled:true,display_state:'active',visible_picks:'ALL',selection_mode:'first'},
                      ace:{enabled:true,display_state:'active',visible_picks:'ALL',selection_mode:'first'}
                    }
                  },
                  results:archived,
                  top_daily_picks:offer.slice(0,3),
                  daily_picks:offer.slice(0,3),
                  value_picks:offer.slice(3,4),
                  ace_picks:offer.slice(4)
                };
                s.resultsFilters={category:'all',tour:'',surface:'',window:'today',
                  dateFrom:'',dateTo:'',bettingDay:true,membership:'elite'};
                const dayKeys=t.currentBettingDayPublishedKeys(Date.now());
                const eliteKeys=t.memberResultCohort('elite',day);
                const elite=t.resultsSummary();
                const settled=t.settledPublishedEntries(t.filteredResults(),'all',s.resultsFilters);
                const preview=t.renderResults();
                const aceExample={projection_metric:'aces',aces_superiority_hint:'Farjat'};
                const leader={id:'270414',name:'Farjat'},opponent={id:'206594',name:'Opponent'};
                // Same Admin → Zobrazenie rule must drive the ELITE result tier,
                // including a newly enabled settled Doubles category.
                const doubles=base('doubles-regression','doubles','match_winner','doubles-p1',1,at('16','00'),true);
                const doublesOffer=structuredClone(doubles);
                delete doublesOffer.market_publications;
                s.feed.results.push(doubles);
                s.feed.doubles_picks=[doublesOffer];
                const doublesRule={enabled:true,display_state:'hidden',visible_picks:0,selection_mode:'first'};
                s.feed.member_result_rules.elite.doubles=doublesRule;
                const beforeDoubles=t.settledPublishedEntries(t.filteredResults(),'all',s.resultsFilters).length;
                doublesRule.display_state='active';doublesRule.visible_picks=1;
                const afterDoubles=t.settledPublishedEntries(t.filteredResults(),'all',s.resultsFilters).length;
                doublesRule.row_overrides={'1':'hidden'};
                const hiddenOverride=t.settledPublishedEntries(t.filteredResults(),'all',s.resultsFilters).length;
                doublesRule.row_overrides={};doublesRule.display_state='hidden';
                const afterDisable=t.settledPublishedEntries(t.filteredResults(),'all',s.resultsFilters).length;
                // SETS and GAMES are independent Admin tabs, even though their
                // published market rows share the legacy sg_picks source.
                const sets=base('sets-regression','sets','sets','sets-p1',1,at('16','30'),true);
                const setsOffer=structuredClone(sets);delete setsOffer.market_publications;
                setsOffer.market='sets';
                s.feed.sg_picks=[setsOffer];s.feed.results.push(sets);
                const setsRule={enabled:true,display_state:'hidden',visible_picks:0,selection_mode:'first'};
                s.feed.member_result_rules.elite.sets=setsRule;
                s.feed.member_result_rules.elite.sg={enabled:false,display_state:'hidden',visible_picks:0,selection_mode:'first'};
                const beforeSets=t.settledPublishedEntries(t.filteredResults(),'all',s.resultsFilters).length;
                setsRule.display_state='active';setsRule.visible_picks=1;
                const afterSets=t.settledPublishedEntries(t.filteredResults(),'all',s.resultsFilters).length;
                const result={
                  published:dayKeys.size,
                  matched:rows.filter(r=>dayKeys.has([r.event_id,
                    r.market_publications[0].market,r.market_publications[0].selection_id].join('::').toLowerCase())).length,
                  eliteCohort:eliteKeys.size,
                  eliteSummary:elite.includes('6/9'),
                  settledCount:settled.length,
                  resultRows:(preview.match(/class="results-card-row/g)||[]).length,
                  noPendingEntries:!preview.includes('ČAKÁ NA OVERENIE'),
                  aceLeaderMarker:t.aceLeaderHintHtml(aceExample,leader,'Farjat').includes('ace-leader-ball'),
                  wrongAceMarker:!!t.aceLeaderHintHtml(aceExample,opponent,'Opponent'),
                  nonAceMarker:!!t.aceLeaderHintHtml({...aceExample,projection_metric:'games'},leader,'Farjat'),
                  beforeDoubles,afterDoubles,hiddenOverride,afterDisable,
                  beforeSets,afterSets,
                  proCohort:t.memberResultCohort('pro',day).size,
                  freeCohort:t.memberResultCohort('rookie',day).size,
                  legendCohort:t.memberResultCohort('legend',day).size,
                  goatCohort:t.memberResultCohort('goat',day).size
                };
                return result;
            }""")
            assert morning == {
                "published": 9, "matched": 9, "eliteCohort": 9,
                "eliteSummary": True, "settledCount": 6, "resultRows": 6,
                "noPendingEntries": True, "aceLeaderMarker": True,
                "wrongAceMarker": False, "nonAceMarker": False,
                "beforeDoubles": 6, "afterDoubles": 7,
                "hiddenOverride": 6, "afterDisable": 6,
                "beforeSets": 6, "afterSets": 7,
                "proCohort": 5, "freeCohort": 2,
                "legendCohort": 9, "goatCohort": 9
            }, morning


            # Current Admin ELITE: TOP first five, all VALUE/ACES/MOST ACES,
            # but no ACCA/DF/SETS/GAMES/DOUBLES. An excluded ACCA publication
            # sharing a TOP identity must not borrow its membership grant.
            current_admin = page.evaluate("""() => {
                const t=bettingDayTest,s=t.state,day=t.bratislavaBettingDayKey(Date.now(),6);
                const when=day+'T12:00:00Z',issued=day+'T07:00:00Z';
                const make=(id,section,market,pos,outcome='win')=>{
                  const pub={
                    section,market,selection_id:'player-'+id,selection:'Player '+id,
                    issued_at:issued,publication_status:'published',betting_day:day,
                    offer_position:pos,odds:1.70,
                    price_status:market==='match_winner'?'priced':'priced_projection',
                    result:outcome==='pending'?{}:{
                      correct:outcome==='win',status:outcome==='win'?'hit':'miss',
                      staked_units:1,profit_units:outcome==='win'?.7:-1}
                  };
                  return {event_id:id,scheduled_at:when,tour:'ATP',surface:'hard',
                    player1:{id:'player-'+id},player2:{id:'opp-'+id},
                    market_publications:[pub]};
                };
                const top=Array.from({length:6},(_,i)=>make('top'+i,'top_daily','match_winner',i+1,i===3?'pending':'win'));
                const value=[make('value1','value','match_winner',2)];
                // Same frozen winner is also issued into VALUE; it is ONE wager.
                top[0].market_publications.push({...structuredClone(top[0].market_publications[0]),
                  section:'value',offer_position:1});
                const aces=Array.from({length:3},(_,i)=>make('ace'+i,'ace','aces',i+1,i===1?'pending':'win'));
                const more=Array.from({length:2},(_,i)=>make('most'+i,'ace_winner','most_aces',i+1));
                const acca=Array.from({length:30},(_,i)=>make('acca'+i,'prime','match_winner',i+1));
                // Identity collision: TOP and hidden ACCA are different Admin tabs.
                top[0].market_publications.push({...structuredClone(top[0].market_publications[0]),
                  section:'prime',offer_position:1});
                const df=[make('df-hidden','double_faults','double_faults',1)];
                const sets=[make('sets-hidden','sets','sets',1)];
                const games=[make('games-hidden','games','games',1)];
                const doubles=[make('doubles-hidden','doubles','match_winner',1)];
                const unissued=make('unissued-top','top_daily','match_winner',7);
                delete unissued.market_publications[0].issued_at;
                // ESÁ bridge inherits a valid issue timestamp, but VIAC ES
                // was never independently issued; it must NOT count in sample.
                const bridge={...structuredClone(aces[0]),event_id:'bridge-leader',
                  market:'most_aces',price_status:'projection_only',
                  ace_winner_issued:false,issued_at:issued,
                  selection_id:'player-bridge-leader',market_publications:[]};
                const active=(limit)=>({enabled:true,display_state:'active',
                  visible_picks:limit,selection_mode:'first',row_overrides:{}});
                const hidden=()=>({enabled:true,display_state:'blurred',
                  visible_picks:0,selection_mode:'first',row_overrides:{}});
                s.feed={account:{is_admin:true,role:'admin',plan:'admin',status:'active'},
                  entitlements:{daily_pick_count:62},
                  member_result_rules:{elite:{
                    daily:active(5),value:active('ALL'),ace:active('ALL'),
                    ace_winner:active('ALL'),prime:hidden(),double_faults:hidden(),
                    sets:hidden(),games:hidden(),doubles:hidden()}},
                  results:[...top,...value,...aces,...more,...acca,...df,...sets,...games,...doubles],
                  daily_picks:top,top_daily_picks:[...top,unissued],
                  value_picks:[top[0],...value],prime_picks:acca,
                  ace_picks:[...aces,...more,...df,bridge],sg_picks:[...sets,...games],
                  doubles_picks:doubles};
                s.resultsFilters={category:'all',tour:'',surface:'',window:'today',
                  bettingDay:true,membership:'elite'};
                const disabled=['prime','double_faults','sets','games','doubles'];
                const activeIds=t.settledPublishedEntries(t.filteredResults(),'all',s.resultsFilters)
                  .map(entry=>entry.row.event_id);
                const total=t.todayPublishedPickCount('elite');
                const summary=t.resultsSummary();
                const excluded={};
                for(const category of disabled){
                  const f={...s.resultsFilters,category};
                  excluded[category]=t.settledPublishedEntries(t.filteredResults(f),category,f).length;
                }
                const primeOverlappingTop=t.settledPublishedEntries(
                  t.filteredResults({...s.resultsFilters,category:'prime'}),'prime',
                  {...s.resultsFilters,category:'prime'}).length;
                // Simulate a newer, server-authoritative Admin publish:
                // all counts must immediately follow the new category/limit
                // without any hard-coded ELITE market list.
                const refresh=()=>({
                  total:t.todayPublishedPickCount('elite'),
                  settled:t.settledPublishedEntries(t.filteredResults(),'all',s.resultsFilters).length
                });
                s.feed.member_result_rules.elite.prime=active('ALL');
                const withPrime=refresh();
                s.feed.member_result_rules.elite.prime=hidden();
                s.feed.member_result_rules.elite.games=active('ALL');
                const withGames=refresh();
                s.feed.member_result_rules.elite.ace_winner=hidden();
                const withoutMoreAces=refresh();
                s.feed.member_result_rules.elite.sets=active('ALL');
                const withSets=refresh();
                s.feed.member_result_rules.elite.daily=active(6);
                const withSixTop=refresh();
                return {total,settled:activeIds.length,activeIds,excluded,
                  primeOverlappingTop,sample:summary.includes('9/11'),
                  nonMemberTotal:s.feed.entitlements.daily_pick_count,
                  withPrime,withGames,withoutMoreAces,withSets,withSixTop};
            }""")
            assert current_admin["total"] == 11,current_admin
            assert current_admin["settled"] == 9,current_admin
            assert current_admin["sample"],current_admin
            assert current_admin["nonMemberTotal"] == 62,current_admin
            assert all(n == 0 for n in current_admin["excluded"].values()),current_admin
            assert current_admin["primeOverlappingTop"] == 0,current_admin
            assert current_admin["withPrime"] == {"total":41,"settled":39},current_admin
            assert current_admin["withGames"] == {"total":12,"settled":10},current_admin
            assert current_admin["withoutMoreAces"] == {"total":10,"settled":8},current_admin
            assert current_admin["withSets"] == {"total":11,"settled":9},current_admin
            assert current_admin["withSixTop"] == {"total":12,"settled":10},current_admin
            assert 'top5' not in current_admin["activeIds"],current_admin
            assert 'unissued-top' not in current_admin["activeIds"],current_admin
            print("ELITE current Admin category caps, hidden categories, duplicate and issuance scope: PASS")

            # Browser: Aces leader icon independent of its O/U contract.
            # A parent result row may have stale match-level hints; the issued
            # publication and exact two final counts remain authoritative.
            ace_outcomes = page.evaluate("""() => {
                const t=bettingDayTest,s=t.state;
                const savedFeed=s.feed,savedFilters=s.resultsFilters,savedPage=s.resultsPage;
                const mk=(id,actual,opponent,correct,market='aces',status=correct?'hit':'miss')=>({
                    event_id:id,tour:'ATP',surface:'hard',
                    scheduled_at:'2026-11-02T15:00:00Z',tournament:'Test',
                    market:'match_winner',aces_superiority_hint:'Musetti',
                    player1:{id:'p1',name:'Hurkacz'},player2:{id:'p2',name:'Musetti'},
                    market_publications:[{
                        section:market==='aces'?'ace':'double_faults',
                        market,projection_metric:market,projection_scope:'player',
                        selection:'CASE-'+id,selection_id:'p1',
                        projection_subject:'Hurkacz',projection:11.3,
                        opponent_projection:6.2,
                        price_contract:'player_total_ou',ou_side:'over',
                        market_line:10.5,odds:1.8,price_status:'priced_projection',
                        issued_at:'2026-11-02T08:00:00Z',publication_status:'published',
                        result:{status,correct,actual_count:actual,
                                opponent_actual_count:opponent,
                                staked_units:1,profit_units:correct?0.8:-1}
                    }]
                });
                s.feed={account:{is_admin:true,role:'admin',plan:'admin'},
                  results:[
                    mk('hit-leader-loss-ou',9,5,false),
                    mk('miss-leader-win-ou',5,9,true),
                    mk('tie',5,5,false),
                    mk('missing',9,null,false),
                    mk('not-aces',9,5,false,'double_faults')
                  ]};
                s.resultsFilters={category:'all',tour:'',surface:'',window:'all',
                    dateFrom:'',dateTo:'',bettingDay:true};
                const body=document.createElement('div');
                body.innerHTML=t.renderResults();
                const rows=[...body.querySelectorAll('tr.results-card-row')];
                const outcomeRows=Object.fromEntries(rows.map(row=>{
                    const label=row.querySelector('.result-prediction strong')?.textContent.trim().split(' · ')[0];
                    return [label,{
                      balls:row.querySelectorAll('.ace-leader-ball').length,
                      win:!!row.querySelector('.result-status b.correct'),
                      loss:!!row.querySelector('.result-status b.wrong'),
                      units:row.querySelector('.result-units')?.textContent.trim()
                    }];
                }));
                s.feed=savedFeed;s.resultsFilters=savedFilters;s.resultsPage=savedPage;
                return outcomeRows;
            }""")
            assert ace_outcomes == {
                "CASE-hit-leader-loss-ou": {"balls":1,"win":False,"loss":True,"units":"-1.00u"},
                "CASE-miss-leader-win-ou": {"balls":0,"win":True,"loss":False,"units":"+0.80u"},
                "CASE-tie": {"balls":0,"win":False,"loss":True,"units":"-1.00u"},
                "CASE-missing": {"balls":0,"win":False,"loss":True,"units":"-1.00u"},
                "CASE-not-aces": {"balls":0,"win":False,"loss":True,"units":"-1.00u"}
            }, ace_outcomes

            # ALL means no second membership-cohort restriction in Admin.
            # Some settled Aces from the verified ledger lack legacy offer IDs,
            # but they must not disappear from an unrestricted ELITE preview.
            all_aces = page.evaluate("""() => {
              const t=bettingDayTest,s=t.state;
              const day=t.bratislavaBettingDayKey(Date.now(),6);
              const scheduled=new Date().toISOString();
              const mk=(n,correct)=>{
                const selection=n===1?'player-1':'';
                return {
                  event_id:'ace-'+n,scheduled_at:scheduled,tour:'ATP',
                  player1:{id:'player-'+n,name:'Player '+n},
                  player2:{id:'opponent-'+n,name:'Opponent '+n},
                  market_publications:[{
                    section:'ace',market:'aces',selection_id:selection,
                    publication_key:'issued-ace-'+n,
                    publication_status:'published',issued_at:scheduled,
                    betting_day:day,price_status:'priced_projection',odds:1.74,
                    result:{status:correct?'hit':'miss',correct,
                      staked_units:1,profit_units:correct?.74:-1}
                  }]
                };
              };
              s.previewPlan=null;
              s.feed={
                account:{is_admin:true,role:'admin',plan:'admin',status:'active'},
                entitlements:{result_categories:['ace'],daily_pick_count:3},
                member_result_rules:{
                  elite:{ace:{enabled:true,display_state:'active',
                    visible_picks:'ALL',selection_mode:'first',row_overrides:{}}},
                  pro:{ace:{enabled:true,display_state:'active',
                    visible_picks:1,selection_mode:'first',row_overrides:{}}}
                },
                ace_picks:[],results:[mk(1,false),mk(2,true),mk(3,true)]
              };
              const original=JSON.stringify(s.feed.results);
              s.resultsFilters={category:'ace',tour:'',surface:'',
                window:'today',dateFrom:'',dateTo:'',bettingDay:true,membership:''};
              const count=()=>t.settledPublishedEntries(t.filteredResults(),
                'ace',s.resultsFilters).length;
              const all=count();
              s.resultsFilters.membership='elite';
              const elite=count();
              const eliteRecord=t.resultsSummary().includes('2-1');
              s.resultsFilters.membership='pro';
              const pro=count();
              s.resultsFilters.membership='elite';
              s.feed.member_result_rules.elite.ace.row_overrides={'1':'hidden'};
              const overridden=count();
              s.feed.member_result_rules.elite.ace.row_overrides={};
              s.feed.member_result_rules.elite.ace.enabled=false;
              const disabled=count();
              return {all,elite,eliteRecord,pro,overridden,disabled,
                ledgerUnchanged:original===JSON.stringify(s.feed.results)};
            }""")
            assert all_aces == {
                "all": 3, "elite": 3, "eliteRecord": True,
                "pro": 1, "overridden": 0, "disabled": 0,
                "ledgerUnchanged": True,
            }, all_aces

            # Viac Es displays only the numeric frozen BlinQ price in the
            # offer; removing the subtitle must not alter odds provenance.
            no_label = page.evaluate("""() => {
              const row={
                event_id:'most-aces-1',market:'most_aces',
                price_contract:'player_superiority',
                price_status:'priced_projection',
                odds_source:'blinq_statistical',
                price_basis:'blinq_user_most_aces_confidence_band_v1',
                odds_contract_version:'most_aces_local_statistical_v1',
                projection_model:'ace-count-projection-v4',
                selection_id:'p1',player1:{id:'p1'},player2:{id:'p2'},
                scheduled_at:'2026-11-10T12:00:00Z',
                projection_confidence:0.93,projection:7,
                opponent_projection:4,odds:1.50
              };
              const sourceBefore=JSON.stringify(row);
              const html=bettingDayTest.projectionOddsHtml(row);
              const el=document.createElement('div');
              el.innerHTML=html;
              return {
                number:el.querySelector('.hub-number-stack strong')?.textContent,
                subtitle:el.querySelector('.hub-number-stack small')?.textContent||'',
                unchanged:sourceBefore===JSON.stringify(row),
              };
            }""")
            assert no_label == {'number':'1.50','subtitle':'','unchanged':True}, no_label

            assert not errors, errors
            print("Results current betting-day cohort + 06:00 custom filter contract: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
