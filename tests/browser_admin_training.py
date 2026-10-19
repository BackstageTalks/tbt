"""Real browser admin training UI contract; no network or real dispatch."""
import os
from playwright.sync_api import sync_playwright
from browser_admin_test_results import route_request
from browser_runtime_r43 import ORIGIN, browser_path


def main():
    with sync_playwright() as pw:
        exe = os.getenv("BLINQ_BROWSER") or browser_path()
        browser = pw.chromium.launch(headless=True, **({"executable_path": exe} if exe else {}))
        try:
            for width in (390, 1440):
                context = browser.new_context(viewport={"width": width, "height": 900})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.adminTestUi && adminTestUi.state.ui")
                page.evaluate("""() => {
                    const s=adminTestUi.state;
                    s.feed.account={is_admin:true,role:'admin',plan:'admin'};
                    s.route='admin';s.adminTab='calibration';
                    s.adminTraining={can_start:true,reason:'Ready',runs:[],candidates:[]};
                    window.trainingCalls=[];
                    BlinqAuth.adminModelTraining=async payload=>{
                        trainingCalls.push(payload);
                        return payload?{message:'Požiadavka uložená.'}:{can_start:false,reason:'Tréning beží',runs:[],candidates:[]};
                    };
                    document.body.classList.remove('blinq-home','blinq-route');
                    document.body.classList.add('blinq-admin');
                    for(const id of ['bootSplash','cookieConsent','authDialog'])document.getElementById(id)?.remove();
                    document.getElementById('appShell').hidden=false;
                    const host=document.getElementById('routePanel');host.hidden=false;
                    host.innerHTML=adminTestUi.renderAdminRoute();adminTestUi.wireAdmin();
                }""")
                button=page.locator('[data-admin-action="training-start"]')
                assert button.is_enabled()
                page.locator('#admin-training-profile').select_option('standard')
                button.click()
                page.wait_for_function('trainingCalls.length===1 && !adminTestUi.state.adminTrainingBusy')
                assert page.evaluate('trainingCalls[0].profile')=='standard'
                assert page.locator('[data-admin-action="training-start"]').is_disabled()
                assert page.get_by_text('Požiadavka uložená.', exact=True).is_visible()
                page.locator('[data-admin-action="training-refresh"]').click()
                page.wait_for_function('trainingCalls.length===2 && !adminTestUi.state.adminTrainingBusy')
                assert page.locator('[data-admin-action="training-start"]').is_disabled()
                assert not errors, errors
                context.close()
        finally:
            browser.close()
    print('Admin training submit and blocked-state browser checks passed')


if __name__ == '__main__':
    main()
