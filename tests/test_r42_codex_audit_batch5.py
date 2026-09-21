import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _text(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_r42_release_identity():
    release = json.loads(_text("web/release.json"))
    ui = json.loads(_text("web/ui-config.json"))
    assert release["patch"] == ui["ui_patch"] == "736-r49"
    assert 'content="736-r49"' in _text("web/index.html")
    assert "const AUTH_RUNTIME = '736-r49'" in _text("web/auth.js")


def test_b27_push_endpoint_is_allowlisted(monkeypatch):
    from tbt.services import push_notifications as push

    base = {"keys": {"p256dh": "p" * 64, "auth": "a" * 22}}
    assert push._clean_subscription({**base, "endpoint": "https://fcm.googleapis.com/fcm/send/abc"})["endpoint"]
    assert push._clean_subscription({**base, "endpoint": "https://wns2-db5p.notify.windows.com/w/?token=abc"})["endpoint"]
    with pytest.raises(ValueError, match="Unsupported push endpoint host"):
        push._clean_subscription({**base, "endpoint": "https://attacker.example/push"})
    monkeypatch.setenv("BLINQ_WEBPUSH_ALLOWED_HOSTS", "*.push.example.test")
    assert push._clean_subscription({**base, "endpoint": "https://edge.push.example.test/push"})["endpoint"]


def test_b15_sync_revocation_deletes_cached_subscriptions(monkeypatch):
    from tbt.services import push_notifications as push

    rows = [{"PartitionKey": "push", "RowKey": "r1", "user_id": "u1", "plan": "goat", "status": "active", "endpoint": "x"}]
    deleted = []

    class Table:
        def query_entities(self, query_filter=None):
            return list(rows)
        def delete_entity(self, *, partition_key, row_key):
            deleted.append((partition_key, row_key))
        def upsert_entity(self, row, mode=None):
            raise AssertionError("revoked access must not be rewritten as entitled")

    monkeypatch.setattr(push, "_table", lambda name: Table())
    push.sync_push_access(user_id="u1", plan="goat", status="expired", expires_at=None)
    assert deleted == [("push", "r1")]


def test_b15_dispatch_uses_live_identity_not_cached_plan(monkeypatch):
    from tbt.services import push_notifications as push

    row = {
        "PartitionKey": "push", "RowKey": "r1", "user_id": "u1",
        "plan": "goat", "status": "lifetime", "expires_at": "",
        "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
        "keys_json": json.dumps({"p256dh": "p" * 64, "auth": "a" * 22}),
    }
    class Table:
        def query_entities(self, query_filter=None): return [row]
        def delete_entity(self, **kwargs): pass
    monkeypatch.setattr(push, "_table", lambda name: Table())
    monkeypatch.setattr(push, "webpush_config", lambda: {"enabled": True, "public_key": "x", "subject_configured": True, "keys_configured": True})
    monkeypatch.setattr(push, "_current_push_access", lambda uid: ({"plan": "rookie", "status": "active", "expires_at": None}, False))

    # Avoid requiring pywebpush in the test environment.
    import sys, types
    calls=[]
    fake=types.SimpleNamespace(webpush=lambda **kwargs: calls.append(kwargs), WebPushException=type("WebPushException", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "pywebpush", fake)
    result=push.dispatch_insight_push({"active": True, "levels": ["elite", "legend", "goat"], "title": "LIVE", "body": "x"})
    assert result["sent"] == 0
    assert calls == []


def test_b22_firestore_missing_config_is_normal(monkeypatch):
    from tbt.services import admin_storage as storage

    class Table:
        def get_entity(self, **kwargs): raise KeyError("ui-config")
    monkeypatch.setattr(storage, "_table", lambda name: Table())
    assert storage.load_runtime_ui_config() is None


def test_b22_backend_policy_never_silently_cross_fails_over(monkeypatch):
    from tbt.services import admin_storage as storage

    monkeypatch.setenv("BLINQ_STORAGE_CONNECTION_STRING", "configured")
    monkeypatch.delenv("BLINQ_ADMIN_STORAGE_BACKEND", raising=False)
    monkeypatch.setattr(storage, "_azure_table", lambda name: (_ for _ in ()).throw(storage.AdminStorageUnavailable("down")))
    monkeypatch.setattr(storage, "_FirestoreTableAdapter", lambda name: (_ for _ in ()).throw(AssertionError("must not silently switch backend")))
    with pytest.raises(storage.AdminStorageUnavailable):
        storage._table("X")


def test_b17_effective_access_config_fills_legacy_missing_fields(monkeypatch):
    from tbt.services import admin_storage as storage

    legacy = {
        "schema": 2,
        "ui_patch": "736-r31",
        "access_contract_revision": 1,
        "dashboard": {"daily_hub": {"tabs": {"prime": {"enabled": False, "plans": {"rookie": {"selection_mode": "first"}}}}}},
    }
    effective = storage.resolve_ui_access_config(legacy)
    assert effective["dashboard"]["results_history_window"]["legend"] == "all"
    assert effective["dashboard"]["daily_hub"]["tabs"]["prime"]["enabled"] is False
    assert effective["dashboard"]["daily_hub"]["tabs"]["prime"]["plans"]["rookie"]["selection_mode"] == "stable_random"
    assert effective["elements"]["SIDEBAR_RESULTS"]["access"]["rookie"] == "locked"


def test_public_ui_config_returns_effective_contract():
    source = _text("api/function_app.py")
    assert '"runtime_configured": runtime_configured' in source
    assert '"source": "runtime" if runtime_configured else "release_access_defaults"' in source
    assert "load_effective_ui_config()" in source


def test_account_delete_attempts_push_cleanup():
    source = _text("api/function_app.py")
    delete_block = source[source.index('route="v1/admin/users/{user_id}"'):source.index('route="v1/admin/users/{user_id}/metadata"')]
    assert "delete_user_account(settings, user_id)" in delete_block
    assert "delete_subscription(user_id=user_id)" in delete_block
