"""Immutable receipt / one-shot guard for the operator-approved tour clarification."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import telegram_20261110_tour_correction as correction
import telegram_offer_publisher as tg


def _state():
    originals = []
    for n in range(8):
        originals.append({
            "channel": "aces", "market": "aces", "event_id": str(n),
            "selection_id": "player" + str(n), "scheduled_at": "2026-11-10T15:00:00+00:00",
            "name": "Player " + str(n),
        })
    return {"schema": 1, "attempts": {
        correction.DAILY: {"status": "sent", "message_ids": correction.DAILY_IDS,
                           "sha256": correction.DAILY_HASH, "rows": [
                               {"channel": "top", "event_id": "other"},
                               *originals]},
        correction.MORE: {"status": "sent", "message_ids": correction.MORE_IDS,
                          "sha256": correction.MORE_HASH, "rows": [
                              {"event_id": r["event_id"],
                               "selection_id": r["selection_id"]} for r in originals]}
    }, "reposts": {}}


def _snapshot():
    rows = []
    for n in range(8):
        tour = "ATP" if n % 2 == 0 else "WTA"
        tournament = "Main Tour" if n < 4 else "WTA 125" if n % 2 else "ATP Challenger"
        rows.append({
            "market": "aces", "event_id": str(n), "selection_id": "player" + str(n),
            "scheduled_at": "2026-11-10T15:00:00+00:00",
            "tour": tour, "tournament": tournament,
            "_receipt": _state()["attempts"][correction.DAILY]["rows"][n + 1],
        })
    return {
        "confirmed_only": True, "betting_day": correction.DAY,
        "generated_at": "2026-11-10T05:25:00+00:00",
        "source_feed_generated_at": "2026-11-10T05:01:00+00:00",
        "ace_picks": rows,
    }


def test_one_time_tour_correction_is_exact_non_mutating_and_no_bet_issuance(tmp_path, monkeypatch):
    original = _state()
    path = tmp_path / "ledger.json"
    tg.save(path, original)
    monkeypatch.setattr(correction.tg, "snapshot", lambda *_: _snapshot())
    monkeypatch.setattr(correction.tg, "result_reference", lambda row, _: row["_receipt"])
    monkeypatch.setattr(correction.more, "site_readback", lambda *_: {
        "ok": True, "ready": True, "stale": False, "betting_day": correction.DAY,
        "generated_at": "2026-11-10T05:01:00+00:00",
        "offer_authority_keys": {"aces": ["approved0", "approved1", "approved2", "approved3"]},
    })
    monkeypatch.setattr(correction, "row_authority_key", lambda row, _: "approved" + row["event_id"])
    output = tmp_path / "out"
    args = type("Args", (), dict(
        state=str(path), output=str(output), api_url="https://example.org",
        now="2026-11-10T10:00:00+00:00"))
    correction.prepare(args)
    assert (output / "ready").read_text() == correction.CORRECTION
    entry = tg.load(output / "state.json")["reposts"][correction.CORRECTION]
    assert entry["counts"] == {"original": 8, "eligible_main_tour": 4, "off_tour": 4}
    assert entry["paid_provider_requests"] == 0 and entry["cdb_writes"] == 0
    message = tg.load(output / "messages.json")
    assert len(message) == 1 and message[0]["audience"] == "elite"
    assert "korekcia" in message[0]["text"].lower() or "OPRAVA" in message[0]["text"]
    assert "Player 0" in message[0]["text"] and "Player 1" in message[0]["text"]
    assert "Player 4" not in message[0]["text"]
    assert tg.load(path) == original
    tg.save(path, tg.load(output / "state.json"))
    (output / "ready").unlink()
    correction.prepare(args)
    assert not (output / "ready").exists()


def test_receipt_changes_and_unverified_website_fail_closed(tmp_path, monkeypatch):
    original = _state()
    broken = deepcopy(original)
    broken["attempts"][correction.DAILY]["sha256"] = "tampered"
    with pytest.raises(RuntimeError, match="receipt"):
        correction.confirmed_originals(broken)
    monkeypatch.setattr(correction, "row_authority_key",
                        lambda row, _: "approved" + row["event_id"])
    matching = [(row, source) for row, source in zip(
        original["attempts"][correction.DAILY]["rows"][1:], _snapshot()["ace_picks"])]
    with pytest.raises(RuntimeError, match="Live website"):
        correction.verified_production(_snapshot(), {"ok": False}, matching)
    with pytest.raises(RuntimeError, match="not an issued website row"):
        correction.verified_production(_snapshot(), {
            "ok": True, "ready": True, "stale": False,
            "betting_day": correction.DAY,
            "generated_at": _snapshot()["source_feed_generated_at"],
            "offer_authority_keys": {"aces": []},
        }, matching)


def test_correction_workflow_never_calls_provider_or_writes_cdb():
    code = (Path(__file__).resolve().parents[1] /
            ".github/workflows/telegram-20261110-tour-correction.yml").read_text()
    assert "group: blinq-telegram-ledger" in code
    assert "telegram-20261110-tour-correction-request.json" in code
    assert "git diff-tree" in code
    assert "paid_provider_requests == 0" in code
    assert "cdb_writes == false" in code
    assert "scripts/telegram_offer_publisher.py mark-sent" in code
    assert "test \"$expected\" = \"$actual\"" in code
