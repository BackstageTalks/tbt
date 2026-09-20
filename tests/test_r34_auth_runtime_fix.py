from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
AUTH = (ROOT / "web" / "auth.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
API = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")


def test_r34_independence_is_preserved_and_strengthened_by_r35():
    assert "Promise.allSettled([loadUiConfig(),BlinqAuth.init()])" not in APP
    assert "UI config failed; auth remains available" in APP
    assert "const authReady=BlinqAuth.init()" in APP
    assert "BlinqAuth.ensureReady()" in APP
    assert "cfg.enabled&&String(cfg.provider||'').toLowerCase()==='firebase'" in APP


def test_r35_auth_config_has_bounded_retry_and_safe_degraded_mode():
    assert "AUTH_CONFIG_ATTEMPTS = 3" in AUTH
    assert "await json(AUTH_CONFIG_URL, {timeoutMs: 6000})" in AUTH
    assert "degradedClientConfig" in AUTH
    assert "isPermanentAuthConfigError" in AUTH
    assert "async function ensureReady()" in AUTH


def test_r34_ui_config_storage_failure_is_public_fallback_not_500():
    block = API[API.index('@app.route(route="v1/ui-config"'):API.index('@app.route(route="v1/content/news"')]
    assert '"storage_available": False' in block
    assert ', 503)' not in block


def test_r34_loader_and_login_visual_closeout_is_preserved_in_r35():
    assert 'boot-splash.boot-splash-tennis{position:fixed!important;inset:0!important;background-image:' in CSS
    assert 'url("/assets/blinq_page_background.webp")!important' in CSS
    assert '.auth-dialog[open]::after' in CSS
    assert 'opacity:.08' in CSS
    assert 'BlinQ runtime patch 7.3.6-r34' in CSS
    assert 'BlinQ runtime patch 7.3.6-r35' in CSS
