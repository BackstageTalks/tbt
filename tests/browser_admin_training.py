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
                page.on("dialog", lambda dialog: dialog.accept())
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.adminTestUi && adminTestUi.state.ui")
                page.evaluate("""() => {
                    const s=adminTestUi.state;
                    s.feed.account={is_admin:true,role:'admin',plan:'admin'};
                    s.route='admin';s.adminTab='calibration';
                    s.adminTraining={can_start:true,reason:'Ready',runs:[],candidates:[]};
                    s.adminModelLab={can_start:true,reason:'Ready',active_sha256:'a'.repeat(64),candidates:[],operation:null,last_operation:null};
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
                assert button.is_enabled(), 'New Model Factory must allow a ready guarded training'
                assert page.get_by_text('Vytvoriť a otestovať kandidáta 7.2.1').is_visible()
                assert page.get_by_text('Aktivovať iba shadow').is_visible()
                # Confirm the one-click protected build/test path. A successful
                # POST is always followed by durable Admin status GET.
                button.click()
                page.wait_for_function('trainingCalls.length===2 && !adminTestUi.state.adminTrainingBusy')
                assert page.evaluate('trainingCalls[0].profile')=='top-7.2.1'
                assert page.evaluate('trainingCalls[1]===undefined')
                assert page.locator('[data-admin-action="training-start"]').is_disabled()
                assert page.get_by_text('Požiadavka uložená.', exact=True).is_visible()
                assert page.locator('[data-model-lab-operation="activate_shadow"]').is_disabled()
                assert page.locator('[data-model-lab-operation="import_drive"]').count()==1
                assert not errors, errors
                context.close()
        finally:
            browser.close()
    print('Model Factory one-click training, durable readback, blocked concurrent shadow and safe advanced controls: PASS')


if __name__ == '__main__':
    main()
