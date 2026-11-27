import pytest
import pytest

pytest.importorskip("playwright")  # backend CI has no browser stack
from playwright.sync_api import sync_playwright  # noqa: E402

from browser_runtime_r43 import ORIGIN, WEB, browser_path, static_route
from urllib.parse import urlparse


def fixture_route(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        source = source.replace(marker, "  window.cardTest={state,comparatorOfferFixtureId,comparatorResultHtml};\n" + marker)
        return route.fulfill(content_type="application/javascript", body=source)
    return static_route(route)


@pytest.mark.parametrize("width", [390, 1440])
def test_match_card(width):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=browser_path())
        page = browser.new_page(viewport={"width": width, "height": 900}, locale="sk-SK")
        page.route("**/*", fixture_route)
        page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
        page.wait_for_function("window.cardTest && document.getElementById('bootSplash') === null")
        page.evaluate("""() => {
            document.querySelector('#cookieConsent')?.remove();
            document.querySelectorAll('dialog[open]').forEach(d=>d.close());
            document.querySelector('#appShell').hidden=false;
            document.querySelector('#predictionsView').hidden=true;
            const host=document.querySelector('#routePanel'); host.hidden=false;
            const {state,comparatorOfferFixtureId,comparatorResultHtml}=window.cardTest;
            const row={event_id:'1234',player1:{id:'11'},player2:{id:'22'},tour:'ATP',surface:'hard',
                       scheduled_at:new Date(Date.now()+3600000).toISOString()};
            state.feed={daily_picks:[row],upcoming:[row]};
            if(comparatorOfferFixtureId('22','11','atp','hard')!=='1234') throw Error('fixture identity');
            state.feed.upcoming.push({...row,event_id:'1235'});
            if(comparatorOfferFixtureId('22','11','atp','hard')!=='') throw Error('ambiguous identity');
            window.fixture={tour:'atp',surface:'hard',
                player1:{player_id:'11',name:'Player One',probability:.67,stats:{
                    days_since_last_match:2,fatigue_7d:{matches:3,sets:7},fatigue_14d:{matches:5,sets:12}}},
                player2:{player_id:'22',name:'Player Two',probability:.33,stats:{}},
                match_context:{setting:'outdoor',court_speed:{value:104.2,matches:7},
                               blinq_probability:.67,odds:1.82,selection_id:'11'}};
            host.innerHTML=comparatorResultHtml(window.fixture);
        }""")
        card = page.locator(".comparator-result")
        facts = card.locator(".comparator-match-facts")
        for text in ("Vonku", "104", "BlinQ %", "1,82", "7 dní", "14 dní", "3 / 7", "5 / 12", "2 dní"):
            assert text in card.inner_text()
        assert facts.evaluate("node=>node.scrollWidth <= node.clientWidth")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.evaluate("""() => {
            window.fixture.match_context={};
            document.querySelector('#routePanel').innerHTML=cardTest.comparatorResultHtml(window.fixture);
        }""")
        assert facts.locator("dd").all_text_contents() == ["--"] * 4
        browser.close()
