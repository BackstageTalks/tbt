"""Browser regression: authenticated Blob screenshots must render under production CSP."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import struct
from threading import Thread
import zlib

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
CSP = json.loads((WEB / "staticwebapp.config.json").read_text(encoding="utf-8"))["globalHeaders"]["Content-Security-Policy"]
SCREENSHOT_ID = "insight-20261025112700-deadbeef1234-12345678.png"


def image_png():
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xFFFFFFFF)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x9b\x77\xff"))
        + chunk(b"IEND", b"")
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            data = b'<!doctype html><html><head><script defer src="/insight-media.js"></script></head><body><div id="root"></div></body></html>'
            mime = "text/html; charset=utf-8"
        elif path == "/insight-media.js":
            data = (WEB / "insight-media.js").read_bytes()
            mime = "application/javascript"
        elif path == "/private-image":
            if self.headers.get("X-Blinq-Access-Token") != "screenshot-test-token":
                self.send_error(403, "Authorization required")
                return
            data = image_png()
            mime = "image/png"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
                violations = []
                page.on("console", lambda message: violations.append(message.text) if "Content Security Policy" in message.text else None)
                page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="load")
                page.evaluate(
                    """(id) => {
                        window.BlinqAuth={
                            sessionEpochKey:()=> 'test-epoch',
                            insightMedia:async () => {
                                const r=await fetch('/private-image',{headers:{'X-Blinq-Access-Token':'screenshot-test-token'}});
                                if(!r.ok)throw Error('Not authorized');
                                return r.blob();
                            }
                        };
                        localStorage.setItem('test-epoch','signed-in');
                        const root=document.getElementById('root');
                        root.innerHTML=window.BlinqInsightMedia.gallery([id]);
                        root.querySelector('img').style.cssText='display:block;width:100px;height:90px';
                        window.BlinqInsightMedia.loadImages(root);
                        // Main app wires this delegated click handler; reproduce it in the isolated CSP harness.
                        root.querySelector('[data-insight-image-open]').onclick=e=>window.BlinqInsightMedia.open(e.currentTarget);
                    }""",
                    SCREENSHOT_ID,
                )
                page.wait_for_function(
                    "()=>{const img=document.querySelector('[data-private-insight-image]');return !!img && img.complete && img.naturalWidth===1;}",
                    timeout=10000,
                )
                image_src = page.locator("[data-private-insight-image]").get_attribute("src")
                assert image_src and image_src.startswith("blob:"), image_src
                page.locator("[data-insight-image-open]").click()
                page.wait_for_function(
                    "()=>{const img=document.querySelector('.insight-screenshot-lightbox img');return !!img && img.complete && img.naturalWidth===1;}",
                    timeout=10000,
                )
                page.get_by_role("button", name="Zavrieť obrázok").click()
                assert page.locator(".insight-screenshot-lightbox").count() == 0
                assert not violations, violations
                print("Private screenshot browser test: PNG rendered under CSP, fullscreen rendered, close worked — PASS")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
