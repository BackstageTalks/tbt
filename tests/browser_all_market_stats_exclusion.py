"""Chromium regression: independent STATS switches for all eight markets.

Synthetic admin configuration only. No real users, publications or API writes.
"""
import os
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


CATEGORIES = ("daily", "prime", "value", "ace", "double_faults", "doubles", "games", "sets")
MARKETS = dict(zip(CATEGORIES, ("top_daily", "prime", "value", "ace", "double_faults", "doubles", "games", "sets")))


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        assert source.count("  boot();") == 1
        injection = (
            "  window.marketHarness={state,renderAdminRoute,wireAdmin,statsExcludedSections};\n"
            "  boot();"
        )
        route.fulfill(content_type="application/javascript", body=source.replace("  boot();", injection))
    else:
        static_route(route)


def test_width(browser, width):
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.route("**/*", route_request)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
    page.wait_for_function("window.marketHarness && marketHarness.state.ui")
    page.evaluate("""() => {
      document.querySelector('#bootSplash')?.remove();
      document.querySelector('#cookieConsent')?.remove();
      document.querySelectorAll('dialog[open]').forEach(d=>d.close());
      const shell=document.getElementById('appShell'),host=document.getElementById('routePanel');
      shell.hidden=false;host.hidden=false;
      document.body.classList.remove('blinq-home');
      document.body.classList.add('blinq-admin');
      const h=marketHarness,s=h.state;
      s.route='admin';s.adminTab='layout';s.adminPlan='elite';s.uiStorageAvailable=false;
      host.innerHTML=h.renderAdminRoute();h.wireAdmin();
    }""")
    assert page.locator("[data-admin-market-exclude-stats]").count() == 8
    assert page.locator('[data-admin-hub-tab-card="see_all"] [data-admin-market-exclude-stats]').count() == 0

    # Clicking a category's option updates only its own global switch.
    for category, section in MARKETS.items():
        card = page.locator(f'[data-admin-hub-tab-card="{category}"]')
        card.locator("details > summary").click()
        checkbox = card.locator(f'[data-admin-market-exclude-stats="{category}"]')
        assert checkbox.is_visible() and not checkbox.is_disabled()
        assert not checkbox.is_checked()
        checkbox.check()
        assert page.evaluate(
            "(tab)=>marketHarness.state.ui.dashboard.daily_hub.tabs[tab].exclude_from_stats===true",
            category
        )
        excluded = page.evaluate("Array.from(marketHarness.statsExcludedSections()).sort()")
        assert section in excluded and len(excluded) == CATEGORIES.index(category) + 1
        assert page.locator(f'[data-admin-hub-tab-card="{category}"] .admin-daily-category small').inner_text() == "Web zapnutý · STATS vypnuté"

    assert page.evaluate("marketHarness.state.ui.dashboard.daily_hub.tabs.see_all.exclude_from_stats===undefined")
    # Turning a category globally OFF must force STATS OFF, even if its own
    # checkbox was previously unchecked.
    section = page.locator('[data-admin-hub-tab-card="value"]')
    section.locator("details > summary").click()
    section.locator('[data-admin-market-exclude-stats="value"]').uncheck()
    assert "value" not in page.evaluate("Array.from(marketHarness.statsExcludedSections())")
    section = page.locator('[data-admin-hub-tab-card="value"]')
    section.locator('[data-admin-hub-global-field="enabled"]').uncheck()
    section = page.locator('[data-admin-hub-tab-card="value"]')
    section.locator("details > summary").click()
    checkbox = section.locator('[data-admin-market-exclude-stats="value"]')
    assert checkbox.is_checked() and checkbox.is_disabled()
    assert "value" in page.evaluate("Array.from(marketHarness.statsExcludedSections())")
    assert page.locator('[data-admin-hub-tab-card="value"] .admin-daily-category small').inner_text() == "Web + STATS vypnuté"

    # An ordinary per-level SHOW/HIDE restriction is not a global STATS gate.
    page.locator('[data-admin-plan-chip="rookie"]').click()
    assert page.evaluate(
        "marketHarness.state.ui.dashboard.daily_hub.tabs.prime.exclude_from_stats===true"
    )
    assert page.locator("[data-admin-market-exclude-stats]").count() == 8
    assert page.evaluate("marketHarness.state.ui.dashboard.daily_hub.tabs.daily.enabled===true")
    assert page.evaluate("marketHarness.state.ui.dashboard.daily_hub.tabs.value.enabled===false")

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), width
    assert not errors, (width, errors)
    print("PASS per-market STATS toggles", width)
    page.close()


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, executable_path=os.getenv("BLINQ_BROWSER") or browser_path()
        )
        try:
            for width in (390, 768, 1440):
                test_width(browser, width)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
