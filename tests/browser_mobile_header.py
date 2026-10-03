"""Offline real-renderer checks for mobile header, joined groups and prediction cards."""
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path

def route_request(route):
    if urlparse(route.request.url).path == '/app.js':
        source=(WEB/'app.js').read_text(encoding='utf-8')
        source=source.replace('  boot();','  window.mobileTest={state,dailyHubRow,renderProjectGroupBar,renderInsightBell};\n  boot();')
        route.fulfill(content_type='application/javascript',body=source)
    else:
        static_route(route)

def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=os.getenv('BLINQ_BROWSER') or browser_path())
        try:
            for width in (320,390,900,1440):
                page=browser.new_page(viewport={'width':width,'height':850})
                errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/*',route_request)
                page.goto(ORIGIN+'/index.html?lang=sk',wait_until='networkidle')
                page.wait_for_function('window.mobileTest && mobileTest.state.ui')
                page.evaluate('''() => {
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelectorAll('dialog[open]').forEach(d=>d.close());
                    document.getElementById('appShell').hidden=false;
                    const h=mobileTest;h.state.feed.account={plan:'rookie',status:'active',project_groups:[{id:'one',name:'Platba PO',joined:true,active:true}]};
                    h.state.insights=[
                      {id:'project-one',read:false,type:'info',audience_mode:'groups',group_ids:['one']},
                      {id:'info-one',read:false,type:'info',audience_mode:'levels'}
                    ];
                    h.state.ui.notifications={enabled:true};h.renderInsightBell();h.renderProjectGroupBar();
                    const row={event_id:'test',scheduled_at:new Date(Date.now()+3600000).toISOString(),tour:'ATP',tournament:'Beijing, China',surface:'hard',player1:{id:'one',name:'Andrey Rublev',rank:26},player2:{id:'two',name:'Roman Safiullin',rank:102},pick:'Andrey Rublev',model_probability:.703,odds:1.67};
                    document.getElementById('dailyHubBody').innerHTML=h.dailyHubRow(row,'daily',false,0);
                    document.getElementById('dailyHubEmpty').hidden=true;
                    window.groupCalls=[];
                    document.getElementById('projectGroupBar').onclick=e=>{const b=e.target.closest('[data-project-group-open]');if(b)groupCalls.push(b.dataset.projectGroupOpen);};
                }''')
                page.wait_for_timeout(200)
                if width<=900:
                    assert page.locator('#bqm-projects').is_visible()
                    assert page.locator('#bqm-projects').get_attribute('data-unread')=='1'
                    assert page.locator('#insightUnread').is_visible()
                    assert page.locator('#insightUnread').inner_text()=='1'
                    geometry=page.evaluate('''() => {
                        const els=['#bqm-toggle','.header-top>.brand','#bqm-projects','#insightBell','#profileButton'].map(s=>document.querySelector(s).getBoundingClientRect());
                        return {overlap:els.some((r,i)=>i&&r.left<els[i-1].right-1),overflow:document.documentElement.scrollWidth-innerWidth};
                    }''')
                    assert not geometry['overlap'],(width,geometry)
                    assert geometry['overflow']<=2,(width,geometry)
                    font_size=page.locator('.hub-match-player-main b').first.evaluate('(n)=>parseFloat(getComputedStyle(n).fontSize)')
                    assert font_size>=13
                    page.locator('#bqm-projects').click()
                    assert page.evaluate('groupCalls')==['one']
                    page.evaluate("mobileTest.state.feed.account.project_groups.push({id:'two',name:'Druhá skupina',joined:true,active:true});mobileTest.renderProjectGroupBar()")
                    page.wait_for_timeout(50)
                    page.locator('#bqm-projects').click()
                    page.get_by_role('button',name='Druhá skupina',exact=True).click()
                    assert page.evaluate('groupCalls')==['one','two']
                    page.locator('#profileButton').click()
                    assert page.locator('#profileMenu').is_visible()
                    assert not page.locator('#profileProjectsLink').is_visible()
                    page.locator('#profileButton').click()
                    if width==390 and os.getenv('BLINQ_SCREENSHOTS'):
                        out=Path(os.environ['BLINQ_SCREENSHOTS']);out.mkdir(parents=True,exist_ok=True)
                        page.screenshot(path=str(out/'mobile-predictions-review.png'),full_page=True)
                        page.locator('.header-top').screenshot(path=str(out/'mobile-header.png'))
                    page.evaluate('mobileTest.state.feed.account.project_groups=[];mobileTest.renderProjectGroupBar()')
                    page.wait_for_timeout(50)
                    assert not page.locator('#bqm-projects').is_visible()
                else:
                    assert page.locator('#bqm-projects').is_visible()
                    assert not page.locator('#projectGroupBar').is_visible()
                    assert not page.locator('#bqm-toggle').is_visible()
                    assert page.locator('#profileButton').is_visible()
                    assert page.locator('#bqm-projects').get_attribute('data-unread')=='1'
                    assert page.locator('#insightUnread').is_visible()
                    assert page.locator('#insightUnread').inner_text()=='1'
                    page.locator('#bqm-projects').click()
                    assert page.evaluate('groupCalls')==['one']
                assert not errors,(width,errors)
                page.close()
            print('Header PP/Info numeric badges, avatar profile, mobile layout and desktop: PASS')
        finally:
            browser.close()

if __name__=='__main__':main()
