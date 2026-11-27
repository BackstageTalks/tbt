"""Offline Chromium regression for the tournament stats popup."""
import pytest

pytest.importorskip("playwright")  # backend CI has no browser stack
from playwright.sync_api import sync_playwright  # noqa: E402

from browser_runtime_r43 import ORIGIN, browser_path, static_route


STATS = [
    {"id": "accuracy", "title": "Úspešnosť",
     "items": [{"label": "Správne predikcie", "value": "50,0 %", "hint": "1 z 2 vyhodnotených"}]},
    {"id": "extension", "title": "Ďalšie ukazovatele",
     "items": [{"label": "Test sekcie", "value": "2"}]},
]


@pytest.mark.parametrize("width", [390, 1440])
def test_tournament_popup(width):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=browser_path())
        context = browser.new_context(viewport={"width": width, "height": 900})

        def route_request(route):
            if route.request.url == ORIGIN + "/bracket-test":
                return route.fulfill(content_type="text/html; charset=utf-8", body="""
                    <!doctype html><html lang="sk"><meta charset="utf-8">
                    <link rel="stylesheet" href="/bracket.css">
                    <link rel="stylesheet" href="/blinq-desktop.css" media="(min-width: 901px)">
                    <body id="blinqPremium"><main id="host"></main>
                    <script src="/bracket.js"></script></body></html>
                """)
            return static_route(route)

        context.route("**/*", route_request)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(ORIGIN + "/bracket-test")
        page.evaluate("""sections => {
            window.calls = 0;
            window.BlinqAuth = {tournamentBrackets: async () => {
                window.calls += 1;
                return {schema:1, analysis_allowed:true, tournaments:[
                    {id:'fixture', name:'Fixture Open', draws:[], tournament_stats:sections}
                ]};
            }};
            return window.BlinqBracket.open(document.querySelector('#host'));
        }""", STATS)
        badge = page.get_by_role("button", name="Štatistiky turnaja")
        assert badge.inner_text() == "🎯 50,0 %"
        panel_box = page.get_by_role("tabpanel").bounding_box()
        badge_box = badge.bounding_box()
        assert 0 < panel_box["x"] + panel_box["width"] - badge_box["x"] - badge_box["width"] < 25
        assert 0 < panel_box["y"] + panel_box["height"] - badge_box["y"] - badge_box["height"] < 25
        popup = page.get_by_role("dialog", name="Štatistiky turnaja")

        for dismiss in ("escape", "button", "outside"):
            badge.click()
            popup.wait_for(state="visible")
            assert popup.get_by_text("1 z 2 vyhodnotených").is_visible()
            assert popup.get_by_text("Ďalšie ukazovatele").is_visible()
            box = popup.bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= width
            if width == 390:
                assert box["width"] == width and abs(box["y"] + box["height"] - 900) <= 1
            else:
                assert abs(box["x"] + box["width"] / 2 - width / 2) <= 1
            if dismiss == "escape":
                page.keyboard.press("Escape")
            elif dismiss == "button":
                popup.get_by_role("button", name="Zavrieť").click()
            else:
                page.mouse.click(4, 4)
            popup.wait_for(state="detached")
            assert badge.evaluate("node => document.activeElement === node")

        assert page.evaluate("window.calls") == 1
        assert errors == []
        browser.close()

def test_match_dialog_fits_mobile_and_preserves_focus():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=browser_path())
        context = browser.new_context(viewport={"width": 390, "height": 560})

        def route_request(route):
            if route.request.url == ORIGIN + "/bracket-test":
                return route.fulfill(content_type="text/html; charset=utf-8", body="""
                    <!doctype html><html lang="sk"><meta charset="utf-8">
                    <link rel="stylesheet" href="/bracket.css">
                    <body id="blinqPremium"><main id="host"></main>
                    <script src="/bracket.js"></script></body></html>
                """)
            return static_route(route)

        context.route("**/*", route_request)
        page = context.new_page()
        page.goto(ORIGIN + "/bracket-test")
        page.evaluate("""() => {
            const players = [{id:'a', name:'Player A'}, {id:'b', name:'Player B'}];
            const match = {id:'m', event_id:'m', players};
            window.BlinqAuth = {tournamentBrackets: async () => ({
                schema:1, analysis_allowed:true, tournaments:[{
                    id:'fixture', name:'Fixture Open',
                    draws:[{id:'main', rounds:[{name:'Final', matches:[match]}]}]
                }]
            })};
            return window.BlinqBracket.open(document.querySelector('#host'),
                [{event_id:'m', selection:'Player A'.repeat(40)}], null, {});
        }""")
        assert page.get_by_role("button", name="Analýza · Player A – Player B").bounding_box()["height"] >= 44
        match = page.get_by_role("button", name="Player A Player B", exact=True)
        match.click()
        panel = page.get_by_role("dialog", name="Zápas")
        close = panel.get_by_role("button", name="Zavrieť")
        panel.wait_for(state="visible")
        box = panel.bounding_box()
        close_box = close.bounding_box()
        assert box["x"] == 0 and box["width"] == 390
        assert abs(box["y"] + box["height"] - 560) <= 1
        assert close_box["width"] >= 44 and close_box["x"] + close_box["width"] <= 390
        assert panel.evaluate("node => node.scrollWidth === node.clientWidth")
        page.keyboard.press("Escape")
        panel.wait_for(state="detached")
        assert match.evaluate("node => document.activeElement === node")
        browser.close()
