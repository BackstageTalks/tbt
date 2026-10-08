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
                # Approved header: gold rocket instead of PP, no tile borders,
                # and no second navigation row on phones.
                assert page.locator('#bqm-projects svg.project-rocket-icon').count()==1,(width,'rocket icon missing')
                if width<=900:
                    assert page.locator('.mobile-icon-nav').is_hidden(),(width,'second mobile navigation row')
                    header_height=page.locator('.site-header').evaluate('(n)=>n.getBoundingClientRect().height')
                    assert header_height<=66,(width,header_height)
                    assert page.locator('.header-top .reference-navigation .nav-icon-link:visible').count()==3,(width,'primary icons missing')
                    # Worst-case icon density: LIVE and crown both available, plus project, bell, profile.
                    page.evaluate('''() => {
                        for (const id of ['insightShortcut','topUpgradeButton']) {
                            const node=document.getElementById(id);
                            node.dataset.mobileHeaderTestWasHidden=String(node.hidden);
                            node.hidden=false;
                        }
                    }''')
                    page.wait_for_timeout(60)
                    icon_fit=page.evaluate('''() => {
                        const selectors=['#bqm-toggle','.header-top>.brand',
                          '.header-top .reference-navigation [data-route="predictions"]',
                          '.header-top .reference-navigation [data-route="results"]',
                          '.header-top .reference-navigation [data-route="compare"]',
                          '#bqm-projects','#insightShortcut','#topUpgradeButton','#insightBell',
                          '#profileButton'];
                        const rects=selectors.map(selector=>({
                            selector,node:document.querySelector(selector)
                          })).filter(x=>x.node && !x.node.hidden && getComputedStyle(x.node).display!=='none')
                          .map(x=>({selector:x.selector,rect:x.node.getBoundingClientRect()}));
                        const overlap=rects.some((x,i)=>i>0 && x.rect.left < rects[i-1].rect.right-0.75);
                        return {overlap,
                            left:Math.min(...rects.map(x=>x.rect.left)),
                            right:Math.max(...rects.map(x=>x.rect.right)),
                            overflow:document.documentElement.scrollWidth-innerWidth,
                            visible:rects.map(x=>x.selector)};
                    }''')
                    assert len(icon_fit['visible'])==10,(width,icon_fit)
                    assert not icon_fit['overlap'],(width,icon_fit)
                    assert icon_fit['left']>=0 and icon_fit['right']<=width+1,(width,icon_fit)
                    assert icon_fit['overflow']<=2,(width,icon_fit)
                    page.evaluate('''() => {
                        for (const id of ['insightShortcut','topUpgradeButton']) {
                            const n=document.getElementById(id);
                            n.hidden=n.dataset.mobileHeaderTestWasHidden==='true';
                            delete n.dataset.mobileHeaderTestWasHidden;
                        }
                    }''')
                    print(f'Mobile header full icon fit at {width}px: PASS')
                else:
                    styles=page.evaluate('''() => {
                        const selectors=['.reference-navigation[data-icon-navigation="1"] .nav-icon-link',
                            '.reference-topbar #bqm-projects','.reference-topbar #insightBell'];
                        return selectors.flatMap(s=>[...document.querySelectorAll(s)])
                            .filter(n=>!n.hidden).map(n=>({
                                id:n.id||n.getAttribute('data-route'),
                                width:n.getBoundingClientRect().width,
                                height:n.getBoundingClientRect().height,
                                border:getComputedStyle(n).borderTopWidth
                            }));
                    }''')
                    assert len(styles)==5,(width,styles)
                    assert all(x['width']<=42 and x['height']<=42 and x['border']=='0px' for x in styles),(width,styles)
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
                page.evaluate("document.body.classList.add('blinq-admin');document.getElementById('telegramGroupsPanel').hidden=false")
                page.wait_for_timeout(50)
                assert page.locator('#bqm-toggle').is_visible()
                page.evaluate("document.getElementById('bqm-projects').dataset.unread='12';document.getElementById('bqm-projects').classList.add('has-unread');document.getElementById('insightUnread').textContent='6';document.getElementById('insightUnread').hidden=false")
                assert page.locator('#bqm-projects').evaluate("n=>getComputedStyle(n,'::after').content")=='"12"'
                bell_box=page.locator('#insightBell').bounding_box()
                badge_box=page.locator('#insightUnread').bounding_box()
                assert badge_box and bell_box and badge_box['x']>=bell_box['x'] and badge_box['x']+badge_box['width']<=bell_box['x']+bell_box['width']+1,(width,bell_box,badge_box)
                assert not page.locator('#topUpgradeButton').is_visible()
                page.locator('#bqm-toggle').click()
                root_text=page.locator('#bqm-dialog nav').inner_text()
                assert 'Výsledky' in root_text,(width,root_text)
                for unwanted in ('Členstvo', 'Komunita', 'Jazyk', 'Môj účet', 'Odhlásiť sa'):
                    assert unwanted not in root_text,(width,root_text)
                page.get_by_role('button',name='Zavrieť menu',exact=True).click()
                page.locator('#profileButton').click()
                assert page.locator('#profileMenu').is_visible()
                menu_box=page.locator('#profileMenu').bounding_box()
                assert menu_box and menu_box['y'] >= 0 and menu_box['y']+menu_box['height'] <= 850,(width,menu_box)
                for label in ('Môj účet', 'Odhlásiť sa', 'Upgrade', 'Komunita', 'Jazyk'):
                    assert page.locator('#profileMenu').get_by_role('button',name=label,exact=(label in ('Upgrade','Komunita','Jazyk'))).is_visible(),(width,label)
                page.locator('#profileMenu').get_by_role('button',name='Jazyk',exact=True).click()
                assert page.locator('#bqm-dialog').is_visible()
                assert page.locator('#bqm-dialog').get_by_role('button',name='SK',exact=True).is_visible()
                page.get_by_role('button',name='← Menu účtu',exact=True).click()
                assert page.locator('#profileMenu').is_visible()
                if width==1440 and os.getenv('BLINQ_SCREENSHOTS'):
                    page.locator('.site-header').screenshot(path=str(Path(os.environ['BLINQ_SCREENSHOTS'])/'admin-header-review.png'))
                assert not errors,(width,errors)
                page.close()
            print('Header rocket/gold navigation, single-row mobile, badges, profile and desktop: PASS')
        finally:
            browser.close()

if __name__=='__main__':main()
