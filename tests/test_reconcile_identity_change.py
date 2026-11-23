from datetime import datetime, timedelta, timezone
from tbt.services.engine import reconcile_ledger

NOW = datetime(2026, 11, 23, 4, 0, tzinfo=timezone.utc)


def _row(p2, issued=None):
    return {"event_id": "e1", "scheduled_at": (NOW + timedelta(hours=5)).isoformat(),
            "player1": {"id": "a"}, "player2": {"id": p2}, "issued_at": issued,
            "publication_status": "pending", "result": None}


def _find(records):
    rows = records if isinstance(records, list) else list(records)
    return next(r for r in rows if r["event_id"] == "e1")


def test_unissued_lineup_change_is_replaced_not_fatal():
    out = reconcile_ledger([_row("b")], [_row("c")], [], NOW)
    r = _find(out)
    assert r["player2"]["id"] == "c" and r.get("identity_replaced") is True


def test_issued_commitment_stays_frozen():
    out = reconcile_ledger([_row("b", issued=NOW.isoformat())], [_row("c")], [], NOW)
    r = _find(out)
    assert r["player2"]["id"] == "b" and r.get("identity_conflict_skipped") is True
