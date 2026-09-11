from pathlib import Path
import inspect
from types import SimpleNamespace

import pytest

from tbt.services import account_storage, admin_storage, auth, content_news
from tbt.services.auth import account_access, public_account

ROOT = Path(__file__).resolve().parents[1]


def _user(**overrides):
    data = {
        "id": "u1",
        "email": "member@example.com",
        "email_verified": True,
        "created_at": "2026-09-11T10:00:00+00:00",
        "app_metadata": {},
        "user_metadata": {"display_name": "Member"},
    }
    data.update(overrides)
    return data


def test_no_runtime_email_admin_backdoor_remains():
    runtime = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in (
        "api/tbt/config.py",
        "api/tbt/services/auth.py",
        "api/function_app.py",
    ))
    assert "BLINQ_ADMIN_EMAILS" not in runtime
    assert "blinq_admin_emails" not in runtime


def test_suspended_admin_is_not_admin():
    access = account_access(_user(app_metadata={"role": "admin", "blinq_status": "suspended"}))
    assert access["status"] == "suspended"
    assert access["is_admin"] is False
    assert access["role"] == "user"


def test_profile_fields_are_not_read_from_firebase_claims():
    account = public_account(
        _user(app_metadata={"blinq_avatar_variant": "w"}),
        profile={"avatar_variant": "m", "telegram_nick": "@member123"},
    )
    assert account["avatar_variant"] == "m"
    assert account["telegram_nick"] == "@member123"


def test_profile_writer_never_mutates_custom_claims():
    source = inspect.getsource(auth.update_firebase_profile)
    assert "set_custom_user_claims" not in source


@pytest.mark.parametrize("url", [
    "//evil.example/path",
    "http://evil.example/path",
    "https://user:pass@evil.example/path",
])
def test_destination_rejects_protocol_relative_http_and_credentials(url):
    assert admin_storage._valid_destination(url) is False


def test_destination_accepts_safe_internal_and_https():
    assert admin_storage._valid_destination("/account") is True
    assert admin_storage._valid_destination("#pricing") is True
    assert admin_storage._valid_destination("https://example.com/page") is True


@pytest.mark.parametrize("url", [
    "http://example.com/feed.xml",
    "https://localhost/feed.xml",
    "https://127.0.0.1/feed.xml",
    "https://10.0.0.1/feed.xml",
    "https://192.168.1.2/feed.xml",
    "https://[::1]/feed.xml",
])
def test_rss_fetch_guard_rejects_unsafe_targets(url):
    assert content_news._safe_http_url(url) == ""


def test_rss_fetch_guard_accepts_public_https_hostname():
    assert content_news._safe_http_url("https://example.com/feed.xml") == "https://example.com/feed.xml"


def test_profile_validation_normalizes_telegram_and_avatar():
    normalized = account_storage.normalize_profile_update({
        "telegram_nick": "blinq_user",
        "blinq_avatar_variant": "W",
        "display_name": "BlinQ User",
    })
    assert normalized["telegram_nick"] == "@blinq_user"
    assert normalized["avatar_variant"] == "w"


def test_preview_pages_are_not_in_production_web_root():
    assert not (ROOT / "web/preview.html").exists()
    assert not (ROOT / "web/pro-preview.html").exists()


def test_security_headers_are_present():
    swa = (ROOT / "web/staticwebapp.config.json").read_text(encoding="utf-8")
    for token in ("object-src 'none'", "frame-src 'none'", "frame-ancestors 'none'", "upgrade-insecure-requests"):
        assert token in swa


def test_frontend_rejects_protocol_relative_links_and_catches_common_email_typo():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    assert "!text.startsWith('//')" in app
    assert "gmail.comr" in app
    assert "gmail.con" in app


def test_failed_login_clears_prior_local_session_before_new_credential_attempt():
    auth_js = (ROOT / "web/auth.js").read_text(encoding="utf-8")
    marker = "async function signInFirebase(email, password) {"
    pos = auth_js.index(marker)
    nearby = auth_js[pos:pos + 700]
    assert "clear();" in nearby


def test_release_and_asset_versions_are_consistent():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    config = (ROOT / "web/ui-config.json").read_text(encoding="utf-8")
    function_app = (ROOT / "api/function_app.py").read_text(encoding="utf-8")
    assert '"ui_revision": "6.5.34"' in config
    assert 'RELEASE = "6.5.34"' in function_app
    for asset in ("styles.css", "responsive.css", "premium.css", "auth.js", "responsive.js", "app.js"):
        assert f"/{asset}?v=6534" in html


def test_profile_save_is_patch_like_and_does_not_clear_omitted_fields(monkeypatch):
    class Table:
        def __init__(self):
            self.row = {
                "PartitionKey": "account", "RowKey": account_storage._key("u1"),
                "user_id": "u1", "telegram_nick": "@existing_user", "avatar_variant": "w",
            }
        def upsert_entity(self, entity, mode="merge"):
            assert mode == "merge"
            self.row.update(entity)
        def get_entity(self, partition_key, row_key):
            return dict(self.row)
    table = Table()
    monkeypatch.setattr(account_storage, "_table", lambda name: table)
    saved = account_storage.save_profile_metadata("u1", {"display_name": "New Name"})
    assert saved["telegram_nick"] == "@existing_user"
    assert saved["avatar_variant"] == "w"


def test_admin_access_normalizer_rejects_nonsensical_admin_expired_status():
    from tbt.services.admin_accounts import normalize_access_update
    with pytest.raises(ValueError, match="Admin status"):
        normalize_access_update({"role": "admin", "status": "expired"})
