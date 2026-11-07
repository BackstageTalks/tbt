"""Chromium end-to-end: admin CSV buttons download all Results and offered predictions."""
import os
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source = (WEB / "app.js").read_text(encoding="utf-8")
        marker = "  boot();"
        assert source.count(marker) == 1
        route.fulfill(content_type="application/javascript", body=source.replace(
            marker, "  window.adminCsvHarness={state,renderAdminRoute,wireAdmin};\n" + marker
        ))
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        exe = os.getenv("BLINQ_BROWSER") or browser_path()
        browser = pw.chromium.launch(headless=True, executable_path=exe) if exe else pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", route_request)
            page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
            page.wait_for_function("window.adminCsvHarness && window.BlinqAdminCsv && adminCsvHarness.state.ui")
            page.evaluate("""() => {
              const s=adminCsvHarness.state;
              const row=i=>({
                event_id:'evt-'+i,scheduled_at:'2026-11-07T14:00:00Z',
                tour:'ATP',tournament:'Fixture',surface:'hard',round:'R32',
                player1:{id:'p1',name:'A'},player2:{id:'p2',name:'B'},
                market_publications:[
                  {section:'top_daily',market:'match_winner',selection_id:'p1',selection:'A',
                   issued_at:'2026-11-07T08:00:00Z',model_probability:.78,odds:1.83,
                   result:{status:'hit',correct:true,profit_units:.83}},
                  {section:'value',market:'match_winner',selection_id:'p1',selection:'A',
                   issued_at:'2026-11-07T09:00:00Z',model_probability:.78,odds:1.83,
                   result:{status:'hit',correct:true,profit_units:.83}}
                ]
              });
              s.feed={
                account:{is_admin:true,role:'admin',plan:'admin'},
                results:Array.from({length:121},(_,i)=>row(i)),
                daily_picks:[{...row(1000),winner_id:'p1',probability:.78,odds:1.83}],
                prime_picks:[{...row(1001),winner_id:'p2',probability:.83,odds:1.31}],
                value_picks:[],ace_picks:[],sg_picks:[],doubles_picks:[],
                results_archive_unavailable:false,results_exclusions_unavailable:false
              };
              s.previewPlan=null;s.route='admin';s.adminTab='dataexport';
              document.body.classList.remove('blinq-home','blinq-route');
              document.body.classList.add('blinq-admin');
              document.getElementById('bootSplash')?.remove();
              document.getElementById('cookieConsent')?.remove();
              document.getElementById('appShell').hidden=false;
              const host=document.getElementById('routePanel');
              host.hidden=false;host.innerHTML=adminCsvHarness.renderAdminRoute();
              adminCsvHarness.wireAdmin();
            }""")
            assert page.get_by_text("121 vyhodnotených tipov").count() == 1
            with page.expect_download() as info:
                page.locator('[data-admin-export-csv="results"]').click()
            results_dl = info.value
            assert results_dl.suggested_filename.startswith("blinq_vysledky_")
            results_text = results_dl.path().read_bytes().decode("utf-8-sig")
            lines = [line for line in results_text.split("\r\n") if line]
            assert len(lines) == 122, len(lines)
            assert '"TOP | Value"' in results_text
            assert '"0.83"' in results_text
            with page.expect_download() as info:
                page.locator('[data-admin-export-csv="predictions"]').click()
            predictions_dl = info.value
            assert predictions_dl.suggested_filename.startswith("blinq_predikcie_")
            predictions_text = predictions_dl.path().read_bytes().decode("utf-8-sig")
            assert '"TOP"' in predictions_text and '"ACCA"' in predictions_text
            assert '"src_predikcia.event_id"' in predictions_text
            assert not errors, errors

            # Never export a misleading historical CSV after archive outage.
            page.evaluate("""() => {
              adminCsvHarness.state.feed.results_archive_unavailable=true;
              document.getElementById('routePanel').innerHTML=adminCsvHarness.renderAdminRoute();
              adminCsvHarness.wireAdmin();
            }""")
            assert page.locator('[data-admin-export-csv="results"]').is_disabled()
            assert page.locator('[data-admin-export-csv="predictions"]').is_enabled()
            context.close()
            print("Admin CSV browser downloads: 121 Results, merged categories, predictions, archive fail-closed: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
