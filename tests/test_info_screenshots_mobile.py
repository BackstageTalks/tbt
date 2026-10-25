"""Regression tests for private INFO/LIVE screenshot attachments."""
from pathlib import Path
import json
import pytest

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ID = "insight-20261025112700-deadbeef1234-12345678.png"


def test_insight_media_scope_is_private_and_uses_existing_blob_storage(monkeypatch):
    from tbt.services import media_storage as media

    captured = {}

    class Blob:
        def upload_blob(self, data, **kwargs):
            captured.update(kwargs)
            captured["bytes"] = data

    class Container:
        def get_blob_client(self, name):
            captured["media_id"] = name
            return Blob()

    monkeypatch.setattr(media, "_container", lambda: Container())
    monkeypatch.setattr(media, "_content_settings", lambda content_type: {"content_type": content_type})
    uploaded = media.upload_media(
        b"\x89PNG\r\n\x1a\n" + b"screen pixels",
        content_type="image/png",
        actor_id="admin",
        scope="insight",
    )
    assert uploaded["media_id"].startswith("insight-")
    assert uploaded["url"].startswith("/api/v1/insights/media/insight-")
    assert captured["media_id"] == uploaded["media_id"]
    assert captured["overwrite"] is False


def test_insight_attachment_limits_and_roundtrip(monkeypatch):
    from tbt.services import admin_storage as storage

    monkeypatch.setattr(storage, "info_alert_levels", lambda: ["pro", "elite", "legend", "goat"])
    base = {"title": "Test", "body": "Screenshot", "type": "vip", "levels": ["pro"]}
    clean = storage.normalize_insight({**base, "media_ids": [PRIVATE_ID]})
    assert clean["media_ids"] == [PRIVATE_ID]
    for invalid in ([PRIVATE_ID] * 2, [PRIVATE_ID] * 4, ["banner-public.png"], "not a list"):
        with pytest.raises(ValueError):
            storage.normalize_insight({**base, "media_ids": invalid})


def test_public_banner_route_never_serves_insight_images(monkeypatch):
    import function_app as api

    class Req:
        route_params = {"media_id": PRIVATE_ID}

    monkeypatch.setattr(api, "download_media", lambda _: pytest.fail("Private content leaked to public proxy"))
    result = api.public_media(Req())
    assert result.status_code == 404


def test_private_media_denied_if_not_attached_to_entitled_feed(monkeypatch):
    import function_app as api

    class Req:
        route_params = {"media_id": PRIVATE_ID}

    monkeypatch.setattr(api, "_admin_user", lambda request: (None, True))
    monkeypatch.setattr(api, "_verified_user", lambda request: {"id": "member-1", "email_verified": True})
    monkeypatch.setattr(api, "is_suspended", lambda user: False)
    monkeypatch.setattr(api, "_insight_plan_for_user", lambda user: "pro")
    monkeypatch.setattr(api, "list_insights", lambda **kwargs: {"items": [{"id": "msg-1", "media_ids": []}]})
    monkeypatch.setattr(api, "download_media", lambda _: pytest.fail("Unauthorized image read"))
    result = api.private_insight_media(Req())
    assert result.status_code == 403


def test_mobile_gallery_is_wired_before_application_and_stays_private():
    index = (ROOT / "web/index.html").read_text(encoding="utf-8")
    auth = (ROOT / "web/auth.js").read_text(encoding="utf-8")
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    module = (ROOT / "web/insight-media.js").read_text(encoding="utf-8")
    api = (ROOT / "api/function_app.py").read_text(encoding="utf-8")
    assert index.index("/insight-media.js") < index.index("/app.js")
    assert "adminUploadInsightMedia" in auth and "insightMedia" in auth
    assert "BlinqInsightMedia.upload(block" in app
    assert "BlinqInsightMedia.gallery(item.media_ids)" in app
    assert "capture=\"environment\"" in module
    assert "IntersectionObserver" in module
    assert 'scope="insight"' in api
    assert 'route="v1/insights/media/{media_id}"' in api
