from pathlib import Path
import json
import pytest

from tbt.services import admin_storage

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
APP = (ROOT / "web/app.js").read_text(encoding="utf-8")
AUTH = (ROOT / "web/auth.js").read_text(encoding="utf-8")
CSS = (ROOT / "web/blinq.css").read_text(encoding="utf-8")
BACKEND = (ROOT / "api/function_app.py").read_text(encoding="utf-8")
STORAGE = (ROOT / "api/tbt/services/admin_storage.py").read_text(encoding="utf-8")
UI = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))


def test_release_680_and_cache_are_consistent():
    assert UI["ui_revision"] == "6.8.0"
    assert UI["revision"] == "6.8.0"
    assert 'RELEASE = "6.8.0"' in BACKEND
    assert 'API_VERSION = "3.8.0"' in BACKEND
    for asset in ("blinq.css", "auth.js", "app.js"):
        assert f"/{asset}?v=680" in INDEX


def test_private_feed_bell_drawer_and_read_state_are_real_code_paths():
    assert 'id="insightBell"' in INDEX
    assert 'id="insightUnread"' in INDEX
    assert 'class="insight-bell-icon"' in INDEX
    assert 'id="insightDrawer"' in INDEX
    assert 'id="insightDrawerList"' in INDEX
    assert 'id="insightBackdrop"' in INDEX
    assert "function renderInsightBell()" in APP
    assert "function renderInsightDrawer()" in APP
    assert "function markInsightRead(id)" in APP
    assert "BlinqAuth.markInsightRead(id)" in APP
    assert "function insights()" in AUTH
    assert "function markInsightRead(insightId)" in AUTH
    assert 'route="v1/insights"' in BACKEND
    assert 'route="v1/insights/{insight_id}/read"' in BACKEND


def test_admin_has_chat_like_insights_editor_with_configurable_audience():
    assert "['insights','Komunita','BlinQ Insights · správy']" in APP
    assert "function renderAdminInsights()" in APP
    assert "Súkromný feed pre členov" in APP
    assert "Predvolené publikum je ELITE + LEGEND + GOAT" in APP
    assert "levels:['elite','legend','goat']" in APP
    assert 'name="insight_level"' in APP
    for level in ("rookie", "pro", "elite", "legend", "goat"):
        assert level in STORAGE
    for insight_type in ("info", "insight", "alert", "vip"):
        assert f"'{insight_type}'" in APP or f'"{insight_type}"' in STORAGE
    for priority in ("normal", "important", "critical"):
        assert priority in APP
    for field in ("adminInsightMatchId", "adminInsightLinkLabel", "adminInsightLink", "adminInsightFrom", "adminInsightUntil", "adminInsightActive", "adminInsightPinned"):
        assert field in APP
    assert "insight-edit" in APP and "insight-delete" in APP
    assert "read_count" in APP
    assert "const insightForm=$('adminInsightForm')" in APP
    assert "BlinqAuth.adminCreateInsight(payload)" in APP
    assert "BlinqAuth.adminUpdateInsight(state.adminInsightEditingId,payload)" in APP
    assert "BlinqAuth.adminDeleteInsight(id)" in APP


def test_admin_insight_crud_routes_and_client_connector_exist():
    assert 'route="v1/admin/insights"' in BACKEND
    assert 'route="v1/admin/insights/{insight_id}"' in BACKEND
    assert "save_insight(" in BACKEND
    assert "delete_insight(" in BACKEND
    for fn in ("adminInsights", "adminCreateInsight", "adminUpdateInsight", "adminDeleteInsight"):
        assert f"function {fn}" in AUTH


def test_daily_detail_uses_in_page_right_rail_not_match_modal():
    wire = APP.split("function wireDailyHub(){", 1)[1].split("function setRoute", 1)[0]
    assert "selectMatchInRail(current,state.dailyHubTab)" in wire
    assert "openMatch(current" not in wire
    assert 'id="dashboardRightRail"' in INDEX
    assert 'id="dashboardRightRailContent"' in INDEX
    assert "function renderMatchRail()" in APP
    assert "function clearMatchRail()" in APP
    assert "data-rail-close-match" in APP
    assert "renderDashboardRightRailDefault()" in APP


def test_match_rail_contains_requested_motivation_context_and_is_not_claimed_as_model_feature():
    assert "function motivationContext(row,side)" in APP
    assert "function renderMotivationPanel(row)" in APP
    assert "Motivation & readiness" in APP
    assert "renderMotivationPanel(row)" in APP
    assert "psychický stav neodhadujeme" in APP
    assert "qualification" in APP.lower()
    assert "Home factor" in APP
    assert "Event tier" in APP


def test_insight_match_deep_link_opens_same_right_rail():
    assert "data-insight-match" in APP
    assert "findRowByEventId(matchButton.dataset.insightMatch)" in APP
    assert "selectMatchInRail(found.row,found.tab)" in APP
    assert "setInsightDrawer(false)" in APP


def test_dashboard_width_and_right_rail_layout_are_present():
    assert ".app-shell{width:min(100%,1780px)!important" in CSS
    assert ".dashboard-content-grid{display:grid;grid-template-columns:minmax(0,1fr) 330px" in CSS
    assert ".dashboard-right-rail{min-width:0;position:sticky" in CSS
    assert ".rail-match-detail" in CSS
    assert ".rail-motivation" in CSS
    assert ".insight-drawer" in CSS
    assert ".admin-insights-grid" in CSS


class MemoryTable:
    def __init__(self):
        self.rows = {}

    def _key(self, partition_key, row_key):
        return (str(partition_key), str(row_key))

    def get_entity(self, partition_key, row_key):
        key = self._key(partition_key, row_key)
        if key not in self.rows:
            raise KeyError(row_key)
        return dict(self.rows[key])

    def upsert_entity(self, entity, mode=None):
        row = dict(entity)
        self.rows[self._key(row["PartitionKey"], row["RowKey"])] = row

    def create_entity(self, entity):
        row = dict(entity)
        key = self._key(row["PartitionKey"], row["RowKey"])
        if key in self.rows:
            class AlreadyExists(Exception):
                status_code = 409
            raise AlreadyExists()
        self.rows[key] = row

    def delete_entity(self, partition_key, row_key):
        key = self._key(partition_key, row_key)
        if key not in self.rows:
            raise KeyError(row_key)
        del self.rows[key]

    def query_entities(self, query_filter=None):
        values = list(self.rows.values())
        marker = "PartitionKey eq '"
        if query_filter and marker in query_filter:
            partition = query_filter.split(marker, 1)[1].split("'", 1)[0]
            values = [row for row in values if row.get("PartitionKey") == partition]
        return [dict(row) for row in values]


def test_insight_storage_defaults_to_elite_plus_and_allows_custom_levels(monkeypatch):
    tables = {}
    monkeypatch.setattr(admin_storage, "_table", lambda name: tables.setdefault(name, MemoryTable()))
    saved = admin_storage.save_insight({"title": "A", "body": "B"}, actor_id="admin")
    assert saved["levels"] == ["elite", "legend", "goat"]
    updated = admin_storage.save_insight({"levels": ["pro", "goat"], "title": "A2", "body": "B2"}, actor_id="admin", insight_id=saved["id"])
    assert updated["levels"] == ["pro", "goat"]
    assert admin_storage.list_insights(plan="elite")["items"] == []
    assert admin_storage.list_insights(plan="pro")["items"][0]["id"] == saved["id"]


def test_insight_storage_read_state_and_read_count_are_idempotent(monkeypatch):
    tables = {}
    monkeypatch.setattr(admin_storage, "_table", lambda name: tables.setdefault(name, MemoryTable()))
    saved = admin_storage.save_insight({"title": "Alert", "body": "Context", "levels": ["elite"]}, actor_id="admin")
    before = admin_storage.list_insights(plan="elite", user_id="user-1")
    assert before["unread"] == 1 and before["items"][0]["read"] is False
    first = admin_storage.mark_insight_read(insight_id=saved["id"], user_id="user-1")
    second = admin_storage.mark_insight_read(insight_id=saved["id"], user_id="user-1")
    assert first == {"read": True, "already_read": False}
    assert second == {"read": True, "already_read": True}
    after = admin_storage.list_insights(plan="elite", user_id="user-1")
    assert after["unread"] == 0 and after["items"][0]["read"] is True
    admin_list = admin_storage.list_insights(include_inactive=True)["items"]
    assert admin_list[0]["read_count"] == 1


def test_insight_storage_supports_match_link_schedule_pin_and_validation(monkeypatch):
    tables = {}
    monkeypatch.setattr(admin_storage, "_table", lambda name: tables.setdefault(name, MemoryTable()))
    saved = admin_storage.save_insight({
        "title": "Match update", "body": "New information", "type": "alert", "priority": "critical",
        "levels": ["elite", "legend"], "match_id": "14232981", "link_label": "Otvoriť zápas",
        "pinned": True, "active_from": "2026-09-14T10:00:00Z", "active_until": "2026-09-15T10:00:00Z",
    })
    assert saved["match_id"] == "14232981" and saved["pinned"] is True
    assert saved["priority"] == "critical" and saved["type"] == "alert"
    with pytest.raises(ValueError, match="Invalid insight match id"):
        admin_storage.save_insight({"title": "Bad", "body": "Bad", "match_id": "bad id with spaces"})
    with pytest.raises(ValueError, match="Select at least one"):
        admin_storage.save_insight({"title": "Bad", "body": "Bad", "levels": []})
    with pytest.raises(ValueError, match="Unknown insight"):
        admin_storage.save_insight({"title": "X", "body": "Y"}, insight_id="missing-id")
