from pathlib import Path
import json
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_media_accepts_real_png_signature_and_rejects_spoofed_png():
    from tbt.services import media_storage as media
    media._validate_image_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 24, "image/png")
    with pytest.raises(ValueError):
        media._validate_image_bytes(b"not-a-png", "image/png")


def test_media_upload_rejects_svg_before_storage_access():
    from tbt.services import media_storage as media
    with pytest.raises(ValueError, match="Unsupported image type"):
        media.upload_media(b"<svg></svg>", content_type="image/svg+xml", original_name="bad.svg")


def test_media_upload_returns_same_origin_proxy(monkeypatch):
    from tbt.services import media_storage as media

    captured = {}

    class Blob:
        def upload_blob(self, data, **kwargs):
            captured["data"] = data
            captured.update(kwargs)

    class Container:
        def get_blob_client(self, media_id):
            captured["media_id"] = media_id
            return Blob()

    monkeypatch.setattr(media, "_container", lambda: Container())
    monkeypatch.setattr(media, "_content_settings", lambda content_type: {"content_type": content_type})
    result = media.upload_media(
        b"\x89PNG\r\n\x1a\n" + b"x" * 32,
        content_type="image/png",
        original_name="banner.png",
        actor_id="admin-1",
    )
    assert result["url"].startswith("/api/v1/media/banner-")
    assert result["url"].endswith(".png")
    assert captured["data"].startswith(b"\x89PNG")
    assert captured["overwrite"] is False


def test_webpush_config_requires_complete_vapid(monkeypatch):
    from tbt.services import push_notifications as push
    for key in ("BLINQ_WEBPUSH_PUBLIC_KEY", "BLINQ_WEBPUSH_PRIVATE_KEY", "BLINQ_WEBPUSH_SUBJECT"):
        monkeypatch.delenv(key, raising=False)
    assert push.webpush_config()["enabled"] is False
    monkeypatch.setenv("BLINQ_WEBPUSH_PUBLIC_KEY", "public")
    monkeypatch.setenv("BLINQ_WEBPUSH_PRIVATE_KEY", "private")
    monkeypatch.setenv("BLINQ_WEBPUSH_SUBJECT", "mailto:ops@example.com")
    cfg = push.webpush_config()
    assert cfg["enabled"] is True
    assert cfg["public_key"] == "public"


def test_push_subscription_accepts_any_active_membership_and_persists(monkeypatch):
    from tbt.services import push_notifications as push

    monkeypatch.setenv("BLINQ_WEBPUSH_ALLOWED_HOSTS", "push.example.test")
    rows = {}

    class Table:
        def upsert_entity(self, row, mode=None):
            rows[row["RowKey"]] = dict(row)

    monkeypatch.setattr(push, "_table", lambda name: Table())
    subscription = {
        "endpoint": "https://push.example.test/subscription/abc",
        "keys": {"p256dh": "p" * 64, "auth": "a" * 22},
    }
    result = push.save_subscription(user_id="u1", subscription=subscription, plan="pro", status="active")
    assert result["subscribed"] is True
    row = next(iter(rows.values()))
    assert row["plan"] == "pro"
    assert json.loads(row["keys_json"])["auth"] == "a" * 22
    with pytest.raises(ValueError, match="active BlinQ membership"):
        push.save_subscription(user_id="u2", subscription=subscription, plan="expired", status="active")


def test_expired_push_subscription_is_not_entitled():
    from tbt.services import push_notifications as push
    assert push._row_entitled({
        "plan": "elite", "status": "active", "expires_at": "2020-01-01T00:00:00+00:00"
    }, {"elite"}) is False
    assert push._row_entitled({
        "plan": "goat", "status": "lifetime", "expires_at": ""
    }, {"goat"}) is True


def test_v723_frontend_and_api_contracts_are_wired():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    auth = (ROOT / "web/auth.js").read_text(encoding="utf-8")
    function_app = (ROOT / "api/function_app.py").read_text(encoding="utf-8")
    index = (ROOT / "web/index.html").read_text(encoding="utf-8")
    static_config = json.loads((ROOT / "web/staticwebapp.config.json").read_text(encoding="utf-8"))

    assert "LIVE & INFO PUSH" in app
    assert "navigator.serviceWorker.register('/blinq-sw.js'" in app
    assert "PushManager" in app
    assert "adminUploadMedia" in auth
    assert "/api/v1/admin/media" in auth
    assert 'route="v1/admin/media"' in function_app
    assert 'route="v1/media/{media_id}"' in function_app
    assert 'route="v1/push/config"' in function_app
    assert 'route="v1/push/subscription"' in function_app
    assert 'rel="manifest" href="/manifest.webmanifest"' in index
    assert "/*.webmanifest" in static_config["navigationFallback"]["exclude"]


def test_service_worker_displays_push_notification():
    service_worker = (ROOT / "web/blinq-sw.js").read_text(encoding="utf-8")
    assert "addEventListener('push'" in service_worker
    assert "showNotification" in service_worker
    assert "addEventListener('notificationclick'" in service_worker


def test_new_info_pushes_only_after_durable_save(monkeypatch):
    from tbt.services import admin_storage
    from tbt.services import push_notifications

    saved = []
    pushed = []

    class Table:
        def upsert_entity(self, entity, mode=None):
            saved.append(dict(entity))

    monkeypatch.setattr(admin_storage, "_table", lambda name: Table())
    monkeypatch.setattr(push_notifications, "dispatch_insight_push", lambda item: pushed.append(dict(item)) or {"sent": 1})
    item = admin_storage.save_insight({
        "title": "Premium info",
        "body": "Test message",
        "type": "info",
        "levels": ["elite", "legend", "goat"],
    }, actor_id="admin")
    assert saved and pushed
    assert pushed[0]["id"] == item["id"]


def test_v723_diagnostics_surface_media_and_push_readiness():
    source = (ROOT / "api/function_app.py").read_text(encoding="utf-8")
    assert 'problems.append("media_storage_unavailable")' in source
    assert 'problems.append("webpush_not_configured")' in source
    assert 'problems.append("webpush_storage_unavailable")' in source


def test_push_endpoint_rejects_local_network_targets():
    from tbt.services import push_notifications as push
    for endpoint in (
        "https://localhost/push",
        "https://127.0.0.1/push",
        "https://169.254.169.254/latest/meta-data",
        "https://service.internal/push",
    ):
        with pytest.raises(ValueError, match="Invalid push endpoint"):
            push._clean_subscription({"endpoint": endpoint, "keys": {"p256dh": "p" * 64, "auth": "a" * 22}})


def test_scheduled_future_info_does_not_push_early():
    from tbt.services import push_notifications as push
    assert push._insight_active_now({
        "active": True,
        "active_from": "2999-01-01T00:00:00+00:00",
        "active_until": "",
    }) is False
