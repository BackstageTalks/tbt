"""Offline layout/photo regression: no requests reach an external service."""
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == '/app.js':
        source = (WEB / 'app.js').read_text(encoding='utf-8').replace('  boot();', '''
  window.releaseTest={state,renderDailyHub,renderDashboardKpis,renderTelegramGroupsPanel,buildDemoMatch,playerPhotoSource,playerAvatarHtml};
  boot();''')
        route.fulfill(content_type='application/javascript', body=source)
    else:
        static_route(route)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=os.getenv('BLINQ_BROWSER') or browser_path())
        try:
            for width in (390, 768, 1440, 1920):
                page = browser.new_page(viewport={'width': width, 'height': 1000})
                page.route('**/*', route_request)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(ORIGIN+'/index.html?lang=sk', wait_until='networkidle')
                page.wait_for_function('releaseTest.state.ui && document.querySelector(".dashboard-kpi")')
                # boot() may remove the splash as soon as the feed loads.
                # Probe the actual stylesheet using a temporary matching node.
                loader_background = page.evaluate('''() => {
                    const splash=document.createElement('div');
                    splash.className='boot-splash boot-splash-tennis';
                    document.body.append(splash);
                    const background=getComputedStyle(splash).backgroundImage;
                    splash.remove();
                    return background;
                }''')
                assert 'blinq_background.webp' in loader_background, (width, loader_background)
                # Login watermark remains deliberately independent of home.
                assert 'blinq_logo.svg' in page.evaluate('''() => {
                    const dialog=document.querySelector('#authDialog');
                    const wasOpen=dialog.hasAttribute('open');
                    if(!wasOpen)dialog.setAttribute('open','');
                    const image=getComputedStyle(dialog,'::after').backgroundImage;
                    if(!wasOpen)dialog.removeAttribute('open');
                    return image;
                }''')
                # Verify the existing animation frame receives the shared site
                # background, including if the boot JS already removed splash.
                assert page.evaluate('''() => {
                  let splash=document.querySelector('#bootSplash'),temporary=false;
                  if(!splash){splash=document.createElement('div');splash.className='boot-splash boot-splash-tennis';document.body.append(splash);temporary=true;}
                  const image=getComputedStyle(splash).backgroundImage;
                  if(temporary)splash.remove();
                  return image.includes('blinq_background.webp');
                }'''), width
                page.evaluate('''() => {
                  document.querySelector('#bootSplash')?.remove();
                  document.querySelector('#appShell').hidden=false;
                  document.querySelector('#cookieConsent')?.remove();
                  document.querySelectorAll('dialog[open]').forEach(d=>d.close());
                  const t=releaseTest;
                  t.state.feed.account={plan:'rookie',status:'active'};
                  t.state.ui.dashboard.match_detail.plans.rookie=false;
                  t.state.feed.daily_picks=[t.buildDemoMatch(0,'top_daily')];
                  t.state.feed.entitlements={sections:{daily:{enabled:true,total:1,returned:1,blur_remaining:false},ace:{enabled:true,total:3,returned:0,locked_count:3,display_state:'blurred'}}};
                  t.state.ui.telegram_groups.groups.push({...t.state.ui.telegram_groups.groups[0],id:'test-third',title:'BlinQ Updates',description:'Dlhší opis komunity pre kontrolu spoločnej výšky a zarovnania tlačidiel.'});
                  t.state.dailyHubTab='daily';
                  t.renderDailyHub();t.renderDashboardKpis();t.renderTelegramGroupsPanel();
                }''')
                page.wait_for_timeout(150)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), width
                boxes = [page.locator(s).bounding_box() for s in ('#dashboardKpis','#dailyHub','#telegramGroupsPanel','.site-footer')]
                assert max(b['x'] for b in boxes)-min(b['x'] for b in boxes) <= 1, (width, boxes)
                assert max(b['width'] for b in boxes)-min(b['width'] for b in boxes) <= 1, (width, boxes)
                cards = page.locator('.dashboard-kpi')
                sizes = [cards.nth(i).bounding_box() for i in range(3)]
                assert max(b['width'] for b in sizes)-min(b['width'] for b in sizes) <= 1
                if width > 760:
                    assert abs(sizes[-1]['x']+sizes[-1]['width']-boxes[0]['x']-boxes[0]['width']) <= 1
                    assert len({b['y'] for b in sizes}) == 1
                else:
                    assert len({b['y'] for b in sizes}) == 3, (width, sizes, page.locator('#dashboardKpis').evaluate('(e)=>getComputedStyle(e).gridTemplateColumns'))
                assert 'blinq_background.webp' in page.locator('body').evaluate('(e)=>getComputedStyle(e).backgroundImage')
                # Home stays free of global/hero/footer watermark overlays.  Only
                # individual predictions receive a small, non-interactive mark.
                assert page.locator('#dashboardHero').evaluate(
                    '(e) => getComputedStyle(e, "::after").display'
                ) == 'none'
                assert page.locator('#dashboardHero .slot-watermark').count() == 0
                assert page.locator('.anti-share-watermarks:visible').count() == 0
                match_cell = page.locator('#dailyHubBody tr:not(.hub-row-locked) .hub-match-cell').first
                assert match_cell.count() == 1, width
                assert 'blinq_logo.svg' in match_cell.evaluate(
                    '(e) => getComputedStyle(e, "::after").backgroundImage'
                )
                assert match_cell.evaluate(
                    '(e) => getComputedStyle(e, "::after").pointerEvents'
                ) == 'none'
                loader = page.locator('#bootSplash')
                # The preproduction harness removes bootSplash above; confirm
                # the deployed CSS rule itself still references shared artwork.
                css_source = (WEB / 'blinq-app.css').read_text(encoding='utf-8')
                assert 'visual revision home-wm-20260924' in css_source
                button = page.locator('.hub-detail.is-locked').first
                assert button.is_visible(), (width, page.locator('#dailyHub').inner_text(), page.locator('#dailyHubBody').inner_html())
                assert button.evaluate('(e)=>getComputedStyle(e).flexDirection') == 'row'
                assert button.evaluate('(e)=>getComputedStyle(e).display') == 'inline-flex'
                label, icon = [button.locator(s).bounding_box() for s in ('span','i')]
                assert abs(label['y']+label['height']/2-icon['y']-icon['height']/2) <= 1
                assert page.locator('#appShell').evaluate('(e)=>getComputedStyle(e,"::after").display') == 'none'
                assert page.locator('#dashboardHero').evaluate('(e)=>getComputedStyle(e,"::after").content') == 'none'
                assert page.locator('#dashboardHero .slot-watermark').count() == 0
                assert page.locator('.site-footer .footer-watermark-logo').count() == 0
                match = page.locator('#dailyHubBody tr:not(.hub-row-locked) .hub-match-cell').first
                assert match.count(), (width, page.locator('#dailyHubBody').inner_html())
                assert match.evaluate('''e => {
                  const wm=getComputedStyle(e,'::after');
                  return wm.content!=='none' && wm.backgroundImage.includes('blinq_logo.svg')
                    && parseFloat(wm.opacity)<=0.10;
                }'''), width
                assert button.locator('svg').count() == 1
                # Safe versioned local photos must survive both source selection
                # and avatar rendering; no malformed second question mark.
                page.evaluate('''() => {
                  const t=releaseTest, photo=t.playerPhotoSource(null,{photo_url:'/assets/players/42.webp?v=1'});
                  if(!photo)throw Error('versioned photo discarded');
                  const markup=t.playerAvatarHtml(photo,'Player','ATP');
                  if(!markup.includes('42.webp?v=1&amp;p=736-r61'))throw Error(markup);
                  if(t.playerPhotoSource(null,{photo_url:'/assets/../secret.png'}))throw Error('unsafe photo accepted');
                }''')
                if os.getenv('BLINQ_SCREENSHOTS'):
                    dest=Path(os.environ['BLINQ_SCREENSHOTS']);dest.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(dest/f'dashboard-{width}.png'),full_page=True)
                page.evaluate('''() => {
                  releaseTest.state.feed.daily_picks=[];
                  releaseTest.state.feed.entitlements.sections.daily={enabled:true,total:0,returned:0,blur_remaining:false};
                  releaseTest.renderDailyHub();
                }''')
                assert page.locator('#dailyHubEmpty').is_visible()
                assert page.locator('#dailyHubEmpty').evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)') >= 14
                assert not errors, errors
                page.close()
                print(f'PASS preproduction browser regression at {width}px')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
