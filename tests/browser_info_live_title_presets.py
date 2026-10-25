"""Offline Chromium regression for multi-select Premium/FREE headings in INFO and LIVE.

Uses synthetic composer messages only; no authenticated APIs or publishing.
"""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source=(WEB / "app.js").read_text(encoding="utf-8")
        injection="  window.headingHarness={state,adminInsightMessageHtml,syncAdminInsightTitle,wireAdmin};\n  boot();"
        assert source.count("  boot();")==1
        route.fulfill(content_type="application/javascript",body=source.replace("  boot();",injection))
    else:
        static_route(route)


def test_width(browser,width):
    page=browser.new_page(viewport={"width":width,"height":900})
    page.route("**/*",route_request)
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)))
    page.goto(ORIGIN+"/index.html?lang=sk",wait_until="networkidle")
    page.wait_for_function("window.headingHarness && headingHarness.state.ui")
    page.evaluate("""() => {
      document.querySelector('#bootSplash')?.remove();
      document.querySelector('#cookieConsent')?.remove();
      document.querySelectorAll('dialog[open]').forEach(d=>d.close());
      const shell=document.getElementById('appShell');
      const host=document.getElementById('routePanel');
      shell.hidden=false;host.hidden=false;
      document.body.classList.remove('blinq-home');
      document.body.classList.add('blinq-admin');
      const h=window.headingHarness,s=h.state;
      s.route='admin';s.adminTab='insights';s.adminInsightEditingId='';
      host.innerHTML='<form id="adminInsightForm" data-editing="0">'+
        '<div class="admin-insight-message-list">'+
        h.adminInsightMessageHtml(0,{} )+
        h.adminInsightMessageHtml(1,{title:'Premium · FREE · Nový zápas'})+
        h.adminInsightMessageHtml(2,{title:'Pôvodný vlastný nadpis'})+
        '</div><button id="adminInsightSubmit" type="button">Publikovať</button></form>';
      h.wireAdmin();
    }""")
    blocks=page.locator('[data-insight-message]')
    assert blocks.count()==3
    block=blocks.nth(0)
    assert block.locator('[data-insight-title]').input_value()==''
    assert not block.locator('[data-insight-title-dropdown]').evaluate("(d)=>d.open")
    block.locator('summary').click()
    block.locator('[data-insight-title-preset][value="Premium"]').check()
    assert block.locator('[data-insight-title]').input_value()=='Premium'
    block.locator('[data-insight-title-preset][value="FREE"]').check()
    assert block.locator('[data-insight-title]').input_value()=='Premium · FREE'
    block.locator('[data-insight-custom-title]').fill('Nová analýza')
    assert block.locator('[data-insight-title]').input_value()=='Premium · FREE · Nová analýza'
    assert block.locator('[data-insight-title-preview]').inner_text()=='Premium · FREE · Nová analýza'
    block.locator('[data-insight-title-preset][value="Premium"]').uncheck()
    assert block.locator('[data-insight-title]').input_value()=='FREE · Nová analýza'
    block.locator('[data-insight-title-preset][value="FREE"]').uncheck()
    assert block.locator('[data-insight-title]').input_value()=='Nová analýza'
    block.locator('[data-insight-custom-title]').fill('')
    assert block.locator('[data-insight-title]').input_value()==''  # image-only stays valid

    saved=blocks.nth(1)
    assert saved.locator('[data-insight-title-preset][value="Premium"]').is_checked()
    assert saved.locator('[data-insight-title-preset][value="FREE"]').is_checked()
    assert saved.locator('[data-insight-custom-title]').input_value()=='Nový zápas'
    assert saved.locator('[data-insight-title]').input_value()=='Premium · FREE · Nový zápas'

    legacy=blocks.nth(2)
    assert legacy.locator('[data-insight-custom-title]').input_value()=='Pôvodný vlastný nadpis'
    assert legacy.locator('[data-insight-title]').input_value()=='Pôvodný vlastný nadpis'
    assert legacy.locator('[data-insight-title-preset]:checked').count()==0

    # Both presets consume the same 140-character maximum as a normal heading.
    saved.locator('[data-insight-custom-title]').fill('x'*140)
    assert saved.locator('[data-insight-title-count]').inner_text().endswith('/140')
    assert saved.locator('[data-insight-title-count]').get_attribute('class')=='is-over-limit'
    assert not saved.locator('[data-insight-custom-title]').evaluate('(el)=>el.checkValidity()')
    saved.locator('[data-insight-custom-title]').fill('Krátky text')
    assert saved.locator('[data-insight-custom-title]').evaluate('(el)=>el.checkValidity()')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
    assert not errors,(width,errors)
    page.close()


def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,
                                   executable_path=os.getenv("BLINQ_BROWSER") or browser_path())
        try:
            for width in (390,768,1440):
                test_width(browser,width)
                print('PASS INFO/LIVE heading presets at',width)
        finally:
            browser.close()


if __name__=="__main__":
    main()
