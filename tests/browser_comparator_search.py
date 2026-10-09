"""Offline Chromium regression for live comparator name suggestions."""
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
            "  window.comparatorHarness={state,renderComparatorRoute,wireComparator};\n"
            + marker,
        )
        route.fulfill(content_type="application/javascript", body=source)
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, executable_path=os.getenv("BLINQ_BROWSER") or browser_path()
        )
        try:
            for width in (390, 1440):
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function(
                    "window.comparatorHarness && comparatorHarness.state.ui"
                )
                # Wait for the app's asynchronous boot/auth path to finish so it
                # cannot replace the manually mounted comparator during typing.
                page.wait_for_function("document.getElementById('bootSplash') === null")
                page.evaluate("""() => {
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelectorAll('dialog[open]').forEach(d=>d.close());
                    document.getElementById('appShell').hidden=false;
                    document.getElementById('routePanel').hidden=false;
                    const h=window.comparatorHarness;
                    h.state.route='compare';
                    h.state.comparator=null;
                    window.comparatorSearchCalls=[];
                    window.BlinqAuth.comparatorPlayers=async(query,tour) => {
                        window.comparatorSearchCalls.push({query,tour});
                        return {players:[
                            {player_id:'atp:novak',name:'Novak Djokovic',tour:'atp',matches_seen:100},
                            {player_id:'atp:novic',name:'Novak Novic',tour:'atp',matches_seen:8}
                        ]};
                    };
                    document.getElementById('routePanel').innerHTML=h.renderComparatorRoute();
                    h.wireComparator();
                }""")
                page.locator("#comparatorPlayer0").fill("Nov")
                page.wait_for_timeout(1200)
                diagnostic = page.evaluate("""() => ({
                    route: comparatorHarness.state.route,
                    seq: comparatorHarness.state.comparator?.searchSeq,
                    rows: comparatorHarness.state.comparator?.search?.[0],
                    query: document.querySelector('#comparatorPlayer0')?.value,
                    html: document.querySelector('#comparatorSearch0')?.innerHTML,
                    calls: window.comparatorSearchCalls
                })""")
                assert page.locator(".comparator-search-results button").count() == 2, (
                    width, diagnostic, errors
                )
                page.locator(".comparator-search-results button").first.click()
                assert page.locator("#comparatorPlayer0").input_value() == "Novak Djokovic"
                assert page.locator(".comparator-player-confirmed").count() == 1

                # API errors need inline feedback without destroying input focus.
                page.evaluate("""() => {
                    window.BlinqAuth.comparatorPlayers=async()=>{
                        const error=new Error('rate_limited');error.status=429;throw error;
                    };
                }""")
                page.locator("#comparatorPlayer1").fill("Rafe")
                page.locator("#comparatorSearch1 [role=alert]").wait_for()
                assert "Priveľa vyhľadávaní" in page.locator("#comparatorSearch1").inner_text()

                # Out-of-order results from the previous query must never overwrite
                # the newest suggestion list.
                page.evaluate("""() => {
                    window.pendingComparatorQueries={};
                    window.BlinqAuth.comparatorPlayers=(q)=>new Promise(resolve=>{
                        window.pendingComparatorQueries[q]=resolve;
                    });
                }""")
                page.locator("#comparatorPlayer1").fill("Rafa")
                page.wait_for_function("Boolean(window.pendingComparatorQueries.Rafa)")
                page.locator("#comparatorPlayer1").fill("Rafael")
                page.wait_for_function("Boolean(window.pendingComparatorQueries.Rafael)")
                page.evaluate("""() => {
                    window.pendingComparatorQueries.Rafael({players:[
                        {player_id:'atp:nadal',name:'Rafael Nadal',tour:'atp',matches_seen:500},
                        {player_id:'atp:rafael2',name:'Rafael Silva',tour:'atp',matches_seen:7}
                    ]});
                }""")
                page.get_by_role("button", name="Rafael Nadal").wait_for()
                page.evaluate("""() => {
                    window.pendingComparatorQueries.Rafa({players:[
                        {player_id:'atp:stale',name:'Stale Rafa',tour:'atp',matches_seen:5}
                    ]});
                }""")
                page.wait_for_timeout(100)
                assert page.get_by_role("button", name="Rafael Nadal").count() == 1
                assert page.get_by_role("button", name="Stale Rafa").count() == 0
                page.get_by_role("button", name="Rafael Nadal").click()
                assert page.locator("#comparatorPlayer1").input_value() == "Rafael Nadal"
                assert page.locator(".comparator-player-confirmed").count() == 2
                # Existing historical import fragments must not be exposed
                # as separate public records, but remain untouched in the API.
                page.evaluate("""() => {
                    window.BlinqAuth.comparatorPlayers=async(query) => ({
                        players:query.toLowerCase().includes('norr')?[
                            {player_id:'95935',name:'Cameron Norrie',tour:'atp',rank:27,matches_seen:598},
                            {player_id:'other-person',name:'Simon Norman',tour:'atp',matches_seen:37},
                            {player_id:'hist-js:atp:N771',name:'Cameron Norrie',tour:'atp',matches_seen:8},
                        ]:[
                            {player_id:'hist-js:atp:207494',name:'Svrčina D.',aliases:['Dalibor Svrcina'],tour:'atp',rank:99,matches_seen:83},
                            {player_id:'260122',name:'Dalibor Svrčina',tour:'atp',rank:91,matches_seen:330},
                        ]
                    });
                }""")
                page.locator("#comparatorPlayer0").fill("norr")
                page.get_by_role("button", name="Cameron Norrie").wait_for()
                assert page.locator("#comparatorSearch0 .comparator-search-primary").count() == 2
                assert page.locator("#comparatorSearch0 [data-player-id='95935']").count() == 1
                assert page.locator("#comparatorSearch0 [data-player-id='hist-js:atp:N771']").count() == 0
                assert page.locator("#comparatorSearch0 [data-comparator-expand]").count() == 0
                assert "zápasov v DB" not in page.locator("#comparatorSearch0").inner_text()
                page.locator("#comparatorSearch0 [data-player-id='95935']").click()
                assert page.evaluate("comparatorHarness.state.comparator.players[0].player_id") == "95935"

                page.locator("#comparatorPlayer1").fill("svrc")
                page.get_by_role("button", name="Dalibor Svrčina").wait_for()
                assert page.locator("#comparatorSearch1 .comparator-search-primary").count() == 1
                assert page.locator("#comparatorSearch1 [data-player-id='260122']").count() == 1
                assert page.locator("#comparatorSearch1 [data-player-id='hist-js:atp:207494']").count() == 0
                assert page.locator("#comparatorSearch1 [data-comparator-expand]").count() == 0
                page.locator("#comparatorSearch1 [data-player-id='260122']").click()
                assert page.evaluate("comparatorHarness.state.comparator.players[1].player_id") == "260122"

                # The real screenshot shows one abbreviated provider record
                # and one full-name provider record with ranks #50 and #54.
                # Only the full name should be offered, never a technical ID.
                page.evaluate("""() => {
                    window.BlinqAuth.comparatorPlayers=async(query) => ({
                        players:query.includes('ambig')?[
                            {player_id:'short-50',name:'Kecmanovic M.',tour:'atp',rank:50},
                            {player_id:'provider-54',name:'Miomir Kecmanović',tour:'atp',rank:54},
                            {player_id:'different-53',name:'Milos Kecmanovic',tour:'atp',rank:53}
                        ]:[
                            {player_id:'short-50',name:'Kecmanovic M.',tour:'atp',rank:50},
                            {player_id:'provider-54',name:'Miomir Kecmanović',tour:'atp',rank:54}
                        ]
                    });
                }""")
                page.locator("#comparatorPlayer0").fill("kecma")
                page.locator("#comparatorSearch0 [data-player-id='provider-54']").wait_for()
                assert page.locator("#comparatorSearch0 .comparator-search-primary").count() == 1
                assert page.locator("#comparatorSearch0 [data-player-id='short-50']").count() == 0
                assert page.locator("#comparatorSearch0 [data-comparator-expand]").count() == 0
                page.locator("#comparatorSearch0 [data-player-id='provider-54']").click()
                assert page.evaluate("comparatorHarness.state.comparator.players[0].player_id") == "provider-54"
                page.locator("#comparatorPlayer0").fill("ambig")
                page.locator("#comparatorSearch0 [data-player-id='different-53']").wait_for()
                assert page.locator("#comparatorSearch0 .comparator-search-primary").count() == 3
                assert page.locator("#comparatorSearch0 [data-player-id='short-50']").count() == 1
                # Ambiguous initials are never silently collapsed or linked.
                page.locator("#comparatorSearch0 [data-player-id='provider-54']").click()
                assert page.evaluate("comparatorHarness.state.comparator.players[0].player_id") == "provider-54"

                # Realistic analysis data, not decorative placeholders.
                page.evaluate("""() => {
                    const h=window.comparatorHarness;
                    h.state.comparator.result={
                        player1:{player_id:'95935',name:'Cameron Norrie',rank:27,
                            probability:.700225,fair_odds:1.428,
                            stats:{history_matches:598,surface_matches:240,overall_elo:1765.2,
                                surface_elo:1735.5,recent_5:{matches:5,wins:4},
                                recent_10:{matches:10,wins:7},surface_recent_10:{matches:10,wins:8},
                                recent_results:[{result:'W',surface:'hard'},{result:'L',surface:'clay'},
                                    {result:'W',surface:'hard'}],days_since_last_match:6,
                                surface_quality_samples:{serve:9,return:1},
                                surface_serve_quality:.624,surface_return_quality:.477}},
                        player2:{player_id:'260122',name:'Dalibor Svrčina',rank:91,
                            probability:.299775,fair_odds:3.336,
                            stats:{history_matches:330,surface_matches:115,overall_elo:1590.5,
                                surface_elo:1610,recent_5:{matches:5,wins:2},
                                recent_10:{matches:10,wins:5},surface_recent_10:{matches:4,wins:2},
                                recent_results:[{result:'L',surface:'hard'}],days_since_last_match:3,
                                surface_quality_samples:{serve:0,return:0},
                                surface_serve_quality:null,surface_return_quality:null}},
                        h2h:{overall:{player1_wins:1,player2_wins:2,matches:3},
                            surface:{player1_wins:1,player2_wins:0,matches:1}},
                        winner:{name:'Cameron Norrie',player_id:'95935'},
                        confidence:{data_band:'medium'},tour:'atp',surface:'hard',best_of:3,
                        model_version:'v201-test',
                        artifact:{generated_at:'2026-10-08T03:46:00+00:00'},
                        factors:[{label:'Surface Elo',advantage_player_id:'95935'}]
                    };
                    document.getElementById('routePanel').innerHTML=h.renderComparatorRoute();
                    h.wireComparator();
                }""")
                panel=page.locator(".comparator-analytics")
                panel.wait_for()
                assert panel.locator(".comparator-form-chip").count() == 4
                assert panel.locator(".comparator-h2h-line").count() == 2
                assert "1 : 2" in panel.locator(".comparator-h2h-line").first.inner_text()
                assert "1 : 0" in panel.locator(".comparator-h2h-line").last.inner_text()
                assert "70,0" in panel.inner_text() or "70.0" in panel.inner_text()
                assert "0.624" in panel.inner_text() or "0,624" in panel.inner_text()
                assert "0.477" not in panel.inner_text()  # only one return sample
                assert "vymyslen" not in panel.inner_text()
                assert panel.locator(".comparator-prob-meter span").get_attribute("style") == "width:70.02%"
                assert not page.evaluate("""() => {
                    const panel=document.querySelector('.comparator-analytics');
                    const rect=panel.getBoundingClientRect();
                    return rect.left< -2 || rect.right>innerWidth+2;
                }"""), (width, "analysis result overflows viewport")
                assert not errors, (width, errors)
                page.close()

            print("Comparator player search click, errors, stale result and mobile: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
