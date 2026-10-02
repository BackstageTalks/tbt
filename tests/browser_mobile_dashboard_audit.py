"""Mobile dashboard geometry matrix for Chrome/Brave-class Chromium.

Covers small phones, common Android/iPhone portrait sizes, tablet width and
landscape viewport shrinkage. No live API or network is used.
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
            "  window.mobileAudit={positionAccessHint};\n" + marker,
        )
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


FIXTURE = """() => {
  document.querySelector('#bootSplash')?.remove();
  document.querySelector('#cookieConsent')?.remove();
  document.querySelectorAll('dialog[open]').forEach(el=>el.close());
  const shell=document.querySelector('#appShell'); shell.hidden=false;
  document.body.className='blinq-home';
  document.querySelector('#routePanel').hidden=true;
  document.querySelector('#predictionsView').hidden=false;

  const upgrade=document.querySelector('#topUpgradeButton');
  const live=document.querySelector('#insightShortcut');
  const bell=document.querySelector('#insightBell');
  const profile=document.querySelector('#profileShell');
  const projects=document.querySelector('#projectGroupBar');
  upgrade.hidden=false; live.hidden=false; bell.hidden=false; profile.hidden=false;
  projects.hidden=false;
  projects.innerHTML=['ALPHA','TESTERI','PARTNER X','RESEARCH'].map((name,i)=>
    '<button class="project-group-chip is-'+(['blue','orange','purple','green'][i])+'"><span>◆</span><strong>'+name+'</strong>'+(i===0?'<b>2</b>':'')+'</button>').join('');
  live.classList.add('is-access-locked');
  live.querySelector('#insightShortcutCount').hidden=false;
  live.querySelector('#insightShortcutCount').textContent='2';
  bell.classList.remove('is-access-locked');
  document.querySelector('#avatar').textContent='B';

  const hero=document.querySelector('#dashboardHero');
  hero.hidden=false;
  hero.innerHTML='<article class="dashboard-hero is-active"><div class="hero-slide-image" style="background:#08251f"></div><div class="dashboard-hero-copy"><small>BLINQ</small><h2>Každý zápas má príbeh, BlinQ má dáta.</h2><p>Mobilný audit.</p></div></article>';

  document.querySelector('#dashboardKpis').innerHTML=[
    ['DNEŠNÉ PREDIKCIE','60'],['ÚSPEŠNOSŤ','76.7%'],['PRIEMERNÝ KURZ','1.50']
  ].map(([label,value])=>'<article class="dashboard-kpi"><span>↗</span><div><small>'+label+'</small><strong>'+value+'</strong></div></article>').join('');

  const hub=document.querySelector('#dailyHub'); hub.hidden=false;
  document.querySelector('#dailyHubTabs').innerHTML=
    ['TOP','SHORT ODDS','VALUE','ACES','DVOJCHYBY','DOUBLES','GAMES','SETS'].map((name,i)=>
      '<button class="daily-hub-tab '+(i===0?'active':'')+'"><span>'+name+'</span></button>').join('');
  const body=document.querySelector('#dailyHubBody');
  body.innerHTML=Array.from({length:10},(_,i)=>'<tr>'+
    '<td class="hub-rank">'+(i+1)+'</td>'+
    '<td class="hub-time"><strong>'+(12+i)+':20</strong><small>28.09.26</small></td>'+
    '<td class="hub-tournament-cell"><div class="hub-tournament"><span class="hub-tournament-logo"></span><span class="hub-tournament-copy"><b>ITF W35 Reims Women Qualification</b><small>WTA · QUALIFICATIONS · HARD</small></span></div></td>'+
    '<td class="hub-match-cell"><div class="hub-match"><span class="hub-player"><span class="hub-avatar"></span><span class="hub-player-copy"><b>Long Player Name '+i+'</b></span></span><span>vs</span><span class="hub-player"><span class="hub-avatar"></span><span class="hub-player-copy"><b>Second Player Name '+i+'</b></span></span></div></td>'+
    '<td class="hub-pick"><span class="hub-pick-stack"><small>PREDIKCIA</small><strong>Second Player With Long Surname '+i+'</strong></span></td>'+
    '<td class="hub-odds"><span class="hub-number-stack"><small>KURZ</small><strong>1.57</strong></span></td>'+
    '<td class="hub-confidence-cell"><span class="hub-confidence"><strong>73.5%</strong><small class="hub-data-depth">DATA DEPTH · 100%</small></span></td>'+
    '<td class="hub-action-cell"><button class="hub-detail">Detail</button></td>'+
    '</tr>').join('');

  const footer=document.querySelector('.site-footer-minimal');
  footer.hidden=false;
  const resultNav=document.querySelector('#mobileTabs a[data-route="results"]');
  resultNav.classList.add('access-nav-locked');
  document.querySelector('#mobileTabs a[data-route="predictions"]').classList.add('active');

  const hint=document.querySelector('#accessHint');
  hint.hidden=false;
  mobileAudit.positionAccessHint(resultNav);
}"""


def overlap(a, b):
    return min(a["right"], b["right"]) - max(a["left"], b["left"]) > 2 and min(a["bottom"], b["bottom"]) - max(a["top"], b["top"]) > 2


def main():
    viewports = [
        (320, 568, "small-android"),
        (360, 640, "android-360"),
        (375, 667, "iphone-small"),
        (390, 844, "iphone-modern"),
        (412, 915, "android-modern"),
        (430, 932, "wide-phone"),
        (568, 320, "landscape-small"),
        (667, 375, "landscape-medium"),
        (844, 390, "landscape-wide"),
        (768, 1024, "tablet-portrait"),
    ]
    brave_ua = (
        "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36 Brave/1.80"
    )
    with sync_playwright() as pw:
        executable = os.getenv("BLINQ_BROWSER") or browser_path()
        browser = (
            pw.chromium.launch(headless=True, executable_path=executable)
            if executable else pw.chromium.launch(headless=True)
        )
        try:
            for width, height, label in viewports:
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    is_mobile=width <= 900,
                    has_touch=width <= 900,
                    user_agent=brave_ua if label == "iphone-modern" else None,
                )
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.mobileAudit")
                page.evaluate(FIXTURE)
                page.wait_for_timeout(80)
                report = page.evaluate("""() => {
                  const rect=sel=>{const e=typeof sel==='string'?document.querySelector(sel):sel;if(!e)return null;const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
                  const visible=sel=>{const e=document.querySelector(sel);return e&&!e.hidden&&getComputedStyle(e).display!=='none';};
                  const actions=['#topUpgradeButton','#insightShortcut','#insightBell','#profileShell'].filter(visible).map(sel=>({sel,r:rect(sel)}));
                  const footer=rect('.site-footer-minimal'),last=rect('#dailyHubBody tr:last-child'),nav=rect('#mobileTabs'),hint=rect('#accessHint');
                  const status=rect('#footerSystemStatus'),langs=rect('#footerLanguages');
                  const locked=document.querySelector('#mobileTabs a[data-route="results"]');
                  const lockStyle=getComputedStyle(locked,'::after');
                  return {
                    viewport:{width:innerWidth,height:innerHeight},
                    docOverflow:document.documentElement.scrollWidth-innerWidth,
                    header:rect('.reference-topbar'),brand:rect('.reference-topbar .brand'),
                    actions,projects:rect('#projectGroupBar'),projectChips:[...document.querySelectorAll('#projectGroupBar .project-group-chip')].map(rect),hero:rect('#dashboardHero'),last,footer,nav,hint,status,langs,
                    navVisible:visible('#mobileTabs'),
                    tableMaxHeight:getComputedStyle(document.querySelector('.table-scroller')).maxHeight,
                    lockTop:lockStyle.top,lockLeft:lockStyle.left,
                  };
                }""")
                assert report["docOverflow"] <= 2, (label, report)
                assert report["brand"]["right"] <= width + 1, (label, report)
                assert report["projects"]["left"] >= -1 and report["projects"]["right"] <= width + 1, (label, report)
                assert report["projectChips"] and all(chip["width"] > 20 for chip in report["projectChips"]), (label, report)
                actions = [x["r"] for x in report["actions"]]
                for i, a in enumerate(actions):
                    assert a["left"] >= -1 and a["right"] <= width + 1, (label, report)
                    for b in actions[i + 1:]:
                        assert not overlap(a, b), (label, report)
                assert report["hero"]["top"] >= report["header"]["bottom"] - 2, (label, report)
                # Regression for the screenshot where row 5/6 painted through
                # the normal-flow system/language footer.
                assert report["tableMaxHeight"] == "none", (label, report)
                assert report["last"]["bottom"] <= report["footer"]["top"] + 2, (label, report)
                if report["status"] and report["langs"] and width > 480:
                    assert not overlap(report["status"], report["langs"]), (label, report)
                if width <= 900:
                    assert report["navVisible"], (label, report)
                    assert report["nav"]["left"] >= 0 and report["nav"]["right"] <= width, (label, report)
                    assert report["hint"]["bottom"] <= report["nav"]["top"] - 2, (label, report)
                    assert report["lockTop"] != "50%", (label, report)
                    page.evaluate("window.scrollTo(0,document.documentElement.scrollHeight)")
                    page.wait_for_timeout(60)
                    bottom = page.evaluate("""() => ({
                      footer:document.querySelector('.site-footer-minimal').getBoundingClientRect().bottom,
                      nav:document.querySelector('#mobileTabs').getBoundingClientRect().top
                    })""")
                    assert bottom["footer"] <= bottom["nav"] - 2, (label, bottom)
                page.evaluate("""() => {
                  const dialog=document.querySelector('#projectGroupsDialog');
                  const list=document.querySelector('#projectGroupsDialogList');
                  const status=document.querySelector('#projectGroupsDialogStatus');
                  status.textContent='1 moje · 4 projekty';
                  list.innerHTML=[
                    ['OTVORENÁ','ALPHA RESEARCH PROJECT','Pridať sa'],
                    ['NA ŽIADOSŤ','PARTNER DATA GROUP WITH LONG NAME','Chcem sa pridať'],
                    ['UZAVRETÁ','PAID DATA PROJECT','🔒 Skupina je plná'],
                    ['UZAVRETÁ','DEADLINE PROJECT','🔒 Vstup je ukončený']
                  ].map((row,i)=>'<article class="project-directory-card is-'+(['blue','orange','purple','green'][i])+(i>1?' is-locked':'')+'"><header><div><small>PROJEKT · '+row[0]+'</small><strong>'+row[1]+'</strong></div><span>'+(i+7)+'/10</span></header><p>Dlhší popis projektu pre mobilný audit bez rozbitia layoutu.</p><div class="project-directory-meta"><span>1,00 € / osoba</span><span>10,00 € spolu</span><span>Vstup do 05.10. · 20:00</span></div><footer><button class="btn '+(i>1?'btn-ghost project-locked-button':'btn-primary')+'">'+row[2]+'</button></footer></article>').join('');
                  dialog.showModal();
                }""")
                page.wait_for_timeout(40)
                modal = page.evaluate("""() => {
                  const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
                  const dialog=document.querySelector('#projectGroupsDialog');
                  const list=document.querySelector('#projectGroupsDialogList');
                  return {
                    dialog:rect(dialog),
                    list:rect(list),
                    listOverflow:list.scrollWidth-list.clientWidth,
                    cards:[...list.querySelectorAll('.project-directory-card')].map(rect),
                  };
                }""")
                assert modal["dialog"]["left"] >= -1 and modal["dialog"]["right"] <= width + 1, (label, modal)
                assert modal["listOverflow"] <= 2, (label, modal)
                assert all(card["left"] >= modal["dialog"]["left"] - 1 and card["right"] <= modal["dialog"]["right"] + 1 for card in modal["cards"]), (label, modal)
                page.evaluate("document.querySelector('#projectGroupsDialog')?.close()")
                assert not errors, (label, errors)
                context.close()
            print("Mobile dashboard 320-844 portrait/landscape + Brave-class Chromium + tablet: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
