"""Mobile BlinQ geometry gate for real Chromium (no network or paid API).

Reproduces 320-900px Results filters, KPIs and populated result cards, plus
long tournament names, mobile header and fixed navigation. Exercises desktop
to make sure its horizontally scrollable results table remains unchanged.
"""
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
            "  window.mobileGeometry={state,renderResultsFilters,resultsSummary,"
            "renderResults,renderInsightBell};\n" + marker,
        )
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


def main():
    widths = (320, 360, 390, 430, 768, 900, 1024, 1440)
    with sync_playwright() as pw:
        executable = os.getenv("BLINQ_BROWSER") or browser_path()
        browser = (
            pw.chromium.launch(headless=True, executable_path=executable)
            if executable else pw.chromium.launch(headless=True)
        )
        try:
            for width in widths:
                page = browser.new_page(viewport={"width": width, "height": 820})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.mobileGeometry && mobileGeometry.state.ui")
                page.evaluate("""() => {
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelectorAll('dialog[open]').forEach(el=>el.close());
                    document.querySelector('#appShell').hidden=false;
                    const t=mobileGeometry,s=t.state;
                    s.route='results';
                    s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active'};
                    s.ui.notifications={...(s.ui.notifications||{}),enabled:true};
                    s.resultsFilters={
                      category:'all',tour:'',surface:'',window:'all',dateFrom:'',dateTo:''
                    };
                    s.resultsPage=0;s.resultsPageSize=50;
                    s.feed.results=Array.from({length:7},(_,i)=>({
                      event_id:'long-tournament-'+i,tour:i%2?'WTA':'ATP',surface:'clay',
                      scheduled_at:'2026-09-27T14:00:00Z',
                      tournament:'ITF M25 Sharm El Sheikh 4, Egypt, Qualification Round 1',
                      tournament_city:'Sharm El Sheikh',
                      player1:{id:'p1-'+i,name:'Alejandro Fernandez de la Cruz',
                        country_code:'ESP'},
                      player2:{id:'p2-'+i,name:'Maximiliano Alessandro Dimitrov',
                        country_code:'BUL'},
                      market_publications:[{
                        section:i%2?'games':'top_daily',
                        market:i%2?'games':'match_winner',
                        issued_at:'2026-09-26T17:00:00Z',
                        selection:i%2?'Over 22.5 Games':'Alejandro Fernandez de la Cruz',
                        selection_id:i%2?'games-over':'p1-'+i,
                        model_probability:.65,odds:1.7,
                        price_status:i%2?'priced_projection':'priced',
                        result:{status:'hit',correct:true,
                          staked_units:1,profit_units:.7,
                          ...(i%2?{actual_count:25,projection:23.4}:{})}
                      }]
                    }));
                    document.body.classList.remove('blinq-home','blinq-admin');
                    document.body.classList.add('blinq-route');
                    document.querySelector('#routePanel').hidden=false;
                    document.querySelector('#routePanel').innerHTML=
                      t.renderResultsFilters()+t.resultsSummary()+t.renderResults();
                    window.BlinqUI.prepareRoute(document.querySelector('#routePanel'));
                    document.querySelector('#profileName').textContent='@BackstageTalks';
                    document.querySelector('#profileRegisteredEmail').textContent='long-account-email@example.org';
                    const projects=document.querySelector('#projectGroupBar');
                    projects.hidden=false;
                    projects.innerHTML='<button class="project-group-chip is-purple is-active" type="button"><span>◆</span><strong>Platba PO</strong></button>';
                    document.querySelector('#insightShortcut').hidden=false;
                    document.querySelector('#topUpgradeButton').hidden=false;
                    t.renderInsightBell();
                }""")
                page.wait_for_selector("#routePanel .results-table tbody tr")
                report = page.evaluate("""() => {
                    const css=s=>document.querySelector(s);
                    const rect=e=>{const r=e.getBoundingClientRect();
                      return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width};
                    };
                    const between=(a,b)=>Math.min(a.right,b.right)-Math.max(a.left,b.left);
                    const labels=[...document.querySelectorAll('.results-filter-field')].map(rect);
                    const kpis=[...document.querySelectorAll('.metric-card')].map(rect);
                    const table=css('.results-table'),wrap=css('.results-table-wrap');
                    const first=css('.results-table tbody tr');
                    const tournament=css('.results-table tbody tr .tournament-identity-copy>strong');
                    const header=css('.reference-topbar');
                    const profile=css('#profileShell');
                    const brand=css('.reference-topbar .brand');
                    const info=css('#insightBell');
                    const nav=css('.mobile-tabs');
                    const projects=css('#projectGroupBar');
                    const projectChip=css('#projectGroupBar .project-group-chip');
                    const live=css('#insightShortcut');
                    const controls=['#insightShortcut','#topUpgradeButton','#insightBell','#profileShell']
                      .map(css).filter(Boolean).map(rect);
                    const filterToggle=css('.results-mobile-filter-toggle');
                    const filterBar=css('.results-filter-bar-v683');
                    const minWidth=getComputedStyle(table).minWidth;
                    const collisions=items=>items.some((a,i)=>items.slice(i+1).some(b=>
                      between(a,b)>2 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>2));
                    return {
                      viewport:innerWidth,
                      docOverflow:document.documentElement.scrollWidth-innerWidth,
                      bodyOverflow:document.body.scrollWidth-innerWidth,
                      appOverflow:css('#appShell').scrollWidth-innerWidth,
                      table:rect(table),wrap:rect(wrap),first:rect(first),
                      minWidth,tbodyDisplay:getComputedStyle(table.tBodies[0]).display,
                      tournament:tournament?.innerText||'',
                      clamp:tournament?getComputedStyle(tournament).webkitLineClamp:'',
                      whiteSpace:tournament?getComputedStyle(tournament).whiteSpace:'',
                      filterCollisions:collisions(labels),kpiCollisions:collisions(kpis),
                      header:rect(header),brand:rect(brand),profile:rect(profile),info:rect(info),
                      projects:rect(projects),projectChip:rect(projectChip),live:rect(live),controls,
                      projectsVisible:projects&&getComputedStyle(projects).display!=='none',
                      filterToggleVisible:filterToggle&&getComputedStyle(filterToggle).display!=='none',
                      filterBarDisplay:filterBar?getComputedStyle(filterBar).display:'',
                      cardClass:first?.classList.contains('results-card-row')||false,
                      navVisible:nav&&getComputedStyle(nav).display!=='none',
                      rows:table.tBodies[0].rows.length
                    };
                }""")
                assert report["rows"]==7,(width,report)
                assert report["docOverflow"]<=2,(width,report)
                assert report["bodyOverflow"]<=2,(width,report)
                assert report["filterCollisions"] is False,(width,report)
                assert report["kpiCollisions"] is False,(width,report)
                assert report["profile"]["right"]<=width+2,(width,report)
                assert report["brand"]["right"]<=report["profile"]["left"]+2,(width,report)
                if width<=900:
                    assert report["navVisible"],(width,report)
                    assert report["projectsVisible"] is False,(width,report)
                    assert all(c["width"]>=43 and c["height"]>=43 for c in report["controls"]),(width,report)
                    assert report["table"]["right"]<=width+2,(width,report)
                    assert report["wrap"]["right"]<=width+2,(width,report)
                    assert report["appOverflow"]<=2,(width,report)
                    page.evaluate("window.scrollTo(0,document.documentElement.scrollHeight)")
                    page.wait_for_timeout(60)
                    bottom=page.evaluate("""() => ({
                      pager:document.querySelector('.results-pagination').getBoundingClientRect().bottom,
                      nav:document.querySelector('.mobile-tabs').getBoundingClientRect().top
                    })""")
                    assert bottom["pager"]<=bottom["nav"]-4,(width,bottom)
                    if width<=767:
                        assert report["filterToggleVisible"],(width,report)
                        assert report["filterBarDisplay"]=="none",(width,report)
                        assert report["cardClass"],(width,report)
                        assert report["first"]["right"]<=width+2,(width,report)
                        assert report["minWidth"]=="0px",(width,report)
                        assert report["tbodyDisplay"]=="grid",(width,report)
                        assert report["whiteSpace"]=="normal",(width,report)
                    else:
                        assert not report["filterToggleVisible"],(width,report)
                else:
                    assert not report["navVisible"],(width,report)
                    assert not report["filterToggleVisible"],(width,report)
                    assert report["minWidth"]!="0px",(width,report)
                if width==390:
                    page.set_viewport_size({"width":390,"height":844})
                    page.evaluate("window.scrollTo(0,0)")
                    page.wait_for_timeout(60)
                    visible=page.evaluate("""() => {
                      const card=document.querySelector('.results-table tbody tr');
                      const nav=document.querySelector('.mobile-tabs');
                      const r=card.getBoundingClientRect(),n=nav.getBoundingClientRect();
                      return {top:r.top,bottom:r.bottom,navTop:n.top,height:r.height};
                    }""")
                    assert visible["height"]>0 and visible["top"]>=0 and visible["bottom"]<=visible["navTop"],(width,visible)
                assert not errors,(width,errors)
                page.close()
            print("Mobile Results 320/360/390/430/768/900 + desktop 1024/1440 geometry: PASS")
        finally:
            browser.close()


if __name__=="__main__":
    main()
