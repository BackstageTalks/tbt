"""Phone app / tablet Predictions geometry audit (offline Chromium)."""
import os
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        source = source.replace(marker, "  window.mobileAudit={positionAccessHint};\n" + marker)
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


FIXTURE = """() => {
  document.querySelector('#bootSplash')?.remove();
  document.querySelector('#cookieConsent')?.remove();
  document.querySelectorAll('dialog[open]').forEach(el=>el.close());
  const shell=document.querySelector('#appShell'); shell.hidden=false;
  document.body.className='blinq-home';
  document.body.dataset.route='predictions';
  document.querySelector('#routePanel').hidden=true;
  document.querySelector('#predictionsView').hidden=false;

  for (const sel of ['#topUpgradeButton','#insightShortcut','#insightBell','#profileShell']) {
    document.querySelector(sel).hidden=false;
  }
  const projects=document.querySelector('#projectGroupBar');
  projects.hidden=false;
  projects.innerHTML='<button class="project-group-chip is-purple is-active"><span>◆</span><strong>Platba PO</strong></button>';
  document.querySelector('#avatar').textContent='B';

  const hero=document.querySelector('#dashboardHero');
  hero.hidden=false;
  hero.innerHTML='<article class="dashboard-hero is-active"><div class="hero-slide-image" style="background:#08251f"></div><div class="dashboard-hero-copy"><small>BLINQ</small><h2>Tenis má dve strany. My poznáme obe.</h2><p>Mobilný audit.</p></div></article>';

  document.querySelector('#dashboardKpis').innerHTML=[
    ['Dnešné predikcie','60'],['Úspešnosť','76.7%'],['Priem. kurz','1.50']
  ].map(([label,value])=>'<article class="dashboard-kpi"><span>↗</span><div><small>'+label+'</small><strong>'+value+'</strong><p>Pomocný údaj</p></div></article>').join('');

  const hub=document.querySelector('#dailyHub'); hub.hidden=false;
  document.querySelector('#dailyHubTabs').innerHTML=
    ['TOP200','TOP','SHORT ODDS','VALUE','ACES','DVOJCHYBY','DOUBLES','GAMES','SETS'].map((name,i)=>
      '<button class="daily-hub-tab '+(i===0?'active':'')+'"><span>'+name+'</span></button>').join('');
  const body=document.querySelector('#dailyHubBody');
  body.innerHTML=Array.from({length:4},(_,i)=>'<tr>'+
    '<td class="hub-rank">'+(i+1)+'</td>'+
    '<td class="hub-time"><strong>'+(12+i)+':20</strong><small>02.10.26</small></td>'+
    '<td class="hub-tournament-cell"><div class="hub-tournament"><span class="hub-tournament-logo"></span><span class="hub-tournament-copy"><b>ITF W100 Templeton Qualification</b><small>WTA · HARD</small></span></div></td>'+
    '<td class="hub-match-cell"><div class="hub-match"><span class="hub-player"><span class="hub-avatar"></span><span class="hub-player-copy"><b>Long Player Name '+i+'</b></span></span><span class="hub-vs">vs</span><span class="hub-player"><span class="hub-avatar"></span><span class="hub-player-copy"><b>Second Player With Long Surname '+i+'</b></span></span></div></td>'+
    '<td class="hub-pick" data-label="Predikcia"><span class="hub-pick-stack"><small>Predikcia</small><strong>Second Player With Long Surname '+i+'</strong></span></td>'+
    '<td class="hub-odds" data-label="Kurz"><span class="hub-number-stack"><small>Kurz</small><strong>1.57</strong></span></td>'+
    '<td class="hub-confidence-cell" data-label="Model"><span class="hub-confidence"><strong>73.5%</strong><small>Data 100%</small></span></td>'+
    '<td class="hub-action-cell"><button class="hub-detail">Detail</button></td>'+
    '</tr>').join('');

  const footer=document.querySelector('.site-footer-minimal'); footer.hidden=false;
  document.querySelector('#mobileTabs a[data-route="predictions"]').classList.add('active');
}"""


def main():
    viewports = [
        (320, 568, "small-phone"),
        (360, 640, "phone-360"),
        (390, 844, "phone-390"),
        (430, 932, "phone-430"),
        (667, 375, "phone-landscape"),
        (768, 1024, "tablet-768"),
        (844, 390, "tablet-landscape"),
        (900, 900, "tablet-900"),
    ]
    with sync_playwright() as pw:
        executable = os.getenv("BLINQ_BROWSER") or browser_path()
        browser = pw.chromium.launch(headless=True, executable_path=executable) if executable else pw.chromium.launch(headless=True)
        try:
            for width, height, label in viewports:
                page = browser.new_page(viewport={"width": width, "height": height})
                errors=[]
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.route("**/*", route_request)
                page.goto(ORIGIN+"/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.mobileAudit")
                page.evaluate(FIXTURE)
                page.wait_for_timeout(50)
                report=page.evaluate("""() => {
                  const q=s=>document.querySelector(s);
                  const visible=e=>!!e&&!e.hidden&&getComputedStyle(e).display!=='none';
                  const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
                  const controls=['#insightShortcut','#topUpgradeButton','#insightBell','#profileShell'].map(s=>q(s)).filter(visible).map(rect);
                  const kpis=[...document.querySelectorAll('.dashboard-kpi')].map(rect);
                  const first=q('#dailyHubBody tr');
                  const scroller=q('.table-scroller');
                  return {
                    docOverflow:document.documentElement.scrollWidth-innerWidth,
                    bodyOverflow:document.body.scrollWidth-innerWidth,
                    header:rect(q('.reference-topbar')), brand:rect(q('.reference-topbar .brand')),
                    controls,kpis,hero:rect(q('#dashboardHero')),
                    projectVisible:visible(q('#projectGroupBar')),
                    navVisible:visible(q('#mobileTabs')),
                    topNavVisible:visible(q('.reference-navigation')),
                    first:rect(first), scroller:rect(scroller),
                    tableMinWidth:getComputedStyle(q('.daily-hub-table')).minWidth,
                    tableDisplay:getComputedStyle(q('.daily-hub-table')).display,
                    tabsOverflow:q('#dailyHubTabs').scrollWidth-q('#dailyHubTabs').clientWidth,
                  };
                }""")
                assert report["docOverflow"] <= 2, (label, report)
                assert report["bodyOverflow"] <= 2, (label, report)
                assert report["brand"]["left"] >= -1 and report["brand"]["right"] <= width+1, (label, report)
                if width <= 767:
                    assert report["navVisible"] and not report["topNavVisible"], (label, report)
                    assert not report["projectVisible"], (label, report)
                    assert all(c["width"] >= 43.5 and c["height"] >= 43.5 for c in report["controls"]), (label, report)
                    assert report["hero"]["height"] <= 110, (label, report)
                    assert len({round(k["top"],1) for k in report["kpis"]}) == 1, (label, report)
                    assert report["first"]["left"] >= -1 and report["first"]["right"] <= width+1, (label, report)
                    assert report["tableDisplay"] == "block", (label, report)
                    # The project directory remains reachable from the account menu.
                    page.click('#profileButton')
                    assert page.locator('#profileMenu').is_visible(), label
                    assert page.locator('#profileProjectsLink').is_visible(), label
                    page.click('#profileButton')
                else:
                    assert not report["navVisible"] and report["topNavVisible"], (label, report)
                    assert not report["projectVisible"], (label, report)
                    assert report["tableDisplay"] == "table", (label, report)
                    assert report["tableMinWidth"] != "0px", (label, report)
                    assert report["scroller"]["right"] <= width+1, (label, report)
                assert not errors, (label, errors)
                page.close()
            print("Predictions phone/tablet responsive geometry and access controls: PASS")
        finally:
            browser.close()


if __name__=="__main__":
    main()
