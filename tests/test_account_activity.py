"""Account activity history is removable without discarding a pending Telegram task."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tbt.services import account_storage as accounts


class MemoryTable:
    def __init__(self):
        self.rows = {}

    def create_entity(self, entity):
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in self.rows:
            raise ValueError("Already exists")
        self.rows[key] = dict(entity)

    def upsert_entity(self, entity, mode=None):
        key = (entity["PartitionKey"], entity["RowKey"])
        old = self.rows.get(key, {}) if mode == "merge" else {}
        self.rows[key] = {**old, **entity}

    def get_entity(self, *, partition_key, row_key):
        return dict(self.rows[(partition_key, row_key)])

    def delete_entity(self, *, partition_key, row_key):
        del self.rows[(partition_key, row_key)]

    def query_entities(self, query_filter=None):
        if not query_filter:
            return [dict(row) for row in self.rows.values()]
        if "PartitionKey eq '" in query_filter:
            partition = query_filter.split("PartitionKey eq '", 1)[1].split("'", 1)[0]
            return [dict(row) for (pk, _), row in self.rows.items() if pk == partition]
        return []


@pytest.fixture
def store(monkeypatch):
    tables = {}
    monkeypatch.setattr(accounts, "_table", lambda name: tables.setdefault(name, MemoryTable()))
    return tables


def test_paid_downgrade_creates_durable_pending_telegram_task(store):
    accounts.record_account_event(
        actor_id="account-lifecycle-worker", target_id="u-paid",
        action="paid_membership_downgraded", outcome="success",
        before={"from_plan": "elite"},
        after={
            "from_plan": "elite", "to_plan": "rookie",
            "email": "user@example.test", "telegram_nick": "@tennis_user",
            "expired_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    activity = accounts.list_account_activity()
    assert activity["total"] == 1
    assert len(activity["tg_pending"]) == 1
    item = activity["tg_pending"][0]
    assert item["from_plan"] == "elite"
    assert item["telegram_nick"] == "@tennis_user"
    assert item["event_id"] == activity["items"][0]["id"]

    # Clearing the displayed event log never hides unfinished Telegram work.
    assert accounts.prune_account_activity(all_events=True)["deleted"] == 1
    cleared = accounts.list_account_activity()
    assert cleared["items"] == []
    assert cleared["tg_pending"][0]["event_id"] == item["event_id"]

    confirmed = accounts.confirm_telegram_cleanup(
        "u-paid", event_id=item["event_id"], actor_id="admin",
    )
    assert confirmed["event_id"] == item["event_id"]
    assert accounts.list_pending_telegram_cleanup() == []
    profile = accounts.load_account_metadata("u-paid")
    assert profile["tg_cleanup_confirmed_event"] == item["event_id"]
    assert profile["tg_private_member"] is False


def test_stale_confirmation_cannot_clear_newer_downgrade(store):
    args = dict(actor_id="worker", target_id="u1", action="paid_membership_downgraded", outcome="success")
    accounts.record_account_event(**args, after={"from_plan": "pro", "to_plan": "rookie"})
    first = accounts.list_pending_telegram_cleanup()[0]["event_id"]
    accounts.record_account_event(**args, after={"from_plan": "elite", "to_plan": "rookie"})
    second = accounts.list_pending_telegram_cleanup()[0]["event_id"]
    assert first != second
    with pytest.raises(ValueError, match="no longer current"):
        accounts.confirm_telegram_cleanup("u1", event_id=first, actor_id="admin")
    assert accounts.list_pending_telegram_cleanup()[0]["event_id"] == second


def test_retention_is_validated_and_purges_only_operational_events(store):
    accounts.record_access_audit(
        actor_id="admin", target_id="u1",
        before={"plan": "pro"}, after={"plan": "rookie"}, outcome="success",
    )
    accounts.record_account_event(
        actor_id="mailer", target_id="email:hashed",
        action="account_email_delivery", outcome="sent",
        after={"email": "user@example.test", "subject": "Paid renewal"},
    )
    assert accounts.save_account_activity_settings(30) == {"retention_days": 30}
    assert accounts.list_account_activity()["settings"]["retention_days"] == 30
    with pytest.raises(ValueError, match="Unsupported retention"):
        accounts.save_account_activity_settings(0)
    assert accounts.prune_account_activity(all_events=True)["deleted"] == 1
    assert len(store[accounts.AUDIT_TABLE].rows) == 1


def test_older_events_deleted_while_new_events_retained(store):
    accounts.save_account_activity_settings(7)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=10)).isoformat()
    current = now.isoformat()
    table = store.setdefault(accounts.ACTIVITY_TABLE, MemoryTable())
    table.create_entity({
        "PartitionKey": (now - timedelta(days=10)).strftime("%Y%m"),
        "RowKey": "old", "occurred_at": old,
    })
    table.create_entity({
        "PartitionKey": now.strftime("%Y%m"), "RowKey": "new", "occurred_at": current,
    })
    assert accounts.prune_account_activity()["deleted"] == 1
    assert len(table.rows) == 1
    assert next(iter(table.rows.values()))["RowKey"] == "new"


def test_admin_ui_contract():
    root = Path(__file__).resolve().parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    auth = (root / "web" / "auth.js").read_text(encoding="utf-8")
    api = (root / "api" / "function_app.py").read_text(encoding="utf-8")
    assert "renderAdminAccountActivity()" in app
    assert "Na odstránenie z Telegramu" in app
    assert "adminActivityRetention" in app
    assert "clear-activity" in app
    assert "admin-legacy-metrics" in app
    assert "adminConfirmTelegramCleanup" in auth
    assert 'route="v1/admin/account-activity/tg-confirm"' in api
