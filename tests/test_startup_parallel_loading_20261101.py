"""Regression guards for the non-blocking BlinQ startup path."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
ROUTES = json.loads((ROOT / "web" / "staticwebapp.config.json").read_text(encoding="utf-8"))["routes"]


def test_presentation_requests_start_before_runtime_config_wait():
    start = APP.index("async function loadUiConfig(deferInitialRender=false)")
    end = APP.index("async function ", start + 10)
    body = APP[start:end]
    assert "const presentationReady=fetchEditablePresentationConfig().catch(()=>null);" in body
    assert body.index("const presentationReady=") < body.index("await Promise.allSettled([")
    assert body.index("await loadEditablePresentationConfig(presentationReady);") > body.index(
        "state.ui=clone(state.uiSource);"
    )


def test_authenticated_feed_prefetch_overlaps_auth_and_ui_but_not_render():
    boot = APP[APP.index("async function boot(){"):]
    assert "const uiReady=loadUiConfig(true)" in boot
    assert "const prefetchedFeed=session?BlinqAuth.feed():null;" in boot
    assert "if(prefetchedFeed)prefetchedFeed.catch(()=>{});" in boot
    assert boot.index("const prefetchedFeed=") < boot.index("await authReady")
    assert boot.index("await uiReady") < boot.index("bootPrefetchedFeed=prefetchedFeed;") < boot.index("await loadFeed();")
    assert "const pendingFeed=bootPrefetchedFeed;bootPrefetchedFeed=null;" in APP
    assert "const feed=(await (pendingFeed||BlinqAuth.feed()))||{};" in APP
    assert "async function loadFeed(showLoading=true){" in APP
    assert "if(generation!==feedGeneration)return;" in APP


def test_static_resources_can_reuse_browser_cache_but_runtime_config_cannot():
    routes = {route["route"]: route["headers"].get("Cache-Control", "") for route in ROUTES}
    # Preserve the production freshness policy for both CSS and critical scripts.
    for path in ("/", "/index.html", "/release.json", "/ui-config.json",
                 "/blinq-app.css", "/auth.js", "/app.js",
                 "/responsive.js", "/insight-media.js"):
        assert "no-store" in routes[path]
    assert "cache:'no-store'" in APP  # live config remains uncached
    assert "fast-boot=20261101-1" in HTML

def test_boot_defers_hidden_dashboard_render_but_preserves_public_login():
    config = APP[APP.index("async function loadUiConfig(deferInitialRender=false)"):APP.index("function applyAccessContractV1")]
    boot = APP[APP.index("async function boot(){"):]
    feed = APP[APP.index("async function loadFeed(showLoading=true){"):APP.index("async function refreshWorkspace(showLoading=false){")]
    assert "if(!deferInitialRender)renderAllUiContent();" in config
    assert "const uiReady=loadUiConfig(true)" in boot
    assert "uiReady.then(loaded=>{if(loaded&&$('appShell').hidden)renderAllUiContent();})" in boot
    assert "if(!session){" in boot
    assert "finishBootSplash();" in boot
    assert feed.index("const feed=(await (pendingFeed||BlinqAuth.feed()))||{};") < feed.index("renderAllUiContent();")
    assert feed.index("renderAllUiContent();") < feed.index("$('appShell').hidden=false")
