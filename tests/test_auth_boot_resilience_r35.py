import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
AUTH = (ROOT / "web" / "auth.js").read_text(encoding="utf-8")
API = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
SWA = json.loads((ROOT / "web" / "staticwebapp.config.json").read_text(encoding="utf-8"))
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_auth_boot_is_not_coupled_to_ui_config():
    assert "Promise.allSettled([loadUiConfig(),BlinqAuth.init()])" not in APP
    assert "UI config failed; auth remains available" in APP
    assert "authEnabled:true" in APP
    assert "BlinqAuth.ensureReady()" in APP


def test_auth_runtime_has_bounded_retry_and_client_degraded_mode():
    assert "const AUTH_RUNTIME = '736-r45'" in AUTH
    assert "AUTH_CONFIG_ATTEMPTS = 3" in AUTH
    assert "degradedClientConfig" in AUTH
    assert "async function ensureReady()" in AUTH
    assert "await ensureReady();" in AUTH
    assert "typeof AbortSignal !== 'undefined'" in AUTH


def test_backend_config_validates_firebase_admin_material():
    assert "firebase_app(settings)" in API
    assert '"server_ready": False' in API
    assert '"firebase_server_config_invalid"' in API


def test_auth_critical_assets_are_never_served_from_stale_cache():
    routes = {route.get("route"): route for route in SWA["routes"]}
    for path in ("/auth.js", "/app.js", "/responsive.js", "/ui-config.json"):
        assert path in routes
        assert "no-store" in routes[path]["headers"]["Cache-Control"]


def test_deploy_contract_checks_frontend_and_server_auth_readiness():
    assert "AUTH_RUNTIME = '736-r${patch}'" in CI
    assert "Smoke deployed authentication readiness" in CI
    assert "data.get('server_ready') is True" in CI
