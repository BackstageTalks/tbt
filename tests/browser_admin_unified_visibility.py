"""Offline Chromium regression: per-plan visibility has ONE editor in Zobrazenie.

Uses only bundled UI defaults and synthetic state. Does not publish or access user data.
"""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source=(WEB / "app.js").read_text(encoding="utf-8")
        injection="  window.unifiedHarness={state,renderAdminRoute,renderAdminLayout,renderAdminLevels,wireAdmin};\n  boot();"
        assert source.count("  boot();")==1
        route.fulfill(content_type="application/javascript",body=source.replace("  boot();",injection))
    else:
        static_route(route)


def inspect(browser,width):
    page=browser.new_page(viewport={"width":width,"height":900})
    page.route("**/*",route_request)
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)))
    page.goto(ORIGIN+"/index.html?lang=sk",wait_until="networkidle")
    page.wait_for_function("window.unifiedHarness && unifiedHarness.state.ui")
    page.evaluate("""() => {
      document.querySelector('#bootSplash')?.remove();
      document.querySelector('#cookieConsent')?.remove();
      document.querySelectorAll('dialog[open]').forEach(d=>d.close());
      const shell=document.getElementById('appShell'),host=document.getElementById('routePanel');
      shell.hidden=false;host.hidden=false;
      document.body.classList.remove('blinq-home');document.body.classList.add('blinq-admin');
      const h=unifiedHarness,s=h.state;s.route='admin';s.adminTab='layout';s.adminPlan='elite';
      s.uiStorageAvailable=false; // Never publish, even accidentally.
      host.innerHTML=h.renderAdminRoute();h.wireAdmin();
    }""")
    # Exactly one set of editable permissions for the selected membership tier.
    for key in ("comparator","results","detail"):
        assert page.locator(f'[data-admin-display-access="{key}"]').count()==1,(width,key)
    assert page.locator('[data-admin-display-history]').count()==1
    assert page.locator('[data-admin-detail-section]').count()==3
    assert page.locator('[data-admin-results-plan], [data-admin-level-access], [data-admin-level-hub-field]').count()==0
    # Preserve the deployed baseline: lower tiers may already have Results locked.
    keys=("comparator","results","detail")
    baseline={key:page.locator(f'[data-admin-display-access="{key}"]').is_checked()
              for key in keys}
    for key,old in baseline.items():
        node=page.locator(f'[data-admin-display-access="{key}"]')
        if old:
            node.uncheck()
        else:
            node.check()
        assert node.is_checked() is not old,(width,key)
    page.locator('[data-admin-display-history]').select_option('7d')
    assert page.locator('[data-admin-display-history]').input_value()=='7d'

    # Changes on ELITE never silently propagate to ROOKIE, PRO, or other levels.
    page.locator('[data-admin-plan-chip="rookie"]').click()
    rookie_before=page.locator('[data-admin-display-access="comparator"]').is_checked()
    if rookie_before:
        page.locator('[data-admin-display-access="comparator"]').uncheck()
    else:
        page.locator('[data-admin-display-access="comparator"]').check()
    assert page.evaluate(
        '(desired)=>unifiedHarness.state.ui.dashboard.comparator.plans.rookie===desired',
        not rookie_before,
    )
    assert page.evaluate(
        '(desired)=>unifiedHarness.state.ui.dashboard.comparator.plans.trial===desired',
        not rookie_before,
    )
    page.locator('[data-admin-plan-chip="elite"]').click()
    for key,old in baseline.items():
        assert page.locator(f'[data-admin-display-access="{key}"]').is_checked() is not old,(width,key)
    assert page.locator('[data-admin-display-history]').input_value()=='7d'
    assert page.evaluate('unifiedHarness.state.ui.dashboard.results_history_window.elite==="7d"')
    assert page.evaluate('unifiedHarness.state.ui.dashboard.comparator.plans.pro!==false')

    # Global detail section minima are editable here, not in Členstvá.
    page.locator('.admin-display-global-detail summary').click()
    assert page.locator('[data-admin-detail-section="radar"]').is_visible()

    # EXPIRED is a read-only access context.
    page.locator('[data-admin-plan-chip="expired"]').click()
    assert page.locator('[data-admin-display-access="comparator"]').is_disabled()
    assert page.locator('[data-admin-display-history]').is_disabled()
    page.locator('[data-admin-plan-chip="elite"]').click()

    # Membership plan cards expose metadata & one direct navigation action,
    # never a duplicated board or access editor.
    page.evaluate("""() => {
      const h=unifiedHarness;h.state.adminTab='levels';
      document.getElementById('routePanel').innerHTML=h.renderAdminRoute();
      h.wireAdmin();
    }""")
    assert page.locator('[data-admin-level-access],[data-admin-level-history],[data-admin-level-hub-field]').count()==0
    assert page.locator('[data-admin-display-access]').count()==0
    assert page.locator('[data-admin-level-field="label"]').count()==5
    page.locator('[data-admin-level-plan="pro"] > summary').click()
    page.locator('[data-admin-open-level-display="pro"]').click()
    assert page.evaluate('unifiedHarness.state.adminTab==="layout"')
    assert page.evaluate('unifiedHarness.state.adminPlan==="pro"')
    assert page.locator('.admin-display-access-panel h3').inner_text().startswith('Čo môže otvoriť')
    assert page.locator('[data-admin-display-access="comparator"]').is_checked()

    # On narrow screens, settings do not create horizontal overflow.
    overflow=page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
    assert overflow<=1,(width,overflow)
    assert not errors,(width,errors)
    page.close()


def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,
                                   executable_path=os.getenv("BLINQ_BROWSER") or browser_path())
        try:
            for width in (390,768,1280,1440):
                inspect(browser,width)
                print('PASS unified account visibility at',width)
        finally:
            browser.close()


if __name__=="__main__":
    main()
