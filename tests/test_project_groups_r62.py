from datetime import datetime, timezone

from tbt.services import admin_storage


class MultiTable:
    def __init__(self):
        self.rows = {}

    def get_entity(self, partition_key, row_key):
        key = (partition_key, row_key)
        if key not in self.rows:
            raise KeyError(row_key)
        return dict(self.rows[key])

    def upsert_entity(self, entity, mode=None):
        self.rows[(entity["PartitionKey"], entity["RowKey"])] = dict(entity)

    def create_entity(self, entity):
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in self.rows:
            raise RuntimeError("already exists")
        self.rows[key] = dict(entity)

    def query_entities(self, query_filter=None):
        rows = list(self.rows.values())
        marker = "PartitionKey eq '"
        if query_filter and marker in query_filter:
            key = query_filter.split(marker, 1)[1].split("'", 1)[0]
            rows = [row for row in rows if row.get("PartitionKey") == key]
        return [dict(row) for row in rows]

    def delete_entity(self, partition_key, row_key):
        key = (partition_key, row_key)
        if key not in self.rows:
            raise KeyError(row_key)
        del self.rows[key]


def _all_levels():
    return ["rookie", "pro", "elite", "legend", "goat"]


def test_project_groups_are_dynamic_level_independent_and_keep_info_results(monkeypatch):
    table = MultiTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    monkeypatch.setattr(admin_storage, "info_alert_levels", _all_levels)
    monkeypatch.setattr(admin_storage, "live_alert_levels", _all_levels)

    alpha = admin_storage.save_project_group(
        {
            "name": "Alpha",
            "description": "Test project",
            "color": "blue",
            "capacity": 10,
            "total_cost_cents": 1000,
            "currency": "EUR",
            "self_join_enabled": True,
            "active": True,
        },
        actor_id="admin",
    )
    beta = admin_storage.save_project_group(
        {
            "name": "Beta",
            "description": "",
            "color": "orange",
            "capacity": 4,
            "total_cost_cents": 0,
            "currency": "EUR",
            "self_join_enabled": True,
            "active": True,
        },
        actor_id="admin",
    )
    assert alpha["id"] != beta["id"]
    assert alpha["contribution_cents"] == 100

    # Membership is intentionally independent from BlinQ membership level.
    admin_storage.join_project_group(alpha["id"], "rookie-user")
    admin_storage.join_project_group(alpha["id"], "elite-user")

    groups = admin_storage.list_project_groups(
        user_id="rookie-user", include_members=True
    )["items"]
    alpha_row = next(row for row in groups if row["id"] == alpha["id"])
    assert alpha_row["joined"] is True
    assert alpha_row["member_count"] == 2
    assert {row["user_id"] for row in alpha_row["members"]} == {
        "rookie-user",
        "elite-user",
    }

    message = admin_storage.save_insight(
        {
            "title": "Alpha tip",
            "body": "Projektová INFO správa",
            "type": "vip",
            "priority": "normal",
            "audience_mode": "groups",
            "group_ids": [alpha["id"]],
            "levels": _all_levels(),
            "active": True,
            "pinned": False,
            "active_from": "",
            "active_until": "",
        },
        actor_id="admin",
    )

    rookie_feed = admin_storage.list_insights(
        plan="rookie", user_id="rookie-user", include_inactive=False
    )
    elite_feed = admin_storage.list_insights(
        plan="elite", user_id="elite-user", include_inactive=False
    )
    outsider_feed = admin_storage.list_insights(
        plan="goat", user_id="outsider", include_inactive=False
    )
    assert [row["id"] for row in rookie_feed["items"]] == [message["id"]]
    assert [row["id"] for row in elite_feed["items"]] == [message["id"]]
    assert outsider_feed["items"] == []

    settled = admin_storage.save_info_result(
        message["id"], "win", actor_id="admin"
    )
    assert settled["outcome"] == "win"
    assert settled["audience_mode"] == "groups"
    assert settled["group_ids"] == [alpha["id"]]

    # Settlement history survives removal/expiry of the original INFO row.
    table.delete_entity("insights", message["id"])
    history = admin_storage.list_info_results()
    assert history[0]["title"] == "Alpha tip"
    assert history[0]["group_ids"] == [alpha["id"]]


def test_project_group_capacity_and_payment_state(monkeypatch):
    table = MultiTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)

    group = admin_storage.save_project_group(
        {
            "name": "Paid project",
            "color": "green",
            "capacity": 1,
            "total_cost_cents": 1000,
            "currency": "EUR",
            "self_join_enabled": True,
            "active": True,
        },
        actor_id="admin",
    )
    admin_storage.join_project_group(group["id"], "user-a")
    payment = admin_storage.set_project_member_payment(
        group["id"], "user-a", "paid"
    )
    assert payment["payment_status"] == "paid"

    try:
        admin_storage.join_project_group(group["id"], "user-b")
    except ValueError as exc:
        assert "full" in str(exc).lower()
    else:
        raise AssertionError("A full project group must reject another self-join")


def test_project_group_request_mode_requires_admin_approval(monkeypatch):
    table = MultiTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)

    group = admin_storage.save_project_group(
        {
            "name": "Request project",
            "color": "purple",
            "capacity": 3,
            "total_cost_cents": 300,
            "currency": "EUR",
            "entry_mode": "request",
            "join_deadline": "2999-01-01T12:00:00+00:00",
            "active": True,
        },
        actor_id="admin",
    )
    assert group["entry_mode"] == "request"
    assert group["can_request"] is True
    assert group["can_join"] is False

    pending = admin_storage.join_project_group(group["id"], "rookie-user")
    assert pending["joined"] is False
    assert pending["request_status"] == "requested"
    assert group["id"] not in admin_storage.project_group_ids_for_user("rookie-user")

    visible = admin_storage.list_project_groups(
        user_id="rookie-user", include_members=True
    )["items"][0]
    assert visible["request_status"] == "requested"
    assert visible["request_count"] == 1
    assert visible["requests"][0]["user_id"] == "rookie-user"

    approved = admin_storage.join_project_group(
        group["id"], "rookie-user", admin=True
    )
    assert approved["joined"] is True
    assert approved["request_status"] == ""
    assert group["id"] in admin_storage.project_group_ids_for_user("rookie-user")

    refreshed = admin_storage.list_project_groups(include_members=True)["items"][0]
    assert refreshed["request_count"] == 0
    assert refreshed["member_count"] == 1


def test_project_group_locked_full_and_deadline_states(monkeypatch):
    table = MultiTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)

    locked = admin_storage.save_project_group(
        {
            "name": "Locked",
            "color": "gray",
            "capacity": 5,
            "entry_mode": "locked",
            "active": True,
        },
        actor_id="admin",
    )
    assert locked["locked"] is True
    assert locked["lock_reason"] == "manual"
    try:
        admin_storage.join_project_group(locked["id"], "user-a")
    except ValueError as exc:
        assert "locked" in str(exc).lower()
    else:
        raise AssertionError("A manually locked group must reject self-entry")

    # Admin can still place a user into a manually locked group.
    joined = admin_storage.join_project_group(locked["id"], "user-a", admin=True)
    assert joined["joined"] is True

    full = admin_storage.save_project_group(
        {
            "name": "Full",
            "color": "green",
            "capacity": 1,
            "entry_mode": "open",
            "active": True,
        },
        actor_id="admin",
    )
    admin_storage.join_project_group(full["id"], "user-b")
    full_row = next(
        row for row in admin_storage.list_project_groups()["items"]
        if row["id"] == full["id"]
    )
    assert full_row["locked"] is True
    assert full_row["lock_reason"] == "full"
    assert full_row["effective_entry_mode"] == "locked"

    expired = admin_storage.save_project_group(
        {
            "name": "Expired join window",
            "color": "orange",
            "capacity": 10,
            "entry_mode": "open",
            "join_deadline": "2000-01-01T00:00:00+00:00",
            "active": True,
        },
        actor_id="admin",
    )
    assert expired["locked"] is True
    assert expired["lock_reason"] == "deadline"
    try:
        admin_storage.join_project_group(expired["id"], "user-c")
    except ValueError as exc:
        assert "deadline" in str(exc).lower()
    else:
        raise AssertionError("A project past its join deadline must reject self-entry")


def test_legacy_self_join_groups_map_to_open_mode(monkeypatch):
    table = MultiTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)

    group = admin_storage.save_project_group(
        {
            "name": "Legacy",
            "color": "blue",
            "capacity": 2,
            "self_join_enabled": True,
            "active": True,
        },
        actor_id="admin",
    )
    assert group["entry_mode"] == "open"
    assert group["can_join"] is True
