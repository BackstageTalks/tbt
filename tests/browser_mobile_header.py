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
            for width in (320,360,390,430,500,768,900,1440):
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
                    h.state.ui.notifications={enabled:true,live_min_level:'elite'};h.renderInsightBell();h.renderProjectGroupBar();
                    const row={event_id:'test',scheduled_at:new Date(Date.now()+3600000).toISOString(),tour:'ATP',tournament:'Beijing, China',surface:'hard',player1:{id:'one',name:'Andrey Rublev',rank:26},player2:{id:'two',name:'Roman Safiullin',rank:102},pick:'Andrey Rublev',model_probability:.703,odds:1.67};
                    document.getElementById('dailyHubBody').innerHTML=h.dailyHubRow(row,'daily',false,0);
                    document.getElementById('dailyHubEmpty').hidden=true;
                    window.groupCalls=[];
                    document.getElementById('projectGroupBar').onclick=e=>{const b=e.target.closest('[data-project-group-open]');if(b)groupCalls.push(b.dataset.projectGroupOpen);};
                }''')
                page.wait_for_timeout(200)
                # LIVE lock reflects actual member access; no change to icon size.
                live=page.locator('#insightShortcut')
                lock=page.locator('#insightShortcut .live-access-lock')
                assert live.get_attribute('data-upgrade-plan')=='elite',(width,'LIVE minimum')
                assert 'is-access-locked' in live.get_attribute('class'),(width,'LIVE access class')
                assert lock.is_visible(),(width,'missing LIVE padlock')
                # Real account access, not synthetic CSS: rookie has LIVE locked.
                page.locator('.header-top > .brand').click()
                assert page.locator('#bqm-dialog nav').get_by_role('button',name='Live radar 🔒',exact=True).is_visible(),(width,'LIVE menu access lock')
                assert page.locator('#bqm-menu-scrim').is_visible(),(width,'on-page menu scrim missing')
                menu_state=page.evaluate("""() => {
                    const menu=document.getElementById('bqm-dialog');
                    const scrim=document.getElementById('bqm-menu-scrim');
                    const box=menu.getBoundingClientRect();
                    const color=getComputedStyle(scrim).backgroundColor;
                    return {
                      nonModal: !menu.matches(':modal'),
                      mainVisible: !!document.getElementById('mainContent').getBoundingClientRect().height,
                      width: box.width, viewport:innerWidth,
                      scrimColor:color,
                      isInline: menu.dataset.anchor === 'brand',
                    };
                }""")
                assert menu_state['nonModal'] and menu_state['mainVisible'] and menu_state['isInline'],(width,menu_state)
                # Gold/yellow header and menu lettering is now white on both layouts.
                colors=page.evaluate("""() => {
                    const read=selector=>{
                        const el=document.querySelector(selector);
                        return el ? getComputedStyle(el).color : null;
                    };
                    return {
                        navigation:read('.header-top .reference-navigation[data-icon-navigation="1"] > .nav-icon-link'),
                        chevron:read('.header-top .brand-menu-chevron'),
                        menu:read('#bqm-dialog[open] nav > .bqm-navigation-switch'),
                    };
                }""")
                assert colors['navigation']=='rgb(245, 251, 248)',(width,colors)
                assert colors['chevron']=='rgb(245, 251, 248)',(width,colors)
                assert colors['menu']=='rgb(245, 251, 248)',(width,colors)
                assert menu_state['width'] < width,(width,'menu should not fill the page',menu_state)
                assert not menu_state['scrimColor'].endswith(', 1)'),(width,'scrim must preserve page context',menu_state)

                page.get_by_role('button',name='Zavrieť menu').click()
                page.wait_for_function("!document.getElementById('bqm-dialog').open")
                page.evaluate("""() => {mobileTest.state.feed.account.plan='elite';mobileTest.renderInsightBell();}""")
                page.locator('.header-top > .brand').click()
                assert page.locator('#bqm-dialog nav').get_by_role('button',name='Live radar',exact=True).is_visible(),(width,'LIVE menu unlock')
                page.get_by_role('button',name='Zavrieť menu').click()
                page.wait_for_function("!document.getElementById('bqm-dialog').open")
                page.evaluate("""() => {mobileTest.state.feed.account.plan='rookie';mobileTest.renderInsightBell();}""")
                live_geom=page.evaluate("""() => {
                    const b=document.querySelector('#insightShortcut').getBoundingClientRect();
                    const l=document.querySelector('#insightShortcut .live-access-lock').getBoundingClientRect();
                    return {buttonWidth:b.width,lockWidth:l.width,lockHeight:l.height,
                      lockLeft:l.left,lockRight:l.right};
                }""")
                assert 11<=live_geom['lockWidth']<=16 and 11<=live_geom['lockHeight']<=16,(width,live_geom)
                assert live_geom['lockLeft']>=0 and live_geom['lockRight']<=width+2,(width,live_geom)
                # Approved tennis-ball icon must keep two unmistakable curved seams
                # on the actual header and its dormant mobile-navigation fallback.
                tennis_paths=page.evaluate("""() => {
                    const selectors=['.header-top .nav-icon-tennis',
                                     '.mobile-icon-nav [data-route="predictions"] svg'];
                    return selectors.map(q=>{
                        const svg=document.querySelector(q);
                        return svg ? [...svg.querySelectorAll('path')].map(p=>p.getAttribute('d')) : [];
                    });
                }""")
                assert len(tennis_paths)==2 and tennis_paths[0]==tennis_paths[1],(width,tennis_paths)
                assert len(tennis_paths[0])==2,(width,'expected two distinctive ball seams')
                # Real brand file opens the menu; there is no second hamburger.
                brand=page.locator('.header-top > .brand')
                assert brand.locator('img.brand-source-logo').get_attribute('src')=='/assets/blinq_logo.svg'
                assert page.locator('#bqm-toggle').is_hidden(),(width,'old hamburger still visible')
                assert brand.locator('.brand-menu-chevron').is_visible()
                assert brand.get_attribute('role')=='button'
                assert brand.get_attribute('aria-controls')=='bqm-dialog'
                assert brand.get_attribute('aria-expanded')=='false'
                assert page.locator('#profileButton').get_attribute('aria-controls')=='bqm-dialog'
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
                    assert len(icon_fit['visible'])==9,(width,icon_fit)
                    assert not icon_fit['overlap'],(width,icon_fit)
                    assert icon_fit['left']>=0 and icon_fit['right']<=width+1,(width,icon_fit)
                    assert icon_fit['overflow']<=2,(width,icon_fit)
                    # The chart and rocket are adjacent parts of ONE icon strip.
                    # Previously the auto margin left a large central hole.
                    seam=page.evaluate("""() => {
                        const left=document.querySelector('.header-top [data-route="compare"]').getBoundingClientRect();
                        const right=document.querySelector('#bqm-projects').getBoundingClientRect();
                        return right.left-left.right;
                    }""")
                    assert 0 <= seam <= 32,(width,'disconnected navigation groups',seam)
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
                    desktop_seam=page.evaluate("""() => {
                        const chart=document.querySelector('.header-top [data-route="compare"]').getBoundingClientRect();
                        const rocket=document.querySelector('#bqm-projects').getBoundingClientRect();
                        return rocket.left-chart.right;
                    }""")
                    assert 0 <= desktop_seam <= 24,(width,'desktop icon-strip gap',desktop_seam)
                if width<=900:
                    assert page.locator('#bqm-projects').is_visible()
                    assert page.locator('#bqm-projects').get_attribute('data-unread')=='1'
                    assert page.locator('#insightUnread').is_visible()
                    assert page.locator('#insightUnread').inner_text()=='1'
                    if width==390:
                        # LIVE counts unread published alerts, not active radar signals.
                        page.evaluate("""() => {
                            const h=mobileTest, s=h.state;
                            s.feed.account.plan='elite';
                            s.insights.push({id:'live-unread-test',read:false,type:'alert',audience_mode:'levels'});
                            s.userLiveRadarStatus={signals:4,candidates:7};
                            h.renderInsightBell();
                        }""")
                        assert lock.is_hidden(), 'eligible LIVE cannot display locked badge'
                        assert live.get_attribute('data-upgrade-plan') is None
                        assert 'is-access-locked' not in live.get_attribute('class')
                        assert abs(live.bounding_box()['width']-live_geom['buttonWidth'])<1
                        assert page.locator('#insightShortcutCount').is_visible()
                        assert page.locator('#insightShortcutCount').inner_text()=='1'
                        assert '1 neprečítaných' in page.locator('#insightShortcut').get_attribute('aria-label')
                        page.evaluate("""() => {
                            const h=mobileTest, s=h.state;
                            s.insights.find(item=>item.id==='live-unread-test').read=true;
                            h.renderInsightBell();
                        }""")
                        assert page.locator('#insightShortcutCount').is_hidden(), 'Radar signals must not masquerade as unread alerts'
                        page.evaluate("""() => {
                            const h=mobileTest, s=h.state;
                            s.insights=s.insights.filter(item=>item.id!=='live-unread-test');
                            s.userLiveRadarStatus=null;
                            s.feed.account.plan='rookie';
                            h.renderInsightBell();
                        }""")
                        assert lock.is_visible(), 'padlock must return for Rookie'
                        assert 'is-access-locked' in live.get_attribute('class')
                    geometry=page.evaluate('''() => {
                        const els=['.header-top>.brand','#bqm-projects','#insightBell','#profileButton'].map(s=>document.querySelector(s).getBoundingClientRect());
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
                    assert page.locator('#bqm-dialog').is_visible()
                    assert page.locator('#bqm-account-panel').is_visible()
                    assert page.locator('#profileMenu').is_hidden()
                    assert page.locator('#bqm-dialog').get_by_role('button',name='Odhlásiť sa').is_visible()
                    page.get_by_role('button',name='Zavrieť menu').click()
                    page.wait_for_function("!document.getElementById('bqm-dialog').open")
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
                assert page.locator('#bqm-toggle').is_hidden(),(width,'legacy hamburger returned in admin')
                assert brand.locator('.brand-menu-chevron').is_visible(),(width,'brand menu chevron missing')
                assert brand.get_attribute('role')=='button'
                # Admin uses the same complete icon strip as the public site:
                # 3 primary routes plus the existing project, LIVE, bell and avatar.
                admin_layout=page.evaluate("""() => {
                    const view = n => {
                        const r=n.getBoundingClientRect(),cs=getComputedStyle(n);
                        return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,
                                visible:cs.display!=='none'&&cs.visibility!=='hidden'&&!n.hidden&&r.width>0&&r.height>0};
                    };
                    const header=view(document.querySelector('.site-header .header-top'));
                    const nav=[...document.querySelectorAll('.header-top .reference-navigation .nav-icon-link')].map(view);
                    const actions=['#bqm-projects','#insightShortcut','#topUpgradeButton','#insightBell','#profileButton']
                        .map(s=>({selector:s,...view(document.querySelector(s))}));
                    const all=[...nav,...actions].filter(n=>n.visible).sort((a,b)=>a.left-b.left);
                    const overlap=all.some((r,i)=>i>0&&r.left<all[i-1].right-1);
                    const outside=all.some(r=>r.left<-1||r.right>innerWidth+1);
                    return {header,nav,actions,overlap,outside,viewport:innerWidth};
                }""")
                assert len(admin_layout['nav'])==3 and all(n['visible'] for n in admin_layout['nav']),(width,'admin missing public navigation',admin_layout)
                # Entitlement / group availability is authoritative; any control
                # that is not hidden must keep its public-header presence.
                for sel in ('#bqm-projects','#insightShortcut','#topUpgradeButton','#insightBell','#profileButton'):
                    icon_visible=next(a['visible'] for a in admin_layout['actions'] if a['selector']==sel)
                    expected=page.locator(sel).get_attribute('hidden') is None
                    assert icon_visible==expected,(width,'admin action visibility mismatch',sel,admin_layout)
                assert not admin_layout['overlap'] and not admin_layout['outside'],(width,'admin header icons overlap/overflow',admin_layout)
                page.evaluate("document.getElementById('bqm-projects').dataset.unread='12';document.getElementById('bqm-projects').classList.add('has-unread');document.getElementById('insightUnread').textContent='6';document.getElementById('insightUnread').hidden=false")
                assert page.locator('#bqm-projects').evaluate("n=>getComputedStyle(n,'::after').content")=='"12"'
                bell_box=page.locator('#insightBell').bounding_box()
                badge_box=page.locator('#insightUnread').bounding_box()
                assert badge_box and bell_box and badge_box['x']>=bell_box['x'] and badge_box['x']+badge_box['width']<=bell_box['x']+bell_box['width']+1,(width,bell_box,badge_box)
                upgrade=page.locator('#topUpgradeButton')
                assert upgrade.is_visible()==(upgrade.get_attribute('hidden') is None),(width,'upgrade visibility should follow entitlement')
                brand.click()
                assert page.locator('#bqm-dialog').is_visible()
                assert brand.get_attribute('aria-expanded')=='true'
                # The logo prioritizes navigation; the avatar prioritizes
                # the account. Order must be real DOM order, not CSS only.
                section_order=page.locator('#bqm-dialog nav').evaluate(
                    "n=>[...n.children].map(c=>c.classList[0])"
                )
                assert section_order==['bqm-navigation-switch','bqm-navigation-panel','bqm-account-switch','bqm-account-panel'],(width,section_order)
                assert page.locator('#bqm-navigation-panel').is_visible(),(width,'logo should open navigation')
                assert page.locator('#bqm-account-panel').is_hidden(),(width,'logo should keep account collapsed')
                assert page.locator('.bqm-navigation-switch').get_attribute('aria-expanded')=='true'
                # Use the configured main-page artwork with dark overlay, not a flat gradient.
                background=page.locator('#bqm-dialog').evaluate("(n)=>getComputedStyle(n).backgroundImage")
                assert 'url(' in background and 'gradient' in background,(width,'missing home-page artwork',background)
                root_text=page.locator('#bqm-dialog nav').inner_text()
                assert 'Výsledky' in root_text,(width,root_text)
                # Locked LIVE must show the same padlock as its header button.
                page.get_by_role('button',name='Zavrieť menu').click()
                page.wait_for_function("!document.getElementById('bqm-dialog').open")
                page.evaluate("""() => {
                    const n=document.getElementById('insightShortcut');
                    n.hidden=false;
                    n.dataset.upgradePlan='pro';
                    n.classList.add('is-access-locked');
                }""")
                brand.click()
                assert page.locator('#bqm-dialog nav').get_by_role('button',name='Live radar 🔒',exact=True).is_visible(),width
                page.get_by_role('button',name='Zavrieť menu').click()
                page.wait_for_function("!document.getElementById('bqm-dialog').open")
                page.evaluate("""() => {
                    const n=document.getElementById('insightShortcut');
                    delete n.dataset.upgradePlan;
                    n.classList.remove('is-access-locked');
                }""")
                brand.click()
                assert page.locator('#bqm-dialog nav').get_by_role('button',name='Live radar',exact=True).is_visible(),width
                root_text=page.locator('#bqm-dialog nav').inner_text()
                assert 'Môj účet' in root_text,(width,root_text)
                assert not page.locator('#bqm-account-panel').is_visible()
                for unwanted in ('Profil a členstvo', 'Odhlásiť sa', 'Jazyk'):
                    assert unwanted not in root_text,(width,root_text)
                page.get_by_role('button',name='Zavrieť menu',exact=True).click()
                page.wait_for_function("document.querySelector('.header-top > .brand').getAttribute('aria-expanded')==='false'")
                assert brand.get_attribute('aria-expanded')=='false'
                if width==390:
                    brand.focus()
                    page.keyboard.press('Space')
                    assert page.locator('#bqm-dialog').is_visible(), 'logo must support keyboard space'
                    page.keyboard.press('Escape')
                    assert not page.locator('#bqm-dialog').is_visible()
                page.locator('#profileButton').click()
                assert page.locator('#bqm-dialog').is_visible()
                avatar_section_order=page.locator('#bqm-dialog nav').evaluate(
                    "n=>[...n.children].map(c=>c.classList[0])"
                )
                assert avatar_section_order==['bqm-account-switch','bqm-account-panel','bqm-navigation-switch','bqm-navigation-panel'],(width,avatar_section_order)
                assert page.locator('.bqm-account-switch').get_attribute('aria-expanded')=='true'
                assert page.locator('#profileMenu').is_hidden(),(width,'old profile dropdown must stay closed')
                assert page.locator('#bqm-account-panel').is_visible()
                assert page.locator('#bqm-navigation-panel').is_hidden(),(width,'avatar should collapse navigation by default')
                assert page.locator('.bqm-navigation-switch').get_attribute('aria-expanded')=='false'
                # Users can switch between sections without navigating away.
                page.locator('.bqm-navigation-switch').click()
                assert page.locator('#bqm-navigation-panel').is_visible()
                assert page.locator('#bqm-account-panel').is_hidden()
                page.locator('.bqm-account-switch').click()
                assert page.locator('#bqm-navigation-panel').is_hidden()
                assert page.locator('#bqm-account-panel').is_visible()
                assert page.locator('#bqm-dialog .bqm-account-switch').get_attribute('aria-expanded')=='true'
                assert page.locator('#profileButton').get_attribute('aria-expanded')=='true'
                menu_box=page.locator('#bqm-dialog').bounding_box()
                assert menu_box and menu_box['y'] >= 0 and menu_box['y']+menu_box['height'] <= 850,(width,menu_box)
                for label in ('Profil a členstvo', 'Odhlásiť sa', 'Upgrade', 'Komunita', 'Jazyk'):
                    assert page.locator('#bqm-account-panel').get_by_role('button',name=label,exact=True).is_visible(),(width,label)
                if width == 1440:
                    account_box=page.locator('#bqm-dialog').bounding_box()
                    assert account_box['x'] > 750,(width,'account menu should anchor near avatar',account_box)
                page.locator('#bqm-account-panel').get_by_role('button',name='Jazyk',exact=True).click()
                assert page.locator('#bqm-dialog').is_visible()
                assert page.locator('#bqm-dialog').get_by_role('button',name='SK',exact=True).is_visible()
                page.get_by_role('button',name='← Môj účet',exact=True).click()
                assert page.locator('#bqm-account-panel').is_visible()
                assert page.locator('#profileMenu').is_hidden()
                if width==1440 and os.getenv('BLINQ_SCREENSHOTS'):
                    page.locator('.site-header').screenshot(path=str(Path(os.environ['BLINQ_SCREENSHOTS'])/'admin-header-review.png'))
                assert not errors,(width,errors)
                page.close()
            print('Unified logo/avatar menu, account accordion, unchanged icons and badges: PASS')
        finally:
            browser.close()

if __name__=='__main__':main()
