"""Read-only, explicitly opted-in BlinQ startup diagnostics.

The standard URL keeps the exact existing startup behavior; only a manual
?blinq_boot_trace=1 request reports timing milestones, without telemetry writes.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
BOOT = APP[APP.index("async function boot(){"):]
PROBE = APP[
    APP.index("// Read-only, opt-in startup timing."):
    APP.index("function finishBootSplash(){")
]


def test_diagnostics_are_query_opt_in_and_read_only():
    assert "get('blinq_boot_trace')==='1'" in PROBE
    assert "if(!enabled)return null;" in PROBE
    assert "performance.now()" in PROBE
    assert "performance.getEntriesByType('navigation')" in PROBE
    assert "setTimeout(()=>showBootTracePanel(message),450);" in PROBE
    assert "window.alert(message)" not in PROBE
    assert "fetch(" not in PROBE
    assert "localStorage" not in PROBE
    assert "sessionStorage" not in PROBE
    assert "document.body" not in PROBE


def test_boot_request_dependency_order_remains_unchanged():
    assert "const uiReady=loadUiConfig(true)" in BOOT
    assert "const authReady=BlinqAuth.init()" in BOOT
    assert "const prefetchedFeed=session?BlinqAuth.feed():null;" in BOOT
    assert "if(prefetchedFeed)prefetchedFeed.catch(()=>{});" in BOOT
    assert BOOT.index("const prefetchedFeed=") < BOOT.index("await authReady")
    assert BOOT.index("await uiReady;") < BOOT.index("bootPrefetchedFeed=prefetchedFeed;")
    assert BOOT.index("bootPrefetchedFeed=prefetchedFeed;") < BOOT.index("await loadFeed();")
    assert "bootTimingProbe?.report();" in BOOT


def test_stage_markers_cover_network_and_render_without_changing_loader():
    assert "markBootTiming('Spustenie JS')" in BOOT
    assert "markBootTiming('Obnovenie relácie dokončené')" in BOOT
    assert "markBootTiming('UI konfigurácia pripravená')" in BOOT
    assert "markBootTiming('Autentifikácia pripravená')" in BOOT
    assert "markBootTiming('Feed API odpoveď')" in BOOT
    assert "markBootTiming('Feed prevzatý')" in APP
    assert "markBootTiming('Dashboard vykreslený')" in APP
    assert "markBootTiming('Dashboard odkrytý')" in APP
    assert "markBootTiming('Loader ukončený')" in BOOT
    assert "function finishBootSplash(){const splash=$('bootSplash');" in APP
    assert "loadAdminDraft(); renderAllUiContent(); populateFilters();" in APP
    assert "BlinqAuth.feed()" in APP


def test_full_size_opt_in_dialog_displays_copyable_text_without_touching_normal_ui():
    panel = APP[APP.index("function showBootTracePanel(message){"):
                APP.index("// Read-only, opt-in startup timing.")]
    assert "document.createElement('dialog')" in panel
    assert "width:min(98vw,1120px);height:92vh" in panel
    assert "dialog.showModal();" in panel
    assert "output.textContent=message;" in panel
    assert "navigator.clipboard.writeText(message)" in panel
    assert "Kopírovať celý výpis" in panel
    assert "dialog.addEventListener('close',()=>dialog.remove(),{once:true})" in panel
    assert "innerHTML" not in panel
    assert "fetch(" not in panel
    assert "localStorage" not in panel
