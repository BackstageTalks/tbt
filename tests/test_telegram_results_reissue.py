"""One-time Telegram results reissue must never create additional predictions."""
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import telegram_daily_results as results
import telegram_offer_publisher as tg
import telegram_results_reissue as reissue

DAY = "2026-10-31"
KEY = "results-reissue:2026-10-31:compact-four-lines-v1"


def record(event, channel, odds=1.8):
    return {
        "channel": channel,
        "event_id": event,
        "selection_id": "p1",
        "section": {"top": "top_daily", "value": "value", "aces": "ace"}[channel],
        "market": "aces" if channel == "aces" else "match_winner",
        "scheduled_at": "2026-10-31T13:00:00+00:00",
        "name": "Test " + event,
        "odds": odds,
        "publication_key": "aces-line" if channel == "aces" else "",
        "market_line": 5.5 if channel == "aces" else None,
        "projection_direction": "over" if channel == "aces" else "",
    }


def archive_row(row, won):
    return {
        **{k: row[k] for k in (
            "event_id", "selection_id", "section", "market", "publication_key",
            "market_line", "projection_direction",
        )},
        "odds": row["odds"],
        "price_status": "priced_projection",
        "result": {"correct": won, "void": False, "runtime_source": "match_status_snapshot"},
    }


def fixture(tmp_path, monkeypatch):
    rows = [record("Winner", "top"), record("Loser", "aces", 2.1)]
    archived = [archive_row(rows[0], True), archive_row(rows[1], False)]
    ledger = {"schema": 1, "attempts": {
        DAY + ":daily:0620": {"status": "sent", "message_ids": [702],
                              "rows": rows},
        "results:" + DAY: {"status": "sent", "message_ids": [713],
                          "counts": {"won": 1, "lost": 1, "void": 0, "pending": 0}},
    }}
    state = tmp_path / "ledger.json"
    tg.save(state, ledger)
    monkeypatch.setattr(results, "archive", lambda url, day: list(archived))
    monkeypatch.setattr(tg, "config", lambda url: {"footer": tg.FOOTER})
    args = SimpleNamespace(day=DAY, revision="compact-four-lines-v1",
                           api_url="unused", config_url="unused",
                           state=str(state), output=str(tmp_path / "out"))
    return args, ledger, archived


def test_verified_reissue_exact_four_line_summary_and_original_ledger(tmp_path, monkeypatch):
    args, original, _ = fixture(tmp_path, monkeypatch)
    reissue.prepare(args)
    outbound = tg.load(Path(args.output) / "messages.json")
    assert len(outbound) == 1
    assert outbound[0]["audience"] == "elite"
    text = outbound[0]["text"]
    assert ("✅ WIN 1 | ❌ LOSS 1\n"
            "🟪 VOID 0 | ⏳ PENDING 0\n"
            "🎯 Úspešnosť 50.0%\n"
            "💰 Zisk -0.20u | 📈 ROI -10.0%") in text
    assert "📊 Denný súhrn" not in text and "TOP · WIN" not in text
    assert tg.HEADER in text and "by BlinQ Stat Engine" in text
    assert "🅃 Winner | 1.80 | +0.80u ✅" in text
    assert "🄰 Loser | 2.10 | -1.00u ❌" in text
    state = tg.load(Path(args.output) / "state.json")
    assert state["attempts"] == original["attempts"]
    assert state["reposts"][KEY]["status"] == "reserved"
    assert state["reposts"][KEY]["source_message_ids"] == [713]
    assert (Path(args.output) / "ready").read_text() == KEY


def test_reissue_is_idempotent_even_after_reservation(tmp_path, monkeypatch, capsys):
    args, original, _ = fixture(tmp_path, monkeypatch)
    reissue.prepare(args)
    tg.save(args.state, tg.load(Path(args.output) / "state.json"))
    (Path(args.output) / "ready").unlink()
    def should_not_call(*_):
        raise AssertionError("Already reserved send must not call archive")
    monkeypatch.setattr(results, "archive", should_not_call)
    reissue.prepare(args)
    assert "already_reserved_or_sent" in capsys.readouterr().out
    assert not (Path(args.output) / "ready").exists()


def test_reissue_rejects_changed_or_unsettled_totals(tmp_path, monkeypatch):
    args, _, archived = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(results, "archive", lambda *_: archived[:1])
    with pytest.raises(RuntimeError, match="unresolved"):
        reissue.prepare(args)
    assert not (Path(args.output) / "ready").exists()

    monkeypatch.setattr(results, "archive", lambda *_: [
        archived[0], {**archived[1], "result": {
            "correct": True, "void": False, "runtime_source": "match_status_snapshot"
        }}
    ])
    with pytest.raises(RuntimeError, match="originally sent totals"):
        reissue.prepare(args)
    assert not (Path(args.output) / "ready").exists()
