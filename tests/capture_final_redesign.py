"""Capture real Chromium renders of the final BlinQ dark redesign from this checkout."""
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path

OUT = Path("artifacts/final-redesign")
OUT.mkdir(parents=True, exist_ok=True)


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        source = source.replace(
            marker,
            "  window.finalPreview={state,renderResultsFilters,resultsSummary,renderResults,renderInsightBell};\n" + marker,
        )
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


def seed_shell(page):
    page.wait_for_function("window.finalPreview")
    page.evaluate("""() => {
      document.querySelector('#bootSplash')?.remove();
      document.querySelector('#cookieConsent')?.remove();
      document.querySelectorAll('dialog[open]').forEach(el=>el.close());
      document.querySelector('#appShell').hidden=false;
      const projects=document.querySelector('#projectGroupBar');
      projects.hidden=false;
      projects.innerHTML='<button class="project-group-chip is-purple is-active" type="button" aria-label="Platba P0"><span>◆</span><strong>Platba P0</strong></button>';
      document.querySelector('#insightShortcut').hidden=false;
      document.querySelector('#topUpgradeButton').hidden=false;
      document.querySelector('#insightBell').hidden=false;
      document.querySelector('#profileShell').hidden=false;
      document.querySelector('#avatar').textContent='B';
    }""")


def home(page):
    page.evaluate("""() => {
      document.body.className='blinq-home';
      document.querySelector('#routePanel').hidden=true;
      document.querySelector('#routeHeading').hidden=true;
      document.querySelector('#predictionsView').hidden=false;
      const hero=document.querySelector('#dashboardHero');
      hero.hidden=false;
      hero.innerHTML='<article class="dashboard-hero is-active"><div class="hero-slide-image" style="background:radial-gradient(circle at 75% 40%,rgba(52,238,157,.22),transparent 17%),linear-gradient(115deg,#04110f 0%,#082923 55%,#0a3f34 100%)"></div><div class="dashboard-hero-copy"><small>BLINQ INTELLIGENCE</small><h2>Každý zápas má príbeh.<br>BlinQ má dáta.</h2><p>Modelové predikcie postavené na forme, povrchu a kvalite hráčov.</p></div></article>';
      document.querySelector('#dashboardKpis').innerHTML=[
        ['↗','DNEŠNÉ PREDIKCIE','64'],['◎','ÚSPEŠNOSŤ','76.5%'],['⌁','PRIEMERNÝ KURZ','1.42']
      ].map(([icon,label,value])=>'<article class="dashboard-kpi"><span>'+icon+'</span><div><small>'+label+'</small><strong>'+value+'</strong><p>Aktuálny výber</p></div></article>').join('');
      document.querySelector('#dailyHub').hidden=false;
      document.querySelector('#dailyHubTabs').innerHTML=
        ['TOP200','TOP','SHORT ODDS','VALUE','ACES','DVOJCHYBY','DOUBLES','GAMES','SETS'].map((n,i)=>'<button class="daily-hub-tab '+(i===0?'active':'')+'" type="button"><span>'+n+'</span></button>').join('');
      document.querySelector('#dailyHubBody').innerHTML=[
        ['12:20','ATP Shanghai','Alejandro Tabilo','Arthur Rinderknech','Tabilo','1.62','68.4%'],
        ['13:05','WTA Beijing','Linda Noskova','Emma Navarro','Noskova','1.74','66.1%'],
        ['14:40','ATP Shanghai','Jannik Sinner','Tomas Machac','Sinner','1.28','81.7%']
      ].map((r,i)=>'<tr>'+
        '<td class="hub-rank">#'+(i+1)+'</td>'+
        '<td><strong>'+r[0]+'</strong><small>02.10</small></td>'+
        '<td><div class="hub-tournament"><span class="hub-tournament-logo">ATP</span><span class="hub-tournament-copy"><b>'+r[1]+'</b><small>HARD</small></span></div></td>'+
        '<td><div class="hub-match"><span class="hub-player"><span class="hub-avatar"></span><span class="hub-player-copy"><strong>'+r[2]+'</strong><small>TOP 200</small></span></span><i>vs</i><span class="hub-player"><span class="hub-avatar"></span><span class="hub-player-copy"><strong>'+r[3]+'</strong><small>TOP 200</small></span></span></div></td>'+
        '<td><strong>'+r[4]+'</strong></td><td><strong>'+r[5]+'</strong></td><td><strong class="hub-prob">'+r[6]+'</strong></td><td><button class="hub-detail">Detail</button></td>'+
      '</tr>').join('');
      const tg=document.querySelector('#telegramGroupsPanel');
      tg.hidden=false;
      tg.innerHTML='<div class="tg-panel-head"><div><small>BLINQ COMMUNITY</small><h2>Telegram skupiny</h2><p>Komunita a súkromné skupiny.</p></div></div><div class="tg-group-grid">'+
        ['GrandSlamTalks','TennisBackstageTalks','BlinQ Premium'].map(n=>'<article class="tg-group-card"><span class="tg-group-icon">↗</span><div class="tg-group-copy"><strong>'+n+'</strong><p>Komunita pre BlinQ členov.</p></div><button class="tg-group-cta">Pridať sa</button></article>').join('')+
      '</div>';
      document.querySelectorAll('#mobileTabs a').forEach(a=>a.classList.remove('active'));
      document.querySelector('#mobileTabs a[data-route="predictions"]').classList.add('active');
    }""")


def results(page):
    page.evaluate("""() => {
      const t=window.finalPreview,s=t.state;
      s.route='results';
      s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active'};
      s.resultsFilters={category:'all',tour:'',surface:'',window:'all',dateFrom:'',dateTo:''};
      s.resultsPage=0;s.resultsPageSize=50;
      s.feed.results=Array.from({length:6},(_,i)=>({
        event_id:'preview-'+i,tour:i%2?'WTA':'ATP',surface:'hard',
        scheduled_at:'2026-10-02T14:00:00Z',
        tournament:i%2?'WTA Beijing':'ATP Shanghai Masters',
        tournament_city:i%2?'Beijing':'Shanghai',
        player1:{id:'p1-'+i,name:['Alejandro Tabilo','Linda Noskova','Jannik Sinner','Mirra Andreeva','Taylor Fritz','Coco Gauff'][i],country_code:'SVK'},
        player2:{id:'p2-'+i,name:['Arthur Rinderknech','Emma Navarro','Tomas Machac','Jessica Pegula','Daniil Medvedev','Aryna Sabalenka'][i],country_code:'USA'},
        market_publications:[{section:i===0?'top200':(i===1?'value':'top_daily'),market:'match_winner',
          issued_at:'2026-10-02T10:00:00Z',
          selection:['Alejandro Tabilo','Linda Noskova','Jannik Sinner','Mirra Andreeva','Taylor Fritz','Coco Gauff'][i],
          selection_id:'p1-'+i,model_probability:.68-i*.01,odds:1.62+i*.07,price_status:'priced',
          result:{status:i===4?'miss':'hit',correct:i!==4,staked_units:1,profit_units:i===4?-1:.62}}]
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


def capture(browser, width, height, mobile, name, mode):
    context=browser.new_context(viewport={"width":width,"height":height},device_scale_factor=1,is_mobile=mobile,has_touch=mobile)
    page=context.new_page()
    errors=[]
    page.on("pageerror",lambda e:errors.append(str(e)))
    page.route("**/*",route_request)
    page.goto(ORIGIN+"/index.html?lang=sk",wait_until="networkidle")
    seed_shell(page)
    (home if mode=="home" else results)(page)
    page.wait_for_timeout(250)
    assert not errors, errors
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"), (name,"horizontal overflow")
    page.screenshot(path=str(OUT/name),full_page=True)
    context.close()


def main():
    with sync_playwright() as pw:
        executable=os.getenv("BLINQ_BROWSER") or browser_path()
        browser=pw.chromium.launch(headless=True,executable_path=executable) if executable else pw.chromium.launch(headless=True)
        try:
            capture(browser,1440,1000,False,"desktop-home.png","home")
            capture(browser,1440,1000,False,"desktop-results.png","results")
            capture(browser,390,844,True,"mobile-home.png","home")
            capture(browser,390,844,True,"mobile-results.png","results")
            capture(browser,320,760,True,"mobile-320-results.png","results")
            print("Final redesign screenshots: PASS")
        finally:
            browser.close()

if __name__=="__main__":
    main()
