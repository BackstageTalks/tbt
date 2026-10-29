"""Real Chromium regression for compact mobile banners with Admin-set text coordinates.

Offline fixture: no production account, requests, or API data are mutated.
The live screenshot showed a promo banner clipped at the top when mobile Y was
set close to zero. Keep editor placement when it fits, adjust only overflow.
"""
import os
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser_runtime_r43 import WEB, ORIGIN, static_route, browser_path


def route_request(route):
    if urlparse(route.request.url).path == "/app.js":
        source=(WEB / "app.js").read_text(encoding="utf-8")
        marker="  boot();"
        assert source.count(marker)==1
        source=source.replace(marker, "  window.bannerFitTest={state,renderHeroBanner};\n" + marker)
        route.fulfill(content_type="application/javascript",body=source)
    else:
        static_route(route)


def check(page, y, width):
    page.evaluate("""y => {
        const t=window.bannerFitTest, s=t.state;
        const content=s.ui.elements.HERO_BANNER_1.content;
        s.ui.hero_banner.slot_count=1;
        s.ui.hero_banner.auto_rotate=false;
        s.heroIndex=0;
        s.ui.elements.HERO_BANNER_1.content={
            ...content, enabled:true, type:'promo', eyebrow:'',
            headline:'Všetci chcú byť v nej, iba zopár môže',
            text:'Pridaj sa >>', button_text:'',
            mobile_text_x:7, mobile_text_y:y, mobile_text_width:84,
            mobile_headline_size:18, mobile_text_size:12,
            image_url:'/assets/hero-reference-exact-v680.webp'
        };
        t.renderHeroBanner();
    }""", y)
    page.wait_for_timeout(200)
    result=page.evaluate("""() => {
        const hero=document.querySelector('#dashboardHero .hero-slide.is-active');
        const copy=hero?.querySelector('.dashboard-hero-copy');
        const head=copy?.querySelector('h2');
        const p=copy?.querySelector('p');
        const rect=e=>e?({top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom,height:e.getBoundingClientRect().height}):null;
        return {hero:rect(hero),copy:rect(copy),headline:rect(head),subtitle:rect(p),
          text:copy?.innerText,inlineTop:copy?.style.top||null,body:document.body.className};
    }""")
    assert result["hero"] and result["copy"] and result["headline"] and result["subtitle"], result
    assert result["hero"]["height"] >= 120, (width,y,result)
    assert result["copy"]["top"] >= result["hero"]["top"] + 7, (width,y,result)
    assert result["copy"]["bottom"] <= result["hero"]["bottom"] - 7, (width,y,result)
    assert result["headline"]["top"] >= result["hero"]["top"], (width,y,result)
    assert result["subtitle"]["bottom"] <= result["hero"]["bottom"], (width,y,result)
    assert 'Všetci chcú byť v nej' in result["text"], result
    if y==50:
        assert result["inlineTop"] is None, ("valid editor position should not be changed",width,result)
    else:
        assert result["inlineTop"], ("clipped editor position must be corrected",width,y,result)
    print(f"PASS compact mobile banner width={width}, editorY={y}%",flush=True)


def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=os.getenv("BLINQ_BROWSER") or browser_path())
        try:
            for width in (390,430):
                page=browser.new_page(viewport={"width":width,"height":844})
                page.route("**/*",route_request)
                page.goto(ORIGIN+"/index.html?lang=sk",wait_until="networkidle")
                page.wait_for_function("window.bannerFitTest && bannerFitTest.state.ui && document.body.classList.contains('bqm-enabled')")
                page.evaluate("""() => {
                    document.querySelector('#bootSplash')?.remove();
                    document.querySelector('#cookieConsent')?.remove();
                    document.querySelectorAll('dialog[open]').forEach(el=>el.close());
                    document.querySelector('#appShell').hidden=false;
                }""")
                for y in (0,50,95):
                    check(page,y,width)
                page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
