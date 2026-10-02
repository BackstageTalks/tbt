"""Secondary BlinQ mobile preview contract.

The preview is the real BlinQ runtime behind a separate HTML entry. This test
uses deterministic fixtures only to exercise layout/behaviour without touching
Firebase, Azure or paid providers. It never changes the production index.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path

SHOT_DIR = Path(os.getenv("BLINQ_PREVIEW_SCREENSHOT_DIR", "/tmp/blinq-mobile-preview-shots"))


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        source = source.replace(
            marker,
            "  window.mobilePreviewTest={state,renderHeroBanner,renderDashboardKpis,"
            "renderDailyHub,wireDailyHub,setRoute,filteredResults,renderResultsFilters,"
            "resultsSummary,renderResults,wireResultsFilters,openMatch};\n" + marker,
        )
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


FIXTURE = r"""() => {
  document.querySelector('#bootSplash')?.remove();
  document.querySelector('#cookieConsent')?.remove();
  document.querySelectorAll('dialog[open]').forEach(el=>el.close());
  const shell=document.querySelector('#appShell'); shell.hidden=false;
  const t=mobilePreviewTest,s=t.state;
  s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active',email:'preview@example.test'};
  s.previewPlan=null;
  s.resultsFilters={category:'all',tour:'',surface:'',window:'all',dateFrom:'',dateTo:'',bettingDay:true};
  s.resultsPage=0;s.resultsPageSize=50;
  s.dailyHubTab='top200';s.dailyHubExpanded=false;s.dashboardSearch='';s.dailyHubTournament='';

  const match=(id,tour,p1,p2,pick,odds,prob,tournament,surface='hard')=>({
    event_id:id,tour,surface,scheduled_at:'2026-10-02T13:30:00+02:00',
    tournament,round:'R32',tournament_country_code:tour==='WTA'?'CHN':'USA',
    player1:{id:id+'-p1',name:p1,country_code:tour==='WTA'?'POL':'ESP',rank:12},
    player2:{id:id+'-p2',name:p2,country_code:tour==='WTA'?'USA':'FRA',rank:27},
    pick,selection:pick,selection_id:id+'-p1',winner_id:id+'-p1',
    odds,model_probability:prob,blinq_probability:prob,data_depth:.92,
    betting:{odds,selection_id:id+'-p1'},quality:{player1:{matches:28,surface_matches:18},player2:{matches:31,surface_matches:20}}
  });
  const topA=match('top-a','WTA','Iga Świątek','Jessica Pegula','Iga Świątek',1.62,.68,'China Open · Beijing');
  const topB=match('top-b','ATP','Alejandro Fernández de la Cruz','Maximiliano Alessandro Dimitrov','Alejandro Fernández de la Cruz',1.71,.64,'ATP Masters 1000 Shanghai Qualification');
  const shortA=match('short-a','WTA','Aryna Sabalenka','Coco Gauff','Aryna Sabalenka',1.48,.72,'Wuhan Open');
  const valueA=match('value-a','ATP','Quentin Halys','Roman Safiullin','Quentin Halys',1.91,.59,'Shanghai Masters');
  s.feed.top200_picks=[topA,topB];
  s.feed.daily_picks=[topA,shortA];
  s.feed.prime_picks=[shortA];
  s.feed.value_picks=[valueA];
  s.feed.doubles_picks=[];s.feed.ace_picks=[];s.feed.sg_picks=[];
  s.feed.entitlements={daily_pick_count:4,sections:{
    top200:{enabled:true,total:2,returned:2,visible_picks:'ALL',see_all:true},
    daily:{enabled:true,total:2,returned:2,visible_picks:'ALL',see_all:true},
    prime:{enabled:true,total:1,returned:1,visible_picks:'ALL',see_all:true},
    value:{enabled:true,total:1,returned:1,visible_picks:'ALL',see_all:true},
    ace:{enabled:true,total:0,returned:0,visible_picks:'ALL',see_all:true},
    double_faults:{enabled:true,total:0,returned:0,visible_picks:'ALL',see_all:true},
    doubles:{enabled:true,total:0,returned:0,visible_picks:'ALL',see_all:true},
    games:{enabled:true,total:0,returned:0,visible_picks:'ALL',see_all:true},
    sets:{enabled:true,total:0,returned:0,visible_picks:'ALL',see_all:true}
  }};
  s.feed.performance={accuracy:.73};
  s.feed.dashboard_model_success={accuracy:.73};

  const resultRow=(id,tour,correct)=>({
    event_id:id,tour,surface:tour==='ATP'?'clay':'hard',scheduled_at:'2026-10-01T14:00:00+02:00',
    tournament:tour==='ATP'?'ATP Masters 1000 Shanghai':'WTA 1000 Wuhan',
    player1:{id:id+'-p1',name:tour==='ATP'?'Alejandro Fernández de la Cruz':'Caroline Dolehide',country_code:tour==='ATP'?'ESP':'USA'},
    player2:{id:id+'-p2',name:tour==='ATP'?'Maximiliano Alessandro Dimitrov':'Kate Fakh',country_code:tour==='ATP'?'BUL':'USA'},
    market_publications:[{
      publication_key:id+'-pub',section:correct?'top200':'value',market:'match_winner',issued_at:'2026-09-30T18:00:00Z',
      selection:tour==='ATP'?'Alejandro Fernández de la Cruz':'Caroline Dolehide',selection_id:id+'-p1',
      model_probability:correct ? .66 : .58,odds:correct ? 1.66 : 1.84,price_status:'priced',
      result:{status:correct?'hit':'miss',correct,staked_units:1,profit_units:correct ? .66 : -1}
    }]
  });
  s.feed.results=[resultRow('res-atp-1','ATP',true),resultRow('res-wta-1','WTA',false),resultRow('res-atp-2','ATP',false),resultRow('res-wta-2','WTA',true)];

  document.querySelector('#insightShortcut').hidden=false;
  document.querySelector('#topUpgradeButton').hidden=false;
  document.querySelector('#insightBell').hidden=false;
  t.renderHeroBanner();
  t.renderDashboardKpis();
  t.setRoute('predictions',false);
  t.renderDailyHub();
  t.wireDailyHub();
  return true;
}"""


def boot_fixture(page):
    page.goto(ORIGIN + "/mobile-preview.html?lang=sk", wait_until="networkidle")
    page.wait_for_function("window.mobilePreviewTest && mobilePreviewTest.state.ui")
    page.evaluate(FIXTURE)
    page.wait_for_selector("#dailyHubBody tr[data-hub-event]")
    page.wait_for_timeout(120)


def assert_mobile_geometry(page, width, label):
    report=page.evaluate("""() => ({
      htmlOverflow:document.documentElement.scrollWidth-innerWidth,
      bodyOverflow:document.body.scrollWidth-innerWidth,
      navDisplay:getComputedStyle(document.querySelector('#mobileTabs')).display,
      header:document.querySelector('.reference-topbar').getBoundingClientRect().toJSON(),
      hero:document.querySelector('#dashboardHero').getBoundingClientRect().toJSON(),
      first:document.querySelector('#dailyHubBody tr[data-hub-event]')?.getBoundingClientRect().toJSON(),
      actions:['#insightShortcut','#topUpgradeButton','#insightBell','#profileButton']
        .map(s=>document.querySelector(s)).filter(e=>e&&!e.hidden&&getComputedStyle(e).display!=='none')
        .map(e=>({w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}))
    })""")
    assert report["htmlOverflow"] <= 2, (label, report)
    assert report["bodyOverflow"] <= 2, (label, report)
    assert report["navDisplay"] != "none", (label, report)
    assert report["hero"]["top"] >= report["header"]["bottom"] - 2, (label, report)
    assert report["first"] and report["first"]["right"] <= width + 2, (label, report)
    assert all(a["w"] >= 43 and a["h"] >= 43 for a in report["actions"]), (label, report)


def main():
    main_html=(WEB / "index.html").read_text(encoding="utf-8")
    preview_html=(WEB / "mobile-preview.html").read_text(encoding="utf-8")
    assert 'data-mobile-preview="true"' not in main_html
    assert '/mobile-preview.css' not in main_html
    assert 'data-mobile-preview="true"' in preview_html
    assert '/mobile-preview.css' in preview_html

    SHOT_DIR.mkdir(parents=True,exist_ok=True)
    viewports=[(320,640,"phone-320"),(360,760,"phone-360"),(390,844,"phone-390"),(430,900,"phone-430"),(768,900,"tablet-768"),(900,700,"tablet-900")]
    executable=os.getenv("BLINQ_BROWSER") or browser_path()
    with sync_playwright() as pw:
        browser=(pw.chromium.launch(headless=True,executable_path=executable) if executable else pw.chromium.launch(headless=True))
        try:
            for width,height,label in viewports:
                context=browser.new_context(viewport={"width":width,"height":height},is_mobile=width<=900,has_touch=width<=900)
                page=context.new_page();errors=[];page.on("pageerror",lambda e,errors=errors:errors.append(str(e)))
                page.route("**/*",route_request);boot_fixture(page)
                assert_mobile_geometry(page,width,label)
                assert not errors,(label,errors)
                context.close()

            context=browser.new_context(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
            page=context.new_page();errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
            page.route("**/*",route_request);boot_fixture(page)
            page.screenshot(path=str(SHOT_DIR/"01-predictions-390.png"),full_page=False)

            initial=page.locator("#dailyHubBody tr[data-hub-event]").first.get_attribute("data-hub-event")
            prime=page.locator('#dailyHubTabs [data-daily-hub-tab="prime"]')
            assert prime.count()==1
            prime.click();page.wait_for_timeout(80)
            assert page.evaluate("mobilePreviewTest.state.dailyHubTab") == "prime"
            changed=page.locator("#dailyHubBody tr[data-hub-event]").first.get_attribute("data-hub-event")
            assert changed and changed != initial,(initial,changed)

            page.evaluate("window.scrollTo(0,Math.min(240,document.documentElement.scrollHeight-innerHeight))")
            before_scroll=page.evaluate("window.scrollY")
            row=page.locator("#dailyHubBody tr[data-hub-event]").first
            row.click();page.wait_for_function("document.querySelector('#matchDialog')?.open === true")
            dialog_text=page.locator("#dialogContent").inner_text()
            assert "Aryna Sabalenka" in dialog_text and "Coco Gauff" in dialog_text,dialog_text[:500]
            page.screenshot(path=str(SHOT_DIR/"04-detail-390.png"),full_page=False)
            page.locator("#dialogClose").click();page.wait_for_function("document.querySelector('#matchDialog')?.open === false")
            page.wait_for_timeout(100)
            assert page.evaluate("mobilePreviewTest.state.dailyHubTab") == "prime"
            after_scroll=page.evaluate("window.scrollY")
            assert abs(after_scroll-before_scroll) <= 3,(before_scroll,after_scroll)
            assert page.evaluate("document.activeElement?.matches('#dailyHubBody tr[data-hub-event]')") is True

            page.evaluate("window.scrollTo(0,Math.min(180,document.documentElement.scrollHeight-innerHeight))")
            prediction_scroll=page.evaluate("window.scrollY")
            page.evaluate("mobilePreviewTest.setRoute('results',false)");page.wait_for_selector(".results-preview-titlebar")
            page.screenshot(path=str(SHOT_DIR/"02-results-390.png"),full_page=False)
            page.evaluate("window.scrollTo(0,Math.min(260,document.documentElement.scrollHeight-innerHeight))")
            page.evaluate("mobilePreviewTest.setRoute('predictions',false)");page.wait_for_timeout(100)
            restored=page.evaluate("window.scrollY")
            assert abs(restored-prediction_scroll) <= 3,(prediction_scroll,restored)
            page.evaluate("mobilePreviewTest.setRoute('results',false)");page.wait_for_selector(".results-preview-titlebar")

            toggle=page.locator("[data-results-filter-toggle]");toggle.click()
            page.wait_for_selector(".results-filter-shell.is-open")
            applied_before=page.evaluate("JSON.stringify(mobilePreviewTest.state.resultsFilters)")
            page.locator("#resultsTour").select_option("WTA")
            assert page.evaluate("JSON.stringify(mobilePreviewTest.state.resultsFilters)") == applied_before
            page.locator(".results-filter-sheet-head [data-results-filter-close]").click()
            toggle.click();assert page.locator("#resultsTour").input_value()==""
            page.locator("#resultsTour").select_option("ATP")
            page.screenshot(path=str(SHOT_DIR/"03-filters-390.png"),full_page=False)
            page.locator("[data-results-filter-apply]").click();page.wait_for_timeout(100)
            assert page.evaluate("mobilePreviewTest.state.resultsFilters.tour") == "ATP"
            assert page.locator(".results-table tbody tr.results-card-row").count()==2
            assert page.evaluate("mobilePreviewTest.state.resultsPage") == 0

            page.locator("[data-results-filter-toggle]").click()
            page.locator("[data-results-filter-reset]").click()
            assert page.locator("#resultsTour").input_value()==""
            assert page.evaluate("mobilePreviewTest.state.resultsFilters.tour") == "ATP"
            page.locator(".results-filter-sheet-head [data-results-filter-close]").click()
            page.locator("[data-results-filter-toggle]").click()
            assert page.locator("#resultsTour").input_value()=="ATP"
            page.locator("[data-results-filter-reset]").click();page.locator("[data-results-filter-apply]").click()
            assert page.evaluate("mobilePreviewTest.state.resultsFilters.tour") == ""
            assert page.locator(".results-table tbody tr.results-card-row").count()==4

            page.evaluate("mobilePreviewTest.setRoute('predictions',false)")
            page.locator('#mobileTabs [data-route="account"]').click()
            page.wait_for_function("document.querySelector('#accountDialog')?.open === true")
            assert page.evaluate("mobilePreviewTest.state.route") == "predictions"
            page.locator("#accountDialogClose").click()
            assert not errors,errors
            context.close()

            for width in (1024,1440):
                context=browser.new_context(viewport={"width":width,"height":900})
                page=context.new_page();errors=[];page.on("pageerror",lambda e,errors=errors:errors.append(str(e)))
                page.route("**/*",route_request);boot_fixture(page)
                nav_display=page.locator("#mobileTabs").evaluate("e=>getComputedStyle(e).display")
                assert nav_display == "none",(width,nav_display)
                assert page.evaluate("document.documentElement.scrollWidth-innerWidth") <= 2,width
                assert not errors,(width,errors)
                context.close()
        finally:
            browser.close()
    print(f"BlinQ secondary mobile preview contract: PASS · screenshots={SHOT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
