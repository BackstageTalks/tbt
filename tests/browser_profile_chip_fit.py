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
                }""")
                result=page.evaluate("""() => {
                    const shell=document.getElementById('profileShell');
                    const btn=document.getElementById('profileButton');
                    const toggle=document.getElementById('profileMenuToggle');
                    const menu=document.getElementById('profileMenu');
                    menu.hidden=false;
                    const round=r=>({top:r.top,bottom:r.bottom,left:r.left,right:r.right,
                                    centerY:(r.top+r.bottom)/2});
                    const s=round(shell.getBoundingClientRect());
                    const b=round(btn.getBoundingClientRect());
                    const t=round(toggle.getBoundingClientRect());
                    const svg=round(toggle.querySelector('svg').getBoundingClientRect());
                    const m=round(menu.getBoundingClientRect());
                    const overflow=getComputedStyle(shell).overflow;
                    menu.hidden=true;
                    return {shell:s,button:b,toggle:t,svg,menu:m,overflow};
                }""")
                s=result["shell"]
                for part in ("button","toggle"):
                    b=result[part]
                    assert b["top"]>=s["top"]-0.5,(width,part,result)
                    assert b["bottom"]<=s["bottom"]+0.5,(width,part,result)
                    assert b["left"]>=s["left"]-0.5,(width,part,result)
                    assert b["right"]<=s["right"]+0.5,(width,part,result)
                assert abs(result["toggle"]["centerY"]-result["svg"]["centerY"])<=1,(width,result)
                assert result["menu"]["top"]>=s["bottom"],(width,result)
                assert result["overflow"]=="visible",(width,result)
                assert not errors,(width,errors)
                page.close()
                print(f"PASS: {width}px profile outline and unclipped dropdown")
        finally:
            browser.close()


if __name__=="__main__":
    main()
