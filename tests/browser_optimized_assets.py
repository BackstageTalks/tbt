"""Real Chromium check of frontend minification and membership access.

Compares stable computed geometry/style from untouched sources against the
optimized deploy asset. Authenticated membership cases are deterministic
fixtures; they do not use live Firebase accounts or touch CDB.
"""
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import ORIGIN, WEB, browser_path, static_route

OPT = Path(os.environ.get("BLINQ_OPTIMIZED_ASSET_DIR", "/tmp/blinq-optimized-web"))
MARKER = "  boot();"


def intercept(route, optimized=False, harness=False):
    path = urlparse(route.request.url).path
    if optimized and path in ("/app.js", "/blinq-app.css"):
        route.fulfill(
            content_type="application/javascript" if path.endswith(".js") else "text/css",
            body=(OPT / path.lstrip("/")).read_bytes(),
        )
    elif harness and path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        assert source.count(MARKER) == 1
        source = source.replace(MARKER, """
  window.memberAudit={state,renderNavigation,applyAccessStates,
    resultsAccessAllowed,resultsServerAccessMismatch,comparatorPlanAllowed};
""" + MARKER)
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


def snapshot(browser, width, optimized):
    page = browser.new_page(viewport={"width": width, "height": 844})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.route("**/*", lambda route: intercept(route, optimized=optimized))
    page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
    page.wait_for_selector("#dailyHubHead", state="attached")
    result = page.evaluate("""() => {
      const style = sel => {
        const node = document.querySelector(sel);
        if(!node)return null;
        const s=getComputedStyle(node),r=node.getBoundingClientRect();
        return {
          display:s.display,position:s.position,color:s.color,background:s.backgroundColor,
          fontSize:s.fontSize,gridTemplateColumns:s.gridTemplateColumns,
          borderRadius:s.borderRadius,marginTop:s.marginTop,paddingTop:s.paddingTop,
          width:Math.round(r.width*10)/10,height:Math.round(r.height*10)/10
        };
      };
      return {
        lang:document.documentElement.lang,
        overflow:document.documentElement.scrollWidth-innerWidth,
        activeTabs:document.querySelectorAll('#dailyHubTabs .daily-hub-tab').length,
        items:Object.fromEntries(['#appShell','.site-header','#dailyHub','#dailyHubHead',
          '#dailyHubTabs','#mobileTabs','.boot-splash',
          '#resultsPreviewPanel'].map(sel=>[sel,style(sel)]))
      };
    }""")
    assert not errors, (width, optimized, errors)
    assert result["overflow"] <= 2, result
    page.close()
    return result


def audit_members(browser, width):
    page = browser.new_page(viewport={"width": width, "height": 844})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.route("**/*", lambda route: intercept(route, harness=True))
    page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
    page.wait_for_function("window.memberAudit && window.memberAudit.state.ui")
    cases = [
        ("rookie", False, False, False),
        ("pro", True, True, False),
        ("elite", True, True, False),
        ("legend", True, True, True),
        ("goat", True, True, True),
        ("pro", False, False, False),
        ("admin", False, True, True),
    ]
    for plan, server, results_allowed, comparator_allowed in cases:
        outcome = page.evaluate("""([plan, server]) => {
          const audit=window.memberAudit;
          const admin=plan==='admin';
          audit.state.feed.account={status:'active',plan,
            role:admin?'admin':'member',is_admin:admin};
          audit.state.feed.entitlements={results:server};
          audit.renderNavigation();audit.applyAccessStates();
          const result=document.querySelector('#mobileTabs [data-route="results"]');
          const compare=document.querySelector('#mobileTabs [data-route="compare"]');
          return {
            results:audit.resultsAccessAllowed(),
            comparator:audit.comparatorPlanAllowed(),
            mismatch:audit.resultsServerAccessMismatch(),
            resultsLocked:result?.classList.contains('access-nav-locked'),
            comparatorLocked:compare?.classList.contains('comparator-nav-locked'),
            resultsUpgrade:result?.dataset.upgradePlan||null,
            oldRouteNodes:document.querySelectorAll('[data-route="top200"]').length,
            oldSection:Boolean(audit.state.ui.dashboard.sections.top200)
          };
        }""", [plan, server])
        assert outcome["results"] is results_allowed, (width, plan, outcome)
        assert outcome["comparator"] is comparator_allowed, (width, plan, outcome)
        assert outcome["resultsLocked"] is (not results_allowed), (width, plan, outcome)
        assert outcome["comparatorLocked"] is (not comparator_allowed), (width, plan, outcome)
        assert outcome["oldRouteNodes"] == 0 and not outcome["oldSection"], outcome
        if plan == "pro" and not server:
            assert outcome["mismatch"] and outcome["resultsUpgrade"] is None, outcome
    assert not errors, (width, errors)
    page.close()


def main():
    assert (OPT / "app.js").is_file() and (OPT / "blinq-app.css").is_file()
    with sync_playwright() as pw:
        executable = browser_path()
        browser = pw.chromium.launch(headless=True, executable_path=executable) if executable else pw.chromium.launch(headless=True)
        try:
            for width in (390, 1440):
                before = snapshot(browser, width, optimized=False)
                after = snapshot(browser, width, optimized=True)
                assert before == after, (width, before, after)
                audit_members(browser, width)
        finally:
            browser.close()
    print("Optimized CSS/JS browser parity and 7 membership cases x 2 viewports: PASS")


if __name__ == "__main__":
    main()
