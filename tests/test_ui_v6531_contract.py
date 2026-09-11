import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_version_and_asset_cache_keys_are_consistent():
    cfg = json.loads(text("web/ui-config.json"))
    assert cfg["ui_revision"] == "6.5.31"
    html = text("web/index.html")
    for asset in ("styles.css", "responsive.css", "premium.css", "auth.js", "responsive.js", "app.js"):
        assert f'/{asset}?v=6531' in html


def test_server_owned_entitlements_are_wired_into_feed():
    api = text("api/function_app.py")
    ent = text("api/tbt/services/entitlements.py")
    app = text("web/app.js")
    assert "filter_feed_for_access" in api
    assert "account_suspended" in api
    assert "SECTION_TO_FEED_KEY" in ent
    assert "state.feed?.entitlements?.sections?.[key]" in app


def test_admin_requires_explicit_verified_claim():
    auth = text("api/tbt/services/auth.py")
    api = text("api/function_app.py")
    assert "return str(app.get(\"role\") or \"\").strip().lower() == \"admin\"" in auth
    assert 'if not bool(user.get("email_verified", False))' in api
    assert "Legacy bootstrap admins" not in api


def test_backup_files_do_not_ship_from_web_root():
    assert not list((ROOT / "web").glob("*.bak*"))


def test_security_headers_are_present():
    config = json.loads(text("web/staticwebapp.config.json"))
    headers = config["globalHeaders"]
    assert headers["X-Frame-Options"] == "DENY"
    assert "max-age=" in headers["Strict-Transport-Security"]
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "camera=()" in headers["Permissions-Policy"]
