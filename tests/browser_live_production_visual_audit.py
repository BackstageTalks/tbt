"""Read-only real-production mobile visual audit. No login, no API writes, no fixtures.

This is an on-demand audit branch; a PR runner captures the actual Azure page.
Screenshots are evidence of a public session, not authenticated entitlement tests.
"""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get(
    "BLINQ_PUBLIC_URL",
    "https://agreeable-sky-011a7fe10.7.azurestaticapps.net",
).rstrip("/")
URL = BASE + "/follow-the-data/#predictions"
OUTPUT = Path(os.environ["BLINQ_SCREENSHOTS"])


def audit(page, width):
    response = page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    if response is None or response.status >= 400:
        raise AssertionError(("production SPA route failed", width, response.status if response else None))
    page.wait_for_function(
        """() => {
          const shell=document.querySelector('#appShell');
          const nav=document.querySelector('#mobileTabs');
          const hero=document.querySelector('#dashboardHero');
          return shell && !shell.hidden && nav && getComputedStyle(nav).display!=='none'
                 && hero && hero.getBoundingClientRect().height>30;
        }""",
        timeout=60000,
    )
    page.wait_for_timeout(1800)
    result = page.evaluate("""() => {
        const rect=el=>{const b=el.getBoundingClientRect();return {top:b.top,bottom:b.bottom,left:b.left,right:b.right,width:b.width,height:b.height}};
        const hero=document.querySelector('#dashboardHero');
        const title=hero?.querySelector('.dashboard-hero-copy h2, .hero-copy h2');
        const nav=document.querySelector('#mobileTabs');
        return {
          width:innerWidth, documentWidth:document.documentElement.scrollWidth,
          hero:hero?rect(hero):null, headline:title?rect(title):null,
          headlineText:title?.innerText||null,
          mobileNav:nav?rect(nav):null,
          navigationLabels:nav?.innerText||'',
          deployedMeta:document.querySelector('meta[name="blinq-deployment-sha"]')?.content||null,
          visualCss:[...document.querySelectorAll('link[rel="stylesheet"]')].find(x=>x.href.includes('blinq-mobile-visual.css'))?.href||null,
          images:[...document.images].filter(x=>x.getBoundingClientRect().width>5).map(x=>({src:x.currentSrc||x.src,complete:x.complete,naturalWidth:x.naturalWidth})).slice(0,15)
        };
    }""")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUTPUT / f"production-live-{width}.png"), full_page=True, animations="disabled")
    (OUTPUT / f"production-live-{width}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    assert result["documentWidth"] <= width + 2, ("horizontal overflow", result)
    assert result["headline"], ("missing live headline", result)
    assert result["headline"]["top"] >= result["hero"]["top"] - 2, ("headline clipped at top", result)
    assert result["headline"]["bottom"] <= result["hero"]["bottom"] + 2, ("headline clipped at bottom", result)
    assert all(name in result["navigationLabels"] for name in ("Predikcie", "Výsledky", "Viac")), result
    assert "visual=20261029-2" in (result["visualCss"] or ""), ("live CSS cache mismatch", result)
    print("Production mobile render verified:", json.dumps({k:result[k] for k in ("width","documentWidth","headlineText","deployedMeta","visualCss")}, ensure_ascii=False))


def main():
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        try:
            for width in (390, 320):
                page=browser.new_page(viewport={"width":width,"height":844},device_scale_factor=1,is_mobile=True,has_touch=True)
                try:
                    audit(page,width)
                finally:
                    page.close()
        finally:
            browser.close()


if __name__=="__main__":
    main()
