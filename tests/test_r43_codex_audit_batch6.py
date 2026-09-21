from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_b21_localization_handles_english_legacy_copy_and_dynamic_headers():
    app = text("web/app.js")
    assert "en: {" in app
    assert "'Telegram skupiny':'Telegram groups'" in app
    assert "'Viac o cookies':'More about cookies'" in app
    assert "'TOP a VALUE predikcie v jednom rýchlom dátovom boarde.':'TOP and VALUE predictions in one fast data board.'" in app
    assert "if(locale==='en'||!root)return" not in app
    assert "const time=lcopy('TIME','ČAS','ČAS')" in app
    assert "prediction=lcopy('PREDICTION','PREDIKCIA','PREDIKCE')" in app
    assert "const title=publicText(String(group.title" in app


def test_b23_ci_contains_real_browser_gate():
    workflow = text(".github/workflows/ci.yml")
    browser_test = text("tests/browser_runtime_r43.py")
    assert "Run real-browser runtime contract" in workflow
    assert "playwright==1.57.0" in workflow
    assert "python tests/browser_runtime_r43.py" in workflow
    assert "sync_playwright" in browser_test
    assert "for width in (390, 1440)" in browser_test
    assert 'for locale in ("sk", "cz", "en")' in browser_test
    assert "pageerror" in browser_test
    assert "scrollWidth" in browser_test


def test_b25_firebase_numeric_pages_reuse_cached_cursor(monkeypatch):
    from tbt.services import admin_accounts as mod

    mod._USER_PAGE_TOKEN_CACHE.clear()

    class Record:
        def __init__(self, uid):
            self.uid = uid

    class Page:
        def __init__(self, users, token):
            self.users = [Record(v) for v in users]
            self.next_page_token = token
        def get_next_page(self):
            raise AssertionError("cursor-capable path must not rescan with get_next_page")

    class Auth:
        def __init__(self):
            self.calls = []
        def list_users(self, *, max_results, app, page_token=None):
            self.calls.append(page_token)
            pages = {
                None: Page(["u1", "u2"], "p2"),
                "p2": Page(["u3", "u4"], "p3"),
                "p3": Page(["u5"], None),
            }
            return pages[page_token]

    auth = Auth()
    monkeypatch.setattr(mod, "_firebase_modules", lambda: (None, auth, None))
    monkeypatch.setattr(mod, "firebase_app", lambda cfg: object())
    monkeypatch.setattr(mod, "firebase_user_to_dict", lambda record: {"id": record.uid})

    assert [x["id"] for x in mod._firebase_list_users(object(), page=1, per_page=2)] == ["u1", "u2"]
    assert [x["id"] for x in mod._firebase_list_users(object(), page=2, per_page=2)] == ["u3", "u4"]
    assert [x["id"] for x in mod._firebase_list_users(object(), page=3, per_page=2)] == ["u5"]
    assert mod._firebase_list_users(object(), page=4, per_page=2) == []
    assert auth.calls == [None, "p2", "p3"]


def test_b25_account_metadata_many_uses_bounded_rowkey_queries(monkeypatch):
    from tbt.services import account_storage as mod

    users = ["u1", "u2", "u3"]
    entities = {
        mod._key(uid): {"PartitionKey": "account", "RowKey": mod._key(uid), "user_id": uid, "telegram_nick": f"@{uid}abc"}
        for uid in users
    }

    class AzureLikeClient:
        def __init__(self):
            self.filters = []
        def query_entities(self, query_filter=None):
            self.filters.append(query_filter)
            return [row for key, row in entities.items() if key in str(query_filter)]

    client = AzureLikeClient()
    monkeypatch.setattr(mod, "_table", lambda name: client)
    result = mod.load_account_metadata_many(users)
    assert set(result) == set(users)
    assert len(client.filters) == 1
    assert "RowKey eq" in client.filters[0]
    assert client.filters[0] != "PartitionKey eq 'account'"


def test_b25_insight_runtime_levels_loaded_once(monkeypatch):
    from tbt.services import admin_storage as mod

    rows = [
        {
            "PartitionKey": "insights", "RowKey": f"i{i}", "title": "x", "body": "y",
            "type": "insight", "priority": "normal", "levels_json": '["elite"]',
            "active": True, "pinned": False, "created_at": f"2026-01-01T00:00:{i:02d}+00:00",
        }
        for i in range(10)
    ]

    class Table:
        def query_entities(self, query_filter=None):
            return list(rows)

    counts = {"live": 0, "info": 0}
    monkeypatch.setattr(mod, "_table", lambda name: Table())
    monkeypatch.setattr(mod, "live_alert_levels", lambda config=None: counts.__setitem__("live", counts["live"] + 1) or ["elite", "legend", "goat"])
    monkeypatch.setattr(mod, "info_alert_levels", lambda config=None: counts.__setitem__("info", counts["info"] + 1) or ["rookie", "pro", "elite", "legend", "goat"])
    payload = mod.list_insights(plan="elite", include_inactive=False)
    assert len(payload["items"]) == 10
    assert counts == {"live": 1, "info": 1}


def test_b25_azure_clients_cached_and_live_provider_closed():
    storage = text("api/tbt/services/admin_storage.py")
    function_app = text("api/function_app.py")
    assert "_AZURE_TABLE_CACHE" in storage
    assert "Creating/checking" in storage
    assert "client.close()" in function_app


def test_b26_services_feature_builder_is_only_compatibility_shim():
    service_file = text("api/tbt/services/feature_builder.py")
    model_file = text("api/tbt/models/feature_builder.py")
    assert len(service_file.splitlines()) < 30
    assert len(model_file.splitlines()) > 2000
    assert "from ..models.feature_builder import *" in service_file
    from tbt.models.feature_builder import FeatureBuilder as ModelFeatureBuilder
    from tbt.services.feature_builder import FeatureBuilder as ServiceFeatureBuilder
    assert ServiceFeatureBuilder is ModelFeatureBuilder
