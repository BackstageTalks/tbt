import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path

def route_request(route):
    if urlparse(route.request.url).path == '/app.js':
        source=(WEB/'app.js').read_text(encoding='utf-8')
        source=source.replace('  boot();', "  window.accessTest={state,showUpgradePrompt};\n  boot();")
        route.fulfill(content_type='application/javascript',body=source)
    else:
        static_route(route)

with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path=os.getenv('BLINQ_BROWSER') or browser_path())
    for width in (1440,390):
        context=browser.new_context(viewport={'width':width,'height':900})
        context.route('**/*',route_request)
        page=context.new_page()
        page.goto(ORIGIN+'/index.html?lang=sk',wait_until='networkidle')
        page.wait_for_function('window.accessTest')
        page.evaluate("""() => {
          document.querySelectorAll('dialog[open]').forEach(d=>d.close());
          document.querySelector('#bootSplash')?.remove();
          document.querySelector('#cookieConsent')?.remove();
          document.querySelector('#appShell').hidden=false;
          accessTest.state.route='predictions';
          const fixture=document.createElement('div');
          fixture.innerHTML='<button id="lockedFixture" data-upgrade-plan="elite" data-upgrade-section="SETS" style="position:fixed;left:40px;top:180px;z-index:210"><span>Locked</span></button>';
          document.body.append(fixture);
        }""")
        trigger=page.locator('#lockedFixture')
        trigger.hover(); page.wait_for_timeout(380)
        trigger.focus(); page.locator('#accessHintUpgrade').focus(); page.wait_for_timeout(250)
        page.keyboard.press('Enter'); page.wait_for_timeout(100)
        page.keyboard.press('Escape'); page.wait_for_timeout(100)
        state=page.evaluate("""() => ({
          activeId:document.activeElement?.id||'',activeTag:document.activeElement?.tagName||'',
          triggerFocused:document.activeElement===document.querySelector('#lockedFixture'),
          triggerDisplay:getComputedStyle(document.querySelector('#lockedFixture')).display,
          triggerVisibility:getComputedStyle(document.querySelector('#lockedFixture')).visibility,
          dialogOpen:document.querySelector('#upgradeDialog').open
        })""")
        print(width,state)
        context.close()
    browser.close()
