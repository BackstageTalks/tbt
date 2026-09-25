"""Offline browser regressions for projection prices and membership interactions."""
import os
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == '/app.js':
        source = (WEB / 'app.js').read_text(encoding='utf-8')
        source = source.replace('  boot();', '''
  window.accessTest = {state, dailyHubRow, renderDailyHub, showAccessHint, showUpgradePrompt};
  boot();''')
        route.fulfill(content_type='application/javascript', body=source)
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=os.getenv('BLINQ_BROWSER') or browser_path())
        try:
            for width in (1440, 390):
                context = browser.new_context(viewport={'width': width, 'height': 900})
                context.route('**/*', route_request)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(ORIGIN + '/index.html?lang=sk', wait_until='networkidle')
                page.wait_for_function('window.accessTest && document.querySelector("#dailyHubHead")')
                page.evaluate('''() => {
                  document.querySelectorAll('dialog[open]').forEach(d=>d.close());
                  document.querySelector('#bootSplash')?.remove();
                  document.querySelector('#cookieConsent')?.remove();
                  document.querySelector('#appShell').hidden=false;
                  accessTest.state.route='predictions';
                  const fixture=document.createElement('div');
                  fixture.innerHTML='<button id="lockedFixture" data-upgrade-plan="elite" data-upgrade-section="SETS" style="position:fixed;left:40px;top:180px;z-index:210"><span>Locked</span></button><button id="otherFixture" style="position:fixed;left:40px;top:280px;z-index:210">Other</button>';
                  document.body.append(fixture);
                }''')
                trigger = page.locator('#lockedFixture')
                hint = page.locator('#accessHint')
                trigger.hover()
                page.wait_for_timeout(380)
                assert hint.is_visible()
                before = hint.bounding_box()
                page.locator('#accessHintUpgrade').hover()
                page.wait_for_timeout(420)
                assert hint.bounding_box() == before, 'CTA hover must not re-anchor its own hint'
                trigger.focus()
                page.locator('#accessHintUpgrade').focus()
                page.wait_for_timeout(250)
                assert hint.is_visible(), 'Focus transfer into the hint must not hide it'
                assert hint.bounding_box() == before, 'CTA focus must preserve anchor'
                page.keyboard.press('Enter')
                assert page.locator('#upgradeDialog').is_visible()
                assert not hint.is_visible()
                assert page.locator('#upgradeDialogClose').evaluate('(e)=>e===document.activeElement')
                page.wait_for_timeout(450)
                assert not hint.is_visible(), 'No pending hover timer may reopen the hint'
                page.keyboard.press('Escape')
                assert not page.locator('#upgradeDialog').is_visible()
                assert trigger.evaluate('(e)=>e===document.activeElement'), 'Return focus to original trigger'
                assert not hint.is_visible()
                trigger.click()
                assert hint.is_visible()
                page.keyboard.press('Escape')
                assert not hint.is_visible()
                # An already-open modal must keep its content and focused control.
                page.evaluate("accessTest.showUpgradePrompt('elite','SETS',true)")
                page.locator('#upgradeDialogClose').focus()
                page.evaluate("accessTest.showUpgradePrompt('pro','Other',true)")
                assert page.locator('#upgradeDialogClose').evaluate('(e)=>e===document.activeElement')
                assert 'ELITE' in page.locator('#upgradeDialogContent').inner_text()
                page.keyboard.press('Escape')
                # Inspect the actual rendered SETS and mixed-table cells.
                page.evaluate('''() => {
                  const base={event_id:'sets-test',market:'sets',selection:'Under 2.5 Sets',projection:2.10,projection_unit:'sets',projection_confidence:.9,player1:{name:'A'},player2:{name:'B'}};
                  for(const tab of ['sets','see_all']){
                    for(const data of [{}, {odds:null}, {odds:0}, {odds:1}, {odds:'bad'}, {odds:Infinity}, {odds:true}, {betting:{odds:null}}, {match_winner_market:{player1_odds:1.8}}]){
                      const table=document.createElement('table');
                      table.innerHTML=accessTest.dailyHubRow({...base,_hub_source:'sets',...data},tab);
                      if(!table.querySelector('.hub-odds').textContent.includes('N/A'))throw new Error('Missing price must be N/A: '+JSON.stringify(data));
                    }
                    for(const data of [{odds:1.87},{betting:{odds:1.87}},{odds:0,betting:{odds:1.87}}]){
                      const table=document.createElement('table');table.innerHTML=accessTest.dailyHubRow({...base,_hub_source:'sets',...data},tab);
                      if(!table.querySelector('.hub-odds').textContent.includes('1.87'))throw new Error('Real selection odds must remain visible');
                    }
                  }
                }''')
                # Reproduce the FREE regression: the API returns one random
                # authorized pick at original offer slot 8, not slot 1.
                # The browser must render slot 8 and may not show "Requires FREE".
                page.evaluate('''() => {
                  const app=accessTest, state=app.state;
                  state.ui=state.ui||state.uiSource;
                  const slots=Array(10).fill('blurred');
                  slots[7]='active';
                  const entitlement={
                    visible_picks:1,returned:1,total:10,locked_count:9,
                    enabled:true,blur_remaining:true,see_all:false,
                    display_state:'active',selection_mode:'stable_random',
                    slot_states:slots,
                  };
                  const row={
                    event_id:'free-random-slot-8',_access_slot:7,
                    surface:'hard',tournament:'Regression Test',
                    scheduled_at:new Date(Date.now()+3600000).toISOString(),
                    winner_id:'11',betting:{odds:1.85},
                    player1:{id:'11',name:'Alpha',probability:.72},
                    player2:{id:'22',name:'Beta',probability:.28},
                  };
                  state.feed={
                    account:{status:'active',plan:'rookie'},
                    daily_picks:[row],prime_picks:[row],value_picks:[row],
                    entitlements:{plan:'rookie',sections:{
                      daily:entitlement,prime:entitlement,value:entitlement,
                    }},
                  };
                  state.dashboardSearch='';
                  state.dailyHubTournament='';
                  state.dailyHubExpanded=false;
                  for(const tab of ['daily','prime','value']){
                    state.dailyHubTab=tab;
                    app.renderDailyHub();
                    const active=document.querySelectorAll('#dailyHubBody tr[data-hub-event="free-random-slot-8"]');
                    if(active.length!==1)throw new Error(tab+': FREE slot #8 must be visible exactly once, got '+active.length);
                    const selfLocks=document.querySelectorAll('#dailyHubBody [data-upgrade-plan="rookie"]');
                    if(selfLocks.length)throw new Error(tab+': FREE user must not see a FREE upgrade paywall');
                    const firstLock=document.querySelector('#dailyHubBody tr.hub-row-locked');
                    if(firstLock&&firstLock.dataset.upgradePlan!=='pro'){
                      throw new Error(tab+': first unselected slot should unlock at PRO, not '+firstLock.dataset.upgradePlan);
                    }
                    const button=document.querySelector('#dailyHubTabs [data-daily-hub-tab="'+tab+'"]');
                    if(!button||button.classList.contains('is-locked'))throw new Error(tab+': included FREE tab must remain accessible');
                  }

                  // When the provider temporarily cannot return an allocated
                  // free pick, show a neutral availability message, never a
                  // nonsense "Requires FREE" upgrade prompt.
                  state.feed.prime_picks=[];
                  state.feed.entitlements.sections.prime={
                    ...entitlement,returned:0,locked_count:10,
                    slot_states:Array(10).fill('blurred'),
                  };
                  state.dailyHubTab='prime';
                  app.renderDailyHub();
                  if(document.querySelector('#dailyHubBody [data-upgrade-plan="rookie"]')){
                    throw new Error('Temporarily missing included pick cannot require FREE');
                  }
                  if(document.querySelector('#dailyHubTabs [data-daily-hub-tab="prime"].is-locked')){
                    throw new Error('FREE account must not be locked out of its included category');
                  }
                  if(!document.querySelector('#dailyHubEmpty')?.textContent.includes('zahrnutý tip')){
                    throw new Error('Missing included pick needs an availability explanation');
                  }
                }''')
                assert not errors, errors
                context.close()
                print(f'PASS access/odds browser regression at {width}px')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
