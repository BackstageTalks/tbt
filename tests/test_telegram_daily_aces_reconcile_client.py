"""Daily Telegram ACES client must settle additional issued refresh contracts.

The existing Results writer remains authoritative; these tests ensure frozen
receipts are filtered without modifying the private delivery ledger.
"""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import telegram_daily_aces_reconcile as client


DAY = "2026-11-10"


def ace(event, selection, *, odds=1.70):
    return {
        "channel": "aces", "section": "ace", "market": "aces",
        "event_id": event, "selection_id": selection,
        "publication_key": f"local-aces-ou-v1:{event}:{selection}:over:4.5",
        "market_line": 4.5, "projection_direction": "over",
        "scheduled_at": "2026-11-10T16:00:00+00:00",
        "price_basis": "local_aces_statistical_v1",
        "projection": 5.6, "odds": odds,
    }


def ledger():
    first = ace("old", "player1")
    new = ace("new", "player2")
    original = {
        "status": "sent", "sent_at": "2026-11-10T05:20:00+00:00",
        "message_ids": [100, 101], "rows": [first],
    }
    refresh = {
        "status": "sent", "sent_at": "2026-11-10T10:39:00+00:00",
        "message_ids": [102, 103], "rows": [dict(first), new],
    }
    return {"attempts": {DAY + ":daily:0620": original,
                          DAY + ":daily:refresh-atp-wta-v1": refresh},
            "reposts": {}}


@pytest.fixture(autouse=True)
def target_day(monkeypatch):
    monkeypatch.setattr(client.results, "unreported_day",
                        lambda state, now: DAY)


def test_refreshed_new_aces_settled_once_without_rewriting_original():
    state = ledger()
    before = deepcopy(state)
    calls = []

    def sender(base, day, receipt, mode, digest=""):
        keys = [row["event_id"] for row in receipt["rows"]]
        calls.append((mode, keys, receipt["message_ids"], digest))
        if mode == "commit":
            assert keys == ["new"] and digest == "digest-new"
            return {"digest": digest, "readback_new_aces": 1}
        if keys == ["old"]:
            return {"already_verified": 1, "pending_evidence": 0,
                    "net_new_aces": 0, "digest": "digest-old"}
        assert keys == ["new"]
        return {"already_verified": 0, "pending_evidence": 0,
                "net_new_aces": 1, "digest": "digest-new"}

    actual = client.reconcile(state, "https://unused.test", sender=sender)
    assert actual == {"status": "verified", "day": DAY,
                      "already_verified": 1, "pending_evidence": 0,
                      "net_new_aces": 1}
    assert calls == [
        ("dry-run", ["old"], [100, 101], ""),
        ("dry-run", ["new"], [102, 103], ""),
        ("commit", ["new"], [102, 103], "digest-new"),
    ]
    assert state == before


def test_identical_refresh_rows_do_not_reopen_original_contract():
    state = ledger()
    state["attempts"][DAY + ":daily:refresh-atp-wta-v1"]["rows"] = [
        deepcopy(state["attempts"][DAY + ":daily:0620"]["rows"][0])]
    calls = []

    def sender(base, day, receipt, mode, digest=""):
        calls.append(mode)
        assert mode == "dry-run"
        return {"already_verified": 1, "pending_evidence": 0,
                "net_new_aces": 0}

    actual = client.reconcile(state, "https://unused.test", sender=sender)
    assert actual["status"] == "read_only"
    assert actual["net_new_aces"] == 0
    assert calls == ["dry-run"]


def test_changed_original_market_under_same_key_blocks_all_writes():
    state = ledger()
    state["attempts"][DAY + ":daily:refresh-atp-wta-v1"]["rows"][0]["odds"] = 1.75

    def forbidden(*args):
        raise AssertionError("Sender must not be reached")

    with pytest.raises(RuntimeError, match="Conflicting duplicate"):
        client.reconcile(state, "https://unused.test", sender=forbidden)


def test_changed_native_digest_or_readback_fails_closed():
    state = ledger()

    def sender(base, day, receipt, mode, digest=""):
        keys = [row["event_id"] for row in receipt["rows"]]
        if mode == "commit":
            return {"digest": "changed", "readback_new_aces": 1}
        return {"already_verified": int(keys == ["old"]),
                "pending_evidence": 0, "net_new_aces": int(keys == ["new"]),
                "digest": "frozen"}

    with pytest.raises(RuntimeError, match="read-back mismatch"):
        client.reconcile(state, "https://unused.test", sender=sender)


def test_unreported_or_not_issued_does_not_call_native_writer(monkeypatch):
    state = ledger()
    monkeypatch.setattr(client.results, "unreported_day",
                        lambda state, now: None)

    def forbidden(*args):
        raise AssertionError("Sender must not be reached")

    assert client.reconcile(state, "https://unused.test", sender=forbidden) == {
        "status": "skipped", "reason": "no_unreported_issued_day"}
