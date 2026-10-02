"""Capture real BlinQ mobile UI screenshots from the checked-out repository."""
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path

OUT = Path("artifacts/ui-preview")
OUT.mkdir(parents=True, exist_ok=True)


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        source = source.replace(
            marker,
            "  window.uiPreview={state,renderResultsFilters,resultsSummary,renderResults,renderInsightBell};\n" + marker,
        )
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        executable = os.getenv("BLINQ_BROWSER") or browser_path()
        browser = (
            pw.chromium.launch(headless=True, executable_path=executable)
            if executable else pw.chromium.launch(headless=True)
        )
        try:
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                device_scale_factor=1,
                is_mobile=True,
                has_touch=True,
            )
            page = context.new_page()
            page.route("**/*", route_request)
            page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
            page.wait_for_function("window.uiPreview")
            page.evaluate("""() => {
              document.querySelector('#bootSplash')?.remove();
              document.querySelector('#cookieConsent')?.remove();
              document.querySelectorAll('dialog[open]').forEach(el=>el.close());
              document.querySelector('#appShell').hidden=false;
              document.body.className='blinq-home';
              document.querySelector('#routePanel').hidden=true;
              document.querySelector('#predictionsView').hidden=false;

              const live=document.querySelector('#insightShortcut');
              const bell=document.querySelector('#insightBell');
              const profile=document.querySelector('#profileShell');
              const projects=document.querySelector('#projectGroupBar');
              live.hidden=false; bell.hidden=false; profile.hidden=false; projects.hidden=false;
              document.querySelector('#topUpgradeButton').hidden=false;
              projects.innerHTML='<button class="project-group-chip is-purple is-active" type="button"><span>◆</span><strong>Platba PO</strong></button>';
              document.querySelector('#avatar').textContent='B';

              const hero=document.querySelector('#dashboardHero');
              hero.hidden=false;
              hero.innerHTML='<article class="dashboard-hero is-active"><div class="hero-slide-image" style="background:linear-gradient(120deg,#06261f,#0b4450)"></div><div class="dashboard-hero-copy"><small>BLINQ</small><h2>Tenis má dve strany. BlinQ pozná obe.</h2><p>Aktuálne predikcie a dáta.</p></div></article>';

              document.querySelector('#dashboardKpis').innerHTML=[
                ['DNEŠNÉ PREDIKCIE','64'],['ÚSPEŠNOSŤ','76.3%'],['PRIEMERNÝ KURZ','1.50']
              ].map(([label,value])=>'<article class="dashboard-kpi"><span>↗</span><div><small>'+label+'</small><strong>'+value+'</strong></div></article>').join('');

              const hub=document.querySelector('#dailyHub'); hub.hidden=false;
              document.querySelector('#dailyHubTabs').innerHTML=
                ['TOP200','TOP','VALUE','SHORT ODDS','ACES','DVOJCHYBY','GAMES','SETS'].map((name,i)=>
                  '<button class="daily-hub-tab '+(i===0?'active':'')+'"><span>'+name+'</span></button>').join('');
              document.querySelector('#dailyHubBody').innerHTML=[
                ['12:20','ATP Shanghai','Alejandro Tabilo','Arthur Rinderknech','Tabilo','1.62','68.4%'],
                ['13:05','WTA Beijing','Linda Noskova','Emma Navarro','Noskova','1.74','66.1%'],
                ['14:40','ATP Shanghai','Jannik Sinner','Tomas Machac','Sinner','1.28','81.7%']
              ].map((r,i)=>'<tr>'+
                '<td class="hub-rank">'+(i+1)+'</td>'+
                '<td class="hub-time"><strong>'+r[0]+'</strong><small>02.10.26</small></td>'+
                '<td class="hub-tournament-cell"><div class="hub-tournament"><span class="hub-tournament-logo"></span><span class="hub-tournament-copy"><b>'+r[1]+'</b><small>HARD</small></span></div></td>'+
                '<td class="hub-match-cell"><div class="hub-match"><span class="hub-player"><span class="hub-avatar"></span><span class="hub-player-copy"><b>'+r[2]+'</b></span></span><span>vs</span><span class="hub-player"><span class="hub-avatar"></span><span class="hub-player-copy"><b>'+r[3]+'</b></span></span></div></td>'+
                '<td class="hub-pick"><span class="hub-pick-stack"><small>PREDIKCIA</small><strong>'+r[4]+'</strong></span></td>'+
                '<td class="hub-odds"><span class="hub-number-stack"><small>KURZ</small><strong>'+r[5]+'</strong></span></td>'+
                '<td class="hub-confidence-cell"><span class="hub-confidence"><strong>'+r[6]+'</strong><small class="hub-data-depth">DATA DEPTH · 100%</small></span></td>'+
                '<td class="hub-action-cell"><button class="hub-detail">Detail</button></td>'+
                '</tr>').join('');
              document.querySelector('#mobileTabs a[data-route="predictions"]').classList.add('active');
            }""")
            page.wait_for_timeout(200)
            page.screenshot(path=str(OUT / "mobile-home.png"), full_page=True)

            page.evaluate("""() => {
              const t=window.uiPreview,s=t.state;
              s.route='results';
              s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active'};
              s.resultsFilters={category:'all',tour:'',surface:'',window:'all',dateFrom:'',dateTo:''};
              s.resultsPage=0;s.resultsPageSize=50;
              s.feed.results=Array.from({length:5},(_,i)=>({
                event_id:'preview-'+i,
                tour:i%2?'WTA':'ATP',
                surface:'hard',
                scheduled_at:'2026-10-02T14:00:00Z',
                tournament:i%2?'WTA Beijing':'ATP Shanghai Masters',
                tournament_city:i%2?'Beijing':'Shanghai',
                player1:{id:'p1-'+i,name:['Alejandro Tabilo','Linda Noskova','Jannik Sinner','Mirra Andreeva','Taylor Fritz'][i],country_code:'SVK'},
                player2:{id:'p2-'+i,name:['Arthur Rinderknech','Emma Navarro','Tomas Machac','Jessica Pegula','Daniil Medvedev'][i],country_code:'USA'},
                market_publications:[{
                  section:i===0?'top200':(i===1?'value':'top_daily'),
                  market:'match_winner',
                  issued_at:'2026-10-02T10:00:00Z',
                  selection:['Alejandro Tabilo','Linda Noskova','Jannik Sinner','Mirra Andreeva','Taylor Fritz'][i],
                  selection_id:'p1-'+i,
                  model_probability:.68-i*.01,
                  odds:1.62+i*.07,
                  price_status:'priced',
                  result:{status:i<3?'hit':'pending',correct:i<3,staked_units:1,profit_units:i<3?.62:0}
                }]
              }));
              document.body.className='blinq-route';
              document.querySelector('#predictionsView').hidden=true;
              const route=document.querySelector('#routePanel'); route.hidden=false;
              route.innerHTML=t.renderResultsFilters()+t.resultsSummary()+t.renderResults();
              window.BlinqUI.prepareRoute(route);
              document.querySelector('#routeHeading').hidden=false;
              document.querySelector('#pageEyebrow').textContent='BLINQ';
              document.querySelector('#pageTitle').textContent='Výsledky';
              document.querySelector('#pageSubtitle').textContent='';
              document.querySelectorAll('#mobileTabs a').forEach(a=>a.classList.remove('active'));
              document.querySelector('#mobileTabs a[data-route="results"]').classList.add('active');
            }""")
            page.wait_for_timeout(200)
            page.screenshot(path=str(OUT / "mobile-results.png"), full_page=True)
            print("Captured:", OUT / "mobile-home.png", OUT / "mobile-results.png")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
