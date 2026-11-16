"""Chromium visual + interaction contract for the approved BlinQ match detail skin.

Synthetic rows only. No private data, provider calls, CDB writes or publication.
Checks the rendered winner tabs, market detail tiles and desktop pop-out.
"""
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        route.fulfill(
            content_type="application/javascript",
            body=source.replace(
                marker,
                "  window.detailSkinHarness={state,openMatch,"
                "aceProjectionDetailHtml,sgProjectionDetailHtml};\n" + marker,
            ),
        )
    else:
        static_route(route)


class StaticWebHandler(SimpleHTTPRequestHandler):
    requested_paths = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        if ".css" in self.path:
            self.requested_paths.append(self.path)
        super().do_GET()

    def log_message(self, *_args):
        pass


def main():
    # Real same-origin HTTP asset requests: document.write() pop-ups opened
    # from synthetic blinq.test did not resolve link styles in Chromium.
    # Keep all API replies synthetic and prevent off-machine requests.
    http = ThreadingHTTPServer(("127.0.0.1", 0), StaticWebHandler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{http.server_address[1]}"
    try:
        _run_browser(origin)
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)


def _run_browser(origin):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=os.getenv("BLINQ_BROWSER") or browser_path()
        )
        try:
            for width in (390, 768, 1440):
                context = browser.new_context(viewport={"width": width, "height": 950})
                # The actual HTTP server delivers stylesheets to both the
                # main document and the newly created pop-out. Only JS
                # harness and fake API responses are intercepted.
                context.route("**/app.js*", route_request)
                context.route("**/api/**", static_route)
                context.route("https://**", lambda route: route.abort())
                css_events = []
                context.on("request", lambda req: (
                    css_events.append(("request", req.url)) if ".css" in req.url else None
                ))
                context.on("response", lambda res: (
                    css_events.append(("response", res.status, res.url))
                    if ".css" in res.url else None
                ))
                context.on("requestfailed", lambda req: (
                    css_events.append(("failure", req.url, req.failure))
                    if ".css" in req.url else None
                ))
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                page.goto(origin + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function(
                    "window.detailSkinHarness && detailSkinHarness.state.ui"
                )
                page.evaluate("""() => {
                  document.querySelector('#bootSplash')?.remove();
                  document.querySelector('#cookieConsent')?.remove();
                  document.querySelectorAll('dialog[open]').forEach(el=>el.close());
                  const h=detailSkinHarness,s=h.state;
                  s.feed.account={is_admin:true,role:'admin',plan:'admin',status:'active'};
                  s.ui.dashboard.match_detail.plans.rookie=true;
                  for(const key of ['overview','statistics','radar','history']) {
                    s.ui.dashboard.match_detail.sections[key]='rookie';
                  }
                  const match={
                    event_id:'synthetic-helsinki-visual',
                    tour:'ATP',tournament:'Helsinki, Finland',surface:'hard',
                    scheduled_at:'2026-11-17T18:50:00Z',
                    player1:{id:'101',name:'Andrea Guerrieri',ranking:165,country:'IT'},
                    player2:{id:'102',name:'Elias Ymer',ranking:203,country:'SE'},
                    p1:'Andrea Guerrieri',p2:'Elias Ymer',
                    pick:'Andrea Guerrieri',selection_id:'101',
                    probability:.755,model_probability:.755,
                    section:'top_daily',market:'match_winner',signals:[],
                    __liveIntelligenceLoaded:true
                  };
                  window.detailSkinRow=match;
                  h.openMatch(match,'daily',match,true);
                }""")
                dialog = page.locator("#matchDialog")
                assert dialog.evaluate("(el)=>el.open"), width
                tabs = page.locator("#matchDialog [data-match-tab]")
                assert tabs.count() == 4, width
                style = page.evaluate("""() => {
                  const dialog=document.querySelector('#matchDialog');
                  const tabs=dialog.querySelector('.match-detail-tabs');
                  const active=tabs.querySelector('button.active');
                  const inactive=tabs.querySelector('button:not(.active)');
                  const s1=getComputedStyle(active);
                  const s0=getComputedStyle(inactive);
                  const runner=getComputedStyle(active,'::after');
                  return {
                    grid:getComputedStyle(tabs).gridTemplateColumns,
                    activeColor:s1.color,inactiveColor:s0.color,
                    activeBackground:s1.backgroundColor,
                    activeShadow:s1.boxShadow,
                    runnerHeight:runner.height,runnerWidth:runner.width,
                    runnerColor:runner.backgroundColor,runnerDisplay:runner.display,
                    cardBorder:getComputedStyle(dialog.querySelector('.match-detail-pick')).borderColor,
                    contentOverflow:dialog.scrollWidth-dialog.clientWidth
                  };
                }""")
                expected_columns = 2 if width <= 760 else 4
                assert len(style["grid"].split()) == expected_columns, (width, style)
                assert style["activeColor"] != style["inactiveColor"], (width, style)
                assert style["activeShadow"] == "none", (width, style)
                assert style["runnerDisplay"] == "block", (width, style)
                assert style["runnerHeight"] == "1px", (width, style)
                assert style["runnerWidth"] == "29px", (width, style)
                assert style["contentOverflow"] <= 1, (width, style)
                assert dialog.locator(".insight-player-card").count() == 2, width
                page.locator('[data-match-tab="statistics"]').click()
                assert page.locator('[data-match-tab="statistics"]').get_attribute("aria-pressed") == "true"
                assert page.locator('[data-match-panel="statistics"]').is_visible()
                assert page.locator('[data-match-panel="overview"]').is_hidden()
                page.locator('[data-match-tab="overview"]').click()
                assert page.locator('[data-match-panel="overview"]').is_visible()

                if width == 1440:
                    with page.expect_popup() as popup_info:
                        page.locator("[data-match-popout]").click()
                    popup = popup_info.value
                    # window.open('', name) starts at about:blank. An
                    # immediate stylesheet count can inspect that initial
                    # document instead of the document.write() pop-out.
                    popup.locator(".match-detail-tabs button.active").wait_for(
                        state="visible", timeout=12000
                    )
                    try:
                        popup.wait_for_function(
                            """() => {
                              const el=document.querySelector('.match-detail-tabs button.active');
                              return el && getComputedStyle(el,'::after').height==='1px';
                            }""",
                            timeout=12000,
                        )
                    except Exception:
                        diagnostic = popup.evaluate("""() => ({
                          hrefs:Array.from(document.querySelectorAll('link[rel=stylesheet]'),
                            el=>({href:el.href,loaded:!!el.sheet,
                                  disabled:el.disabled,rel:el.rel})),
                          sheets:document.styleSheets.length,
                          body:document.body?.innerHTML.slice(0,300),
                          state:document.readyState,
                          runner:getComputedStyle(
                            document.querySelector('.match-detail-tabs button.active'),
                            '::after').height
                        })""")
                        diagnostic["css_events"] = css_events[-24:]
                        diagnostic["server_gets"] = StaticWebHandler.requested_paths[-24:]
                        diagnostic["popup_url"] = popup.url
                        if os.getenv("BLINQ_SCREENSHOTS"):
                            out = Path(os.environ["BLINQ_SCREENSHOTS"])
                            out.mkdir(parents=True, exist_ok=True)
                            popup.screenshot(path=str(out / "detail-popup-css-failure-1440.png"))
                        raise AssertionError(("popout detail CSS not loaded", diagnostic))
                    popout_runner = popup.locator(".match-detail-tabs button.active").evaluate(
                        '(el)=>getComputedStyle(el,"::after").height'
                    )
                    assert popout_runner == "1px", popout_runner
                    popup.close()

                for market in ("aces", "double_faults", "sets", "games"):
                    tile = page.evaluate("""market => {
                      const row={...window.detailSkinRow,
                        market,projection:market==='aces'?8.2:2.75,
                        opponent_projection:5.2,projection_gap:3,
                        projection_confidence:.72,reference_projection:2.5,
                        projection_samples:{player1:40,player2:42,
                                            player1_surface:22,player2_surface:20}};
                      const html=market==='aces'||market==='double_faults'
                        ?detailSkinHarness.aceProjectionDetailHtml(row)
                        :detailSkinHarness.sgProjectionDetailHtml(row,market);
                      if(!html)throw new Error('Empty detail markup for '+market);
                      document.querySelector('#dialogContent').innerHTML=html;
                      const card=document.querySelector('.ace-detail-pick,.sg-detail-hero');
                      const metric=document.querySelector('.ace-detail-metric,.sg-detail-grid article');
                      return {
                        cardBackground:getComputedStyle(card).backgroundImage,
                        cardBorder:getComputedStyle(card).borderColor,
                        metricBackground:getComputedStyle(metric).backgroundColor,
                        overflow:document.querySelector('#matchDialog').scrollWidth-
                                 document.querySelector('#matchDialog').clientWidth
                      };
                    }""", market)
                    assert "linear-gradient" in tile["cardBackground"], (width, market, tile)
                    assert tile["overflow"] <= 1, (width, market, tile)

                # Only capture source-owned, anonymous synthetic visuals.
                if os.getenv("BLINQ_SCREENSHOTS") and width in (390, 1440):
                    page.evaluate("""() => {
                      document.querySelector('#dialogContent').innerHTML='';
                      detailSkinHarness.openMatch(
                        window.detailSkinRow,'daily',window.detailSkinRow,true);
                    }""")
                    out = Path(os.environ["BLINQ_SCREENSHOTS"])
                    out.mkdir(parents=True, exist_ok=True)
                    dialog.screenshot(path=str(out / f"detail-premium-winner-{width}.png"))
                assert not errors, (width, errors)
                context.close()
                print("PASS premium match detail / all markets / popup", width)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
