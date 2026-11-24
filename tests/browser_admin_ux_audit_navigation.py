"""Synthetic Chromium audit for BlinQ Admin navigation and operational safety.

No private account data, API write requests, model operations or deployment.
"""
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source=(WEB / "app.js").read_text(encoding="utf-8")
        injection="  window.adminAuditHarness={state,renderAdminRoute,wireAdmin};\n  boot();"
        assert source.count("  boot();")==1
        route.fulfill(content_type="application/javascript",
                      body=source.replace("  boot();",injection))
    else:
        static_route(route)


def test_width(browser,width):
    page=browser.new_page(viewport={"width":width,"height":900})
    page.route("**/*",route_request)
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)))
    page.goto(ORIGIN+"/index.html?lang=sk",wait_until="networkidle")
    page.wait_for_function("window.adminAuditHarness && adminAuditHarness.state.ui")
    page.evaluate("""() => {
      document.querySelector('#bootSplash')?.remove();
      document.querySelector('#cookieConsent')?.remove();
      document.querySelectorAll('dialog[open]').forEach(d=>d.close());
      const shell=document.getElementById('appShell'),host=document.getElementById('routePanel');
      shell.hidden=false;host.hidden=false;document.body.classList.remove('blinq-home');
      document.body.classList.add('blinq-admin');
      const h=adminAuditHarness,s=h.state;
      s.route='admin';s.adminTab='layout';s.adminPlan='elite';
      s.adminLayoutView='access';s.uiStorageAvailable=false; // no publish
      s.adminInsights=[];s.adminInfoResults=[];s.adminLiveResults=[];
      s.adminHistoryRetention={info:0,comeback:0,set2:0};
      s.adminInsightsLoading=false;s.adminInfoResultsLoading=false;s.adminLiveResultsLoading=false;
      host.innerHTML=h.renderAdminRoute();h.wireAdmin();
    }""")
    # Mobile Admin no longer has two framed wallpaper cards stacked above
    # Accounts. Desktop's deliberately framed navigation is unchanged.
    panel_style=page.evaluate("""() => {
      const css=sel => getComputedStyle(document.querySelector(sel));
      const nav=css('.admin-side-nav'),work=css('.admin-workarea');
      const content=css('.admin-panel-v685');
      return {
        navImage:nav.backgroundImage,navBorder:nav.borderTopWidth,navShadow:nav.boxShadow,
        workImage:work.backgroundImage,workBorder:work.borderTopWidth,
        workShadow:work.boxShadow,contentBorder:content.borderTopWidth
      };
    }""")
    if width<=900:
        assert panel_style["navImage"]=="none",(width,panel_style)
        assert panel_style["navBorder"]=="0px",(width,panel_style)
        assert panel_style["navShadow"]=="none",(width,panel_style)
        assert panel_style["workImage"]=="none",(width,panel_style)
        assert panel_style["workBorder"]=="0px",(width,panel_style)
        assert panel_style["workShadow"]=="none",(width,panel_style)
        assert panel_style["contentBorder"]=="0px",(width,panel_style)
    else:
        assert "linear-gradient" in panel_style["navImage"],(width,panel_style)
        assert "url(" in panel_style["navImage"],(width,panel_style)
    # A real runtime/publishing alert must not be hidden by visual cleanup.
    assert page.locator('.admin-runtime-note.is-error[role="alert"]').is_visible()
    assert page.locator(".admin-nav-toolbar [data-admin-nav-expand]").count()==1
    assert page.locator(".admin-nav-entry.is-active").count()==1
    if os.getenv("BLINQ_SCREENSHOTS") and width in (390,1440):
        from pathlib import Path
        out=Path(os.environ["BLINQ_SCREENSHOTS"])
        out.mkdir(parents=True,exist_ok=True)
        page.locator(".admin-side-nav").screenshot(path=str(out/f"admin-sekcie-menu-{width}.png"))

    # Zobrazenie: only focused view is displayed, never duplicate permissions.
    assert page.locator('[data-admin-subtab^="layout:"]').count()==3
    assert page.locator('[data-admin-subpanel="layout:access"]:visible').count()==1
    assert page.locator('[data-admin-subpanel="layout:daily"]:visible').count()==0
    assert page.locator('[data-admin-display-access]').count()==3
    page.locator('[data-admin-subtab="layout:daily"]').click()
    assert page.locator('[data-admin-subpanel="layout:access"]:visible').count()==0
    assert page.locator('[data-admin-subpanel="layout:daily"]:visible').count()==2
    assert page.locator('[data-admin-subpanel="layout:order"]:visible').count()==0
    assert page.locator('[data-admin-daily-preset="full"]').is_visible()
    page.locator('[data-admin-subtab="layout:order"]').click()
    assert page.locator('.admin-tab-sort-shell').is_visible()
    assert page.locator('.admin-daily-matrix-card').is_hidden()
    page.locator('[data-admin-subtab="layout:access"]').click()
    assert page.locator('[data-admin-display-access="results"]').is_visible()
    assert page.locator('[data-admin-subtab="layout:access"]').get_attribute('aria-pressed')=='true'
    assert page.locator('[data-admin-subtab="layout:order"]').get_attribute('aria-pressed')=='false'

    # The ownership guide describes all eleven admin destinations and can
    # navigate without changing the underlying UI config.
    before=page.evaluate('JSON.stringify(adminAuditHarness.state.ui)')
    page.locator('[data-admin-guide-toggle]').click()
    assert page.locator('[data-admin-guide-tab]').count()==11
    assert page.locator('.admin-guide-map').is_visible()
    assert 'Publikovať' in page.locator('.admin-guide-map').inner_text()
    page.locator('[data-admin-guide-tab="layout"]').click()
    assert page.locator('.admin-guide-map').count()==0
    assert page.evaluate('adminAuditHarness.state.adminTab==="layout"')
    assert page.evaluate('JSON.stringify(adminAuditHarness.state.ui)')==before

    # INFO & LIVE: composer is preserved when moving between focused views;
    # destructive retention controls are not visible in normal publishing.
    page.evaluate("""() => {
      const h=adminAuditHarness,s=h.state;s.adminTab='insights';s.adminInsightsView='messages';
      document.getElementById('routePanel').innerHTML=h.renderAdminRoute();
      h.wireAdmin();
    }""")
    assert page.locator('[data-admin-subtab^="insights:"]').count()==4
    assert page.locator('#adminInsightForm').is_visible()
    assert page.locator('[data-admin-action="history-delete-all"]:visible').count()==0
    input_box=page.locator('[data-insight-custom-title]').first
    input_box.fill('Koncept pri prekliknutí')
    page.locator('[data-admin-subtab="insights:results"]').click()
    assert page.locator('#adminInsightForm').is_hidden()
    assert page.locator('.admin-info-management').is_visible()
    assert page.locator('[data-admin-action="history-delete-all"]:visible').count()==0
    page.locator('[data-admin-subtab="insights:retention"]').click()
    assert page.locator('.admin-history-management').is_visible()
    assert page.locator('[data-admin-action="history-delete-all"]:visible').count()==3
    assert page.locator('#adminInsightForm').is_hidden()
    page.locator('[data-admin-subtab="insights:messages"]').click()
    assert input_box.input_value()=='Koncept pri prekliknutí'
    assert page.locator('#adminInsightForm').is_visible()
    page.locator('[data-admin-subtab="insights:audience"]').click()
    assert page.locator('#adminInfoMinLevel').is_visible()
    assert page.locator('.admin-live-radar-card').is_visible()
    assert page.locator('[data-admin-action="history-delete-all"]:visible').count()==0

    # A new-message shortcut returns to the right panel.
    page.locator('[data-admin-action="insight-new"]').first.click()
    assert page.locator('#adminInsightForm').is_visible()
    assert page.locator('[data-admin-subtab="insights:messages"]').get_attribute('aria-pressed')=='true'
    # All 15 Admin destinations share the same neutral visual language.
    # This reads synthetic state only; no API writes, previews or publishing.
    tabs=('accounts','projects','levels','dashboard','offer','testresults','dataexport',
          'monthlyresults','layout','banners','telegram','tgbot','insights',
          'calibration','system')
    screenshots=os.getenv("BLINQ_SCREENSHOTS")
    for tab in tabs:
        style=page.evaluate("""tab => {
          const h=adminAuditHarness,s=h.state,host=document.querySelector('#routePanel');
          s.adminTab=tab;
          host.innerHTML=h.renderAdminRoute();
          const nav=document.querySelector('[data-admin-tab="'+tab+'"]');
          const palette=getComputedStyle(document.querySelector('.admin-console-v685'));
          return {
            tabCount:document.querySelectorAll('[data-admin-tab]').length,
            heading:document.querySelector('.admin-workarea-head h2')?.textContent?.trim(),
            active:Boolean(nav?.classList.contains('active')),
            accent:palette.getPropertyValue('--bq-admin-mint').trim(),
            navBg:nav?getComputedStyle(nav).backgroundColor:null,
            selectedMarker:nav?getComputedStyle(nav.querySelector('.admin-nav-mark')).backgroundColor:null,
            guideColor:getComputedStyle(document.querySelector('.admin-nav-toolbar button')).backgroundColor
          };
        }""",tab)
        assert style["tabCount"]==15,(width,tab,style)
        assert style["heading"] and style["active"],(width,tab,style)
        assert style["accent"]=="#70dab0",(width,tab,style)
        if width<=900:
            # No original green selected-section card; active marker remains.
            assert style["navBg"]=="rgba(0, 0, 0, 0)",(width,tab,style)
            assert style["selectedMarker"]!="rgba(0, 0, 0, 0)",(width,tab,style)
        else:
            assert style["navBg"]!="rgba(0, 0, 0, 0)",(width,tab,style)
        assert style["guideColor"]!="rgba(0, 0, 0, 0)",(width,tab,style)
        if screenshots and width in (390,1440) and tab in (
            'accounts','layout','banners','insights','calibration','system'):
            out=Path(screenshots)
            out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out / f"admin-theme-{tab}-{width}.png"))

    assert not errors,(width,errors)
    page.close()


def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,
                                   executable_path=os.getenv("BLINQ_BROWSER") or browser_path())
        try:
            for width in (390,768,1280,1440):
                test_width(browser,width)
                print("PASS admin task navigation / draft-safe INFO switch",width)
        finally:
            browser.close()


if __name__=="__main__":
    main()
