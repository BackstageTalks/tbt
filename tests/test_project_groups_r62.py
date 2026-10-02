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
