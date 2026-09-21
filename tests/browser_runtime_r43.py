"""Small real-browser release gate for BlinQ public runtime.

All requests are fulfilled from the committed web/ tree or deterministic API
fixtures, so the test never touches Firebase, Azure, SMTP or paid providers.
"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
import shutil
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ORIGIN = "http://blinq.test"


def browser_path() -> str | None:
    for candidate in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "microsoft-edge"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def static_route(route) -> None:
    parsed = urlparse(route.request.url)
    path = parsed.path
    if path.startswith("/api/v1/auth/config"):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "enabled": True,
            "provider": "firebase",
            "project_id": "blinq-182",
            "auth_domain": "blinq-182.firebaseapp.com",
            "server_ready": True,
            "release": "7.3.6",
        }))
        return
    if path.startswith("/api/v1/ui-config"):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"configured": False}))
        return
    rel = path.lstrip("/") or "index.html"
    target = (WEB / rel).resolve()
    if WEB.resolve() not in target.parents and target != WEB.resolve():
        route.fulfill(status=403, body="forbidden")
        return
    if not target.exists() or not target.is_file():
        route.fulfill(status=404, body="not found")
        return
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    route.fulfill(status=200, content_type=content_type, body=target.read_bytes())


def main() -> int:
    executable = browser_path()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=executable) if executable else pw.chromium.launch(headless=True)
        try:
            for width in (390, 1440):
                for locale in ("sk", "cz", "en"):
                    context = browser.new_context(viewport={"width": width, "height": 900})
                    context.route(f"{ORIGIN}/**", static_route)
                    page = context.new_page()
                    errors: list[str] = []
                    page.on("pageerror", lambda exc, errors=errors: errors.append(str(exc)))
                    page.goto(f"{ORIGIN}/index.html?lang={locale}", wait_until="networkidle")
                    page.wait_for_function("document.querySelector('#dailyHubHead') && document.querySelector('#telegramGroupsPanel')")
                    page.wait_for_timeout(100)
                    if errors:
                        raise AssertionError(f"{locale}/{width}: page errors: {errors}")
                    lang = page.evaluate("document.documentElement.lang")
                    expected_lang = "cs" if locale == "cz" else locale
                    assert lang == expected_lang, (locale, width, lang)
                    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                    assert overflow <= 1, (locale, width, overflow)
                    telegram = page.locator("#telegramGroupsPanel").inner_text()
                    cookies = page.locator("#cookieConsent").inner_text()
                    headers = page.locator("#dailyHubHead").inner_text()
                    hero = page.locator("#dashboardHero").inner_text()
                    if locale == "en":
                        joined = "\n".join((telegram, cookies, headers, hero))
                        for forbidden in (
                            "Telegram skupiny",
                            "Oficiálne BlinQ kanály",
                            "Viac o cookies",
                            "PREDIKCIA",
                            "TURNAJ",
                            "ZÁPAS",
                            "ČAS",
                            "TOP a VALUE predikcie",
                        ):
                            assert forbidden not in joined, (forbidden, joined)
                        assert "Telegram groups" in telegram
                        assert "More about cookies" in cookies
                    if locale == "cz":
                        joined = "\n".join((telegram, cookies, headers, hero))
                        assert "PREDIKCIA" not in joined
                        assert "Více o cookies" in cookies
                        assert "Oficiální BlinQ" in telegram
                    context.close()
        finally:
            browser.close()
    print("BlinQ r43 real-browser contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
