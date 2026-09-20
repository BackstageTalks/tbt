from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
AUTH = (ROOT / "web" / "auth.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
API = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")


def test_r34_auth_boot_is_independent_from_runtime_ui_config():
    assert "Promise.allSettled([loadUiConfig(),BlinqAuth.init()])" in APP
    assert "if(uiResult.status==='rejected')console.warn" in APP
    assert "if(authResult.status==='rejected')throw authResult.reason" in APP
    assert "cfg.enabled&&String(cfg.provider||'').toLowerCase()==='firebase'" in APP


def test_r34_auth_config_retries_once_on_transient_failure():
    assert "for (const delay of [0, 350])" in AUTH
    assert "config = await json('/api/v1/auth/config')" in AUTH
    assert "if (!config) throw lastError" in AUTH


def test_r34_ui_config_storage_failure_is_public_fallback_not_500():
    block = API[API.index('@app.route(route="v1/ui-config"'):API.index('@app.route(route="v1/content/news"')]
    assert '"storage_available": False' in block
    assert ', 503)' not in block


def test_r34_loader_and_login_share_page_background_and_watermark():
    assert 'boot-splash.boot-splash-tennis{position:fixed!important;inset:0!important;background-image:' in CSS
    assert 'url("/assets/blinq_page_background.webp")!important' in CSS
    assert '.auth-dialog[open]::after' in CSS
    assert 'opacity:.08' in CSS
    assert 'BlinQ runtime patch 7.3.6-r34' in CSS
