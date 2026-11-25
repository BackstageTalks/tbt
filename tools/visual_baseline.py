#!/usr/bin/env python3
"""Pixel-exact visual regression harness for BlinQ web refactors.

capture: render fixed scenes (guest home, admin) at desktop and phone widths
         from local web/ sources with synthetic fixtures (no network, no
         Firebase/Azure) and save PNGs.
compare: diff two capture dirs; non-zero exit if any pixel differs.

Use before/after CSS or JS cleanup: the look must stay identical.
  python tools/visual_baseline.py capture --out /tmp/vb-before
  python tools/visual_baseline.py capture --out /tmp/vb-after --web path/to/web
  python tools/visual_baseline.py compare /tmp/vb-before /tmp/vb-after
"""
import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import browser_runtime_r43 as rt  # noqa: E402

WIDTHS = {"desktop": 1440, "phone": 390}
FREEZE = """*,*::before,*::after{animation:none!important;transition:none!important;
caret-color:transparent!important}"""
MARK = "  boot();"
ADMIN = """() => {
  document.querySelector('#bootSplash')?.remove();
  document.querySelector('#cookieConsent')?.remove();
  document.querySelectorAll('dialog[open]').forEach(d=>d.close());
  const shell=document.getElementById('appShell'),host=document.getElementById('routePanel');
  shell.hidden=false;host.hidden=false;document.body.classList.remove('blinq-home');
  document.body.classList.add('blinq-admin');
  const h=window.__vb,s=h.state;
  s.route='admin';s.adminTab='layout';s.adminPlan='elite';s.adminLayoutView='access';
  s.uiStorageAvailable=false;s.adminInsights=[];s.adminInfoResults=[];s.adminLiveResults=[];
  s.adminHistoryRetention={info:0,comeback:0,set2:0};
  s.adminInsightsLoading=false;s.adminInfoResultsLoading=false;s.adminLiveResultsLoading=false;
  host.innerHTML=h.renderAdminRoute();h.wireAdmin();
}"""


def _router(web: Path):
    def handle(route):
        path = urlparse(route.request.url).path
        if path == "/app.js":
            src = (web / "app.js").read_text(encoding="utf-8")
            assert src.count(MARK) == 1
            src = src.replace(MARK, "  window.__vb={state,renderAdminRoute,wireAdmin};\n" + MARK)
            route.fulfill(content_type="application/javascript", body=src)
            return
        rel = path.lstrip("/") or "index.html"
        local = (web / rel)
        if web != rt.WEB and local.is_file() and not path.startswith("/api/"):
            ctype = "text/css" if rel.endswith(".css") else (
                "application/javascript" if rel.endswith(".js") else None)
            if ctype:
                route.fulfill(content_type=ctype, body=local.read_bytes())
                return
        rt.static_route(route)
    return handle


def capture(out: Path, web: Path):
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, width in WIDTHS.items():
            for scene in ("home", "admin"):
                page = browser.new_page(viewport={"width": width, "height": 900},
                                        device_scale_factor=1)
                page.clock.install(time=1764000000000)
                page.route("**/*", _router(web))
                page.goto(rt.ORIGIN + "/index.html?lang=sk", wait_until="networkidle")
                page.wait_for_function("window.__vb && __vb.state.ui")
                page.add_style_tag(content=FREEZE)
                if scene == "admin":
                    page.evaluate(ADMIN)
                page.wait_for_timeout(300)
                page.screenshot(path=str(out / f"{scene}-{label}.png"), full_page=True)
                page.close()
        browser.close()
    print("captured", sorted(x.name for x in out.glob("*.png")))


def compare(a: Path, b: Path) -> int:
    from PIL import Image, ImageChops
    bad = 0
    for fa in sorted(a.glob("*.png")):
        fb = b / fa.name
        if not fb.exists():
            print("MISSING", fa.name); bad += 1; continue
        ia, ib = Image.open(fa).convert("RGB"), Image.open(fb).convert("RGB")
        if ia.size != ib.size:
            print("SIZE", fa.name, ia.size, ib.size); bad += 1; continue
        box = ImageChops.difference(ia, ib).getbbox()
        print(("DIFF " + str(box)) if box else "same", fa.name)
        bad += bool(box)
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture"); c.add_argument("--out", type=Path, required=True)
    c.add_argument("--web", type=Path, default=rt.WEB)
    d = sub.add_parser("compare"); d.add_argument("a", type=Path); d.add_argument("b", type=Path)
    a = ap.parse_args()
    if a.cmd == "capture":
        capture(a.out, a.web.resolve())
    else:
        sys.exit(compare(a.a, a.b))


if __name__ == "__main__":
    main()
