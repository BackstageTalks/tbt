"""Offline Chromium regression for clickable, exclusive Admin account activity panes.

Uses only synthetic data. No real users, Telegram or SMTP messages are accessed.
"""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import ORIGIN, WEB, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source=(WEB / "app.js").read_text(encoding="utf-8")
        injection="  window.activityHarness={state,renderAdminAccountActivity,wireAdmin};\n  boot();"
        assert source.count("  boot();")==1
        route.fulfill(content_type="application/javascript",body=source.replace("  boot();",injection))
    else:
        static_route(route)


def open_activity(page):
    page.goto(ORIGIN+"/index.html?lang=sk",wait_until="networkidle")
    page.wait_for_function("window.activityHarness && activityHarness.state.ui")
    page.evaluate("""() => {
      document.querySelector('#bootSplash')?.remove();
      document.querySelector('#cookieConsent')?.remove();
      document.querySelectorAll('dialog[open]').forEach(d=>d.close());
      const shell=document.getElementById('appShell');
      const host=document.getElementById('routePanel');
      shell.hidden=false;host.hidden=false;
      document.body.classList.remove('blinq-home');
      document.body.classList.add('blinq-admin');
      const s=activityHarness.state;
      s.route='admin';s.adminTab='accounts';s.adminActivityView='tg';
      s.adminActivitySearch='';s.adminActivityExpanded=true;
      s.adminUsersLoading=false;s.adminUsersError='';s.adminSelectedUser=null;
      s.adminUsers=[
        {id:'u1',email:'first@example.test',telegram_nick:'@firstuser',plan:'rookie',status:'active'},
        {id:'u2',email:'failed@example.test',telegram_nick:'@seconduser',plan:'rookie',status:'active'},
        {id:'u3',email:'pending@example.test',telegram_nick:'@thirduser',plan:'rookie',status:'active'}
      ];
      const at='2026-10-24T12:00:00Z';
      s.adminActivity={
        items:[
          {target_id:'u1',occurred_at:at,action:'paid_membership_downgraded',
           outcome:'success',after:{email:'first@example.test',from_plan:'legend',to_plan:'rookie',expired_at:at}},
          {target_id:'u1',occurred_at:at,action:'account_email_delivery',
           outcome:'sent',after:{email:'first@example.test',subject:'receipt 7 dní'}},
          {target_id:'u2',occurred_at:at,action:'account_email_delivery',
           outcome:'failed',after:{email:'failed@example.test',subject:'failed notice',error_type:'smtp_not_accepted'}},
          {target_id:'u3',occurred_at:at,action:'account_email_delivery',
           outcome:'pending',after:{email:'pending@example.test',subject:'pending notice'}},
          {target_id:'u2',occurred_at:at,action:'account_access_changed',
           outcome:'success',before:{from_plan:'rookie'},after:{email:'failed@example.test',to_plan:'elite'}}
        ],
        tg_pending:[{event_id:'tg-1',target_id:'u1',occurred_at:at,email:'first@example.test',
                     telegram_nick:'@firstuser',from_plan:'legend',expired_at:at}],
        settings:{retention_days:90}
      };
      host.innerHTML=activityHarness.renderAdminAccountActivity();
      activityHarness.wireAdmin();
    }""")


def check_selection(page,key,label,count):
    page.locator(f'[data-admin-activity-view="{key}"]').click()
    assert page.locator(f'[data-admin-activity-view="{key}"]').get_attribute('aria-pressed')=='true'
    assert page.locator('.admin-activity-stats [aria-pressed="true"]').count()==(0 if key=='other' else 1)
    assert page.locator('.admin-activity-history h4').inner_text()==label
    assert page.locator('.admin-activity-event').count()==count
    assert page.locator('.admin-tg-cleanup').count()==0


def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,
                                   executable_path=os.getenv("BLINQ_BROWSER") or browser_path())
        try:
            for width in (390,768,1280,1440):
                page=browser.new_page(viewport={'width':width,'height':900})
                page.route("**/*",route_request)
                errors=[]
                page.on("pageerror",lambda error:errors.append(str(error)))
                open_activity(page)
                assert page.locator('.admin-activity-stats button').count()==5
                assert page.locator('[data-admin-activity-view="tg"]').get_attribute('aria-pressed')=='true'
                assert page.locator('.admin-tg-cleanup-item').count()==1
                assert page.locator('.admin-activity-events').count()==0
                check_selection(page,'rookie','Prechody na ROOKIE',1)
                assert 'LEGEND' in page.locator('.admin-activity-event').inner_text()
                check_selection(page,'sent','E-maily · SMTP prijaté',1)
                assert 'receipt' in page.locator('.admin-activity-event').inner_text()
                page.locator('#adminActivitySearch').fill('not-matching')
                assert page.locator('.admin-activity-event').count()==0
                page.locator('#adminActivitySearch').fill('receipt')
                assert page.locator('.admin-activity-event').count()==1
                check_selection(page,'failed','Chyby odoslania',1)
                assert page.locator('#adminActivitySearch').input_value()==''
                assert 'smtp_not_accepted' in page.locator('.admin-activity-event').inner_text()
                check_selection(page,'pending','E-maily · naplánované',1)
                assert 'Naplánované' in page.locator('.admin-activity-event').inner_text()
                check_selection(page,'other','Ostatné udalosti',1)
                assert 'Zmena prístupu' in page.locator('.admin-activity-event').inner_text()
                assert not page.locator('#adminActivityRetention').is_visible()
                page.locator('.admin-activity-management summary').click()
                assert page.locator('#adminActivityRetention').is_visible()
                assert page.locator('#adminActivityRetention').input_value()=='90'
                assert page.locator('[data-admin-action="clear-activity"]').is_visible()
                page.locator('[data-admin-activity-view="tg"]').click()
                assert page.locator('.admin-tg-cleanup-item').count()==1
                page.evaluate("""() => {
                    window.confirm=()=>true;
                    window.BlinqAuth.adminConfirmTelegramCleanup=async()=>({
                      event_id:'tg-1',confirmed_at:'2026-10-25T12:00:00Z'
                    });
                }""")
                page.locator('[data-admin-action="tg-cleanup-confirm"]').click()
                page.wait_for_function("""() => document.querySelector('[data-admin-activity-view="tg"] strong')?.textContent==='0'""")
                assert page.locator('.admin-tg-cleanup-item').count()==0
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
                assert not errors,(width,errors)
                page.close()
                print('PASS focused account activity views at',width)
        finally:
            browser.close()


if __name__=="__main__":
    main()
