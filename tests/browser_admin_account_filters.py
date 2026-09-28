"""Offline Chromium regression for BlinQ admin account filters and sorting.

The fixture is synthetic: no account APIs, credentials, or private users are accessed.
"""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source=(WEB / "app.js").read_text(encoding="utf-8")
        injection="  window.accountHarness={state,renderAdminAccounts,wireAdmin};\n  boot();"
        assert source.count("  boot();")==1
        route.fulfill(content_type="application/javascript",
                      body=source.replace("  boot();",injection))
    else:
        static_route(route)


def visible_nicks(page):
    return [x.strip() for x in page.locator(
        ".admin-simple-user-list .admin-simple-user-row:visible .admin-simple-user-main b"
    ).all_inner_texts()]


def assert_results(page,nicks):
    actual=visible_nicks(page)
    assert actual==nicks,(actual,nicks)
    assert page.locator("#adminFilteredCount").inner_text()==str(len(nicks))


def assert_column_alignment(page, label):
    geometry=page.evaluate("""() => {
      const head=document.querySelector('.admin-simple-user-head');
      const row=document.querySelector('.admin-simple-user-row:not([hidden])');
      const headers=[...head.children].map(e=>e.getBoundingClientRect().left);
      const cells=[...row.children].map(e=>e.getBoundingClientRect().left);
      return {headers,cells,tableWidth:head.getBoundingClientRect().width,
        headDisplay:getComputedStyle(head).display,rowDisplay:getComputedStyle(row).display};
    }""")
    assert geometry["headDisplay"]=="grid" and geometry["rowDisplay"]=="grid",(label,geometry)
    for column in (1,2,3):  # Level, expiry, status. Chevron is right-aligned by design.
        delta=abs(geometry["headers"][column]-geometry["cells"][column])
        assert delta<=2.5,(label,column,geometry)
    # The Level track must not get pushed to the far right, leaving a huge empty user track.
    ratio=(geometry["headers"][1]-geometry["headers"][0])/geometry["tableWidth"]
    assert ratio<0.72,(label,ratio,geometry)


def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,
                                   executable_path=os.getenv("BLINQ_BROWSER") or browser_path())
        try:
            for width in (390,1024,1280,1440,1920):
                page=browser.new_page(viewport={"width":width,"height":900})
                page.route("**/*",route_request)
                errors=[]
                page.on("pageerror",lambda e:errors.append(str(e)))
                page.goto(ORIGIN+"/index.html?lang=sk",wait_until="networkidle")
                page.wait_for_function("window.accountHarness && accountHarness.state.ui")
                page.evaluate("""() => {
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelectorAll('dialog[open]').forEach(d=>d.close());
                    const shell=document.getElementById('appShell');
                    const host=document.getElementById('routePanel');
                    shell.hidden=false;host.hidden=false;
                    document.body.classList.remove('blinq-home');
                    document.body.classList.add('blinq-admin');
                    const s=accountHarness.state;
                    s.route='admin';s.adminTab='accounts';s.adminSelectedUser=null;
                    s.adminUsersLoading=false;s.adminUsersError='';
                    s.adminUserFilters={q:'',plan:'all',status:'all',sort:'email'};
                    s.adminUsers=[
                        {id:'u1',email:'a@example.test',telegram_nick:'@Zara',plan:'rookie',status:'active'},
                        {id:'u2',email:'z@example.test',telegram_nick:'@Franta',plan:'elite',status:'active',
                         expires_at:'2026-12-10T00:00:00Z'},
                        {id:'u3',email:'b@example.test',telegram_nick:'@Ladislav',plan:'elite',status:'expired',
                         expires_at:'2026-08-10T00:00:00Z'},
                        {id:'u4',email:'y@example.test',telegram_nick:'@Adam',plan:'pro',status:'active'}
                    ];
                    host.innerHTML=accountHarness.renderAdminAccounts();
                    accountHarness.wireAdmin();
                }""")
                assert_results(page,["@Zara","@Ladislav","@Adam","@Franta"])
                if width>860:
                    assert_column_alignment(page,f"full-width {width}px")
                page.locator("#adminUserSearch").fill("franta")
                assert_results(page,["@Franta"])
                page.locator("#adminUserLevelFilter").select_option("elite")
                assert_results(page,["@Franta"])
                page.locator("#adminUserStatusFilter").select_option("expired")
                assert_results(page,[])
                assert page.locator("#adminUserFilterEmpty").is_visible()
                page.locator("#adminUserSearch").fill("")
                assert_results(page,["@Ladislav"])
                assert not page.locator("#adminUserFilterEmpty").is_visible()
                page.locator("#adminUserStatusFilter").select_option("all")
                assert_results(page,["@Ladislav","@Franta"])
                page.locator("#adminUserLevelFilter").select_option("all")
                page.locator("#adminUserSort").select_option("telegram")
                assert_results(page,["@Adam","@Franta","@Ladislav","@Zara"])
                if width==1440:
                    split=page.locator('.admin-accounts-split-v22')
                    split.evaluate("""node=>{
                      node.classList.remove('no-selection');
                      node.classList.add('has-selection');
                      node.querySelector('.admin-simple-user-editor-wrap').innerHTML='<div>Editor fixture</div>';
                    }""")
                    assert_column_alignment(page,"with-editor 1440px")
                assert not errors,(width,errors)
                page.close()
                print("PASS admin account filters/search/sort at",width)
        finally:
            browser.close()


if __name__=="__main__":
    main()
