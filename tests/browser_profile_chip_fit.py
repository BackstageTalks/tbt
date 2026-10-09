"""Offline browser check for the desktop profile outline and dropdown."""
import os
from playwright.sync_api import sync_playwright
from browser_runtime_r43 import ORIGIN, browser_path, static_route


def main():
    with sync_playwright() as pw:
        executable=os.getenv("BLINQ_BROWSER") or browser_path()
        browser=(pw.chromium.launch(headless=True,executable_path=executable)
                 if executable else pw.chromium.launch(headless=True))
        try:
            for width in (1280,1440,1920):
                page=browser.new_page(viewport={"width":width,"height":900})
                page.route("**/*",static_route)
                errors=[]
                page.on("pageerror",lambda e:errors.append(str(e)))
                page.goto(ORIGIN+"/index.html?lang=sk",wait_until="networkidle")
                page.evaluate("""() => {
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelectorAll('dialog[open]').forEach(d=>d.close());
                    document.querySelector('#appShell').hidden=false;
                    document.body.classList.remove('blinq-admin');
                    document.getElementById('profileName').textContent='@BackstageTalks';
                    const projects=document.getElementById('projectGroupBar');
                    projects.hidden=false;
                    projects.innerHTML='<button class="project-group-chip is-purple" data-project-group-open="one"><span>◆</span><strong>Platba PO</strong><b>1</b></button>';
                    const live=document.getElementById('insightShortcut');
                    live.hidden=false;
                    const info=document.getElementById('insightBell');
                    info.hidden=false;
                    const upgrade=document.getElementById('topUpgradeButton');
                    upgrade.hidden=false;
                }""")
                result=page.evaluate("""() => {
                    const shell=document.getElementById('profileShell');
                    const btn=document.getElementById('profileButton');
                    const toggle=document.getElementById('profileMenuToggle');
                    const menu=document.getElementById('profileMenu');
                    assert menu.hidden, 'legacy profile dropdown must stay closed';
                    const round=r=>({top:r.top,bottom:r.bottom,left:r.left,right:r.right,
                                    centerY:(r.top+r.bottom)/2});
                    const s=round(shell.getBoundingClientRect());
                    const b=round(btn.getBoundingClientRect());
                    const t=round(toggle.getBoundingClientRect());
                    const svg=round(toggle.querySelector('svg').getBoundingClientRect());
                    const menuHidden=getComputedStyle(menu).display==='none';
                    const overflow=getComputedStyle(shell).overflow;
                    const controls=['#bqm-projects','#insightShortcut','#topUpgradeButton','#insightBell','#profileShell']
                      .map(sel=>({sel,rect:round(document.querySelector(sel).getBoundingClientRect())}));
                    return {shell:s,button:b,toggle:t,svg,menuHidden,overflow,controls};
                }""")
                s=result["shell"]
                for part in ("button","toggle"):
                    b=result[part]
                    assert b["top"]>=s["top"]-0.5,(width,part,result)
                    assert b["bottom"]<=s["bottom"]+0.5,(width,part,result)
                    assert b["left"]>=s["left"]-0.5,(width,part,result)
                    assert b["right"]<=s["right"]+0.5,(width,part,result)
                assert abs(result["toggle"]["centerY"]-result["svg"]["centerY"])<=1,(width,result)
                assert result["menuHidden"],(width,result)
                assert result["overflow"]=="visible",(width,result)
                controls=result["controls"]
                heights=[round(item["rect"]["bottom"]-item["rect"]["top"],1) for item in controls]
                centers=[item["rect"]["centerY"] for item in controls]
                assert max(heights)-min(heights)<=0.5,(width,heights,result)
                assert max(centers)-min(centers)<=1.0,(width,centers,result)
                assert all(abs(h-42)<=0.5 for h in heights),(width,heights,result)
                page.locator('#profileButton').click()
                assert page.locator('#bqm-dialog').is_visible(),(width,'shared dialog missing')
                assert page.locator('#bqm-account-panel').is_visible(),(width,'account section not expanded')
                assert page.locator('#profileMenu').is_hidden(),(width,'duplicate account dropdown')
                page.get_by_role('button',name='Zavrieť menu').click()
                assert not errors,(width,errors)
                page.close()
                print(f"PASS: {width}px profile outline and unified account menu")
        finally:
            browser.close()


if __name__=="__main__":
    main()
