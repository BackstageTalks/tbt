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
                initial_dialog = lambda dialog: dialog.accept()
                page.on("dialog", initial_dialog)
                page.route("**/*", route_request)
                page.goto(ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.adminTestUi && adminTestUi.state.ui")
                page.evaluate("""() => {
                    const s=adminTestUi.state;
                    s.feed.account={is_admin:true,role:'admin',plan:'admin'};
                    s.route='admin';s.adminTab='calibration';
                    s.adminTraining={can_start:true,reason:'Ready',runs:[],candidates:[]};
                    // A promoted model must be the visible champion while the
                    // former shadow comparison stays historical.
                    s.adminCalibration={
                        production_version:'v7.2.1-v201-20261022T134742452543Z',
                        shadow_pair_state:'awaiting_new_pair',
                        historical_shadow_pair:{production_version:'v201-20260925T204608601094Z',
                            candidate_version:'v7.2.1-v201-20261022T134742452543Z'},
                        candidate_version:null,candidate_active:false,stale:false,
                        updated_at:'2026-10-26T06:25:06Z',
                        shadow:{captured:0,settled:0,pending:0,settled_utc_days:0,
                            target_for_tracking:1000,remaining_to_target:1000,
                            minimum_for_review:200,production:{},candidate:{},gate:{}},
                        unseen:{available:true,eligible_rows:10446,target_for_retrain:1000,
                            minimum_for_review:200,remaining_to_target:0,remaining_to_review:0},
                    };
                    s.adminModelLab={can_start:true,reason:'Ready',champion_sha256:'c'.repeat(64),active_sha256:'a'.repeat(64),candidates:[],operation:null,last_operation:null,
                        last_preflight:{state:'WORKFLOW_VERIFIED',verified_at:new Date().toISOString(),
                            run:{id:123,status:'completed',conclusion:'success',artifact_verified:true,
                                 html_url:'https://github.com/BackstageTalks/tbt/actions/runs/123',
                                 preflight_report:{eligible_rows:600000,tours:{
                                   atp:{eligible_matches:340000,coverage_counts:{rank_pair:250000,serve:100000,return:90000,break_points:80000}},
                                   wta:{eligible_matches:260000,coverage_counts:{rank_pair:200000,serve:80000,return:85000,break_points:60000}}}}}}};
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
                assert page.locator('.admin-model-production').get_by_text('BlinQ 7.2.1').is_visible()
                assert page.locator('.admin-calibration-card').first.get_by_text('BlinQ 7.2.1').is_visible()
                assert page.get_by_text('Pre nový produkčný model zatiaľ neexistuje porovnateľná shadow vzorka', exact=False).is_visible()
                assert page.get_by_text('Ďalší model · čaká na vyhodnotenie').is_visible()
                button=page.locator('[data-admin-action="training-start"]')
                assert button.is_enabled(), 'New Model Factory must allow a ready guarded training'
                assert page.get_by_text('Natrénovať a spustiť shadow').is_visible()
                page.locator('.admin-model-factory-advanced summary').click()
                assert page.get_by_text('Aktivovať iba shadow (manuálne)').is_visible()
                assert page.get_by_text('3 · Nasadiť do produkcie').is_visible()
                assert page.locator('[data-admin-action="model-factory-promote"]').is_disabled()
                assert page.get_by_text('ATP: 340', exact=False).is_visible()
                assert page.get_by_text('WTA: 260', exact=False).is_visible()
                # Confirm the one-click protected build/test path. A successful
                # POST is always followed by durable Admin status GET.
                button.click()
                page.get_by_role("button",name="Potvrdiť a pokračovať",exact=True).click()
                page.wait_for_function('trainingCalls.length===2 && !adminTestUi.state.adminTrainingBusy')
                assert page.evaluate('trainingCalls[0].profile')=='accuracy-7.2.2'
                assert page.evaluate('trainingCalls[0].auto_shadow') is True
                assert page.evaluate('trainingCalls[1]===undefined')
                assert page.locator('[data-admin-action="training-start"]').is_disabled()
                assert page.get_by_text('Požiadavka uložená.', exact=True).is_visible()
                assert page.locator('[data-model-lab-operation="activate_shadow"]').is_disabled()
                assert page.locator('[data-model-lab-operation="import_drive"]').count()==1
                page.evaluate("""() => {
                    const s=adminTestUi.state;
                    s.adminTraining={can_start:true,runs:[],candidates:[]};
                    s.adminModelLab.can_start=true;
                    s.adminModelLab.candidates=[{tag:'blinq-candidate-frozen-123-1',sha256:'b'.repeat(64)}];
                    s.adminCalibration=null; // Incomplete calibration must allow explicit waiver.
                    window.releaseCalls=[];
                    BlinqAuth.adminModelLab=async payload=>{
                        if(payload){releaseCalls.push(payload);return {message:'Release queued'};}
                        return s.adminModelLab;
                    };
                    document.getElementById('routePanel').innerHTML=adminTestUi.renderAdminRoute();
                    adminTestUi.wireAdmin();
                }""")
                promote=page.locator('[data-admin-action="model-factory-promote"]')
                assert promote.is_enabled()
                # Native dialogs are unavailable in some embedded browsers.
                page.evaluate("window.prompt=()=>null;window.confirm=()=>false")
                promote.click()
                page.get_by_role('button',name='Zrušiť',exact=True).click()
                assert page.evaluate('releaseCalls.length')==0
                promote.click()
                page.get_by_label('Dôvod výnimky kalibrácie',exact=True).fill('Owner accepts incomplete calibration')
                page.get_by_label('Napíš RELEASE blinq-candidate-frozen-123-1',exact=True).fill('wrong')
                page.get_by_role('button',name='Potvrdiť produkčný release',exact=True).click()
                assert page.evaluate('releaseCalls.length')==0
                page.get_by_label('Napíš RELEASE blinq-candidate-frozen-123-1',exact=True).fill('RELEASE blinq-candidate-frozen-123-1')
                page.get_by_role('button',name='Potvrdiť produkčný release',exact=True).click()
                page.wait_for_function('releaseCalls.length===1 && !adminTestUi.state.adminModelLabBusy')
                request=page.evaluate('releaseCalls[0]')
                assert request['action']=='promote_production'
                assert request['calibration_override'] is True
                assert request['confirmation']=='RELEASE blinq-candidate-frozen-123-1'
                assert not errors, errors
                context.close()
        finally:
            browser.close()
    print('Model Factory three-phase preflight, one-click shadow training, durable readback, and safe advanced controls: PASS')


if __name__ == '__main__':
    main()
