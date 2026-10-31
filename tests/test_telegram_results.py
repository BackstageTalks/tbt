"""Read-only previous betting day report and Telegram legacy-format contracts."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import importlib.util
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

from tbt.services.telegram_result_report import report_rows, previous_closed_day
from tbt.services.result_exclusions import result_bet_id

spec = importlib.util.spec_from_file_location("telegram_result_publisher", ROOT / "scripts/telegram_result_publisher.py")
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)


CLOSED_DAY = "2026-10-30"
NOW = datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc)  # 07:00 CET
START = datetime(2026, 10, 30, 12, 30, tzinfo=timezone.utc).isoformat()


def row(section="top_daily", *, event="31", market="match_winner", state="win", priced=True):
    outcome = {} if state == "pending" else {
        "correct": True if state == "win" else False if state == "loss" else None,
        "void": state == "void",
        "runtime_source": "match_status_snapshot",
    }
    if state in ("win", "loss") and priced:
        outcome.update(staked_units=1.0, profit_units=0.8 if state == "win" else -1.0)
    publication = {
        "section": section, "market": market, "selection_id": "p1",
        "issued_at": (datetime.fromisoformat(START) - timedelta(minutes=10)).isoformat(),
        "odds": 1.8 if priced else None,
        "price_status": "priced_projection" if market == "aces" and priced else "projection_only" if market == "aces" else "priced",
        "betting_day": CLOSED_DAY,
        "result": outcome,
    }
    data = {
        "event_id": event, "scheduled_at": START, "betting_day": CLOSED_DAY,
        "player1": {"id": "p1", "name": "Maria Novak"}, "player2": {"id": "p2", "name": "Ana Doe"},
        "market_publications": [publication],
    }
    return data


def report(rows, excluded=None):
    return report_rows({"results": rows}, [], excluded or set(), CLOSED_DAY)


def test_yesterday_closed_at_0600_and_dst_transition():
    assert previous_closed_day(NOW) == CLOSED_DAY
    assert tg.previous_day(NOW) == CLOSED_DAY
    assert tg.due({"enabled": True, "results_enabled": True, "results_time": "07:00"}, NOW) == "results:2026-10-30"
    assert tg.due({"enabled": True, "results_enabled": True, "results_time": "07:00"},
                  NOW + timedelta(hours=2)) is None
    with pytest.raises(ValueError):
        previous_closed_day(datetime(2026, 10, 31, 4, 59, tzinfo=timezone.utc))
    at_dst = datetime(2026, 10, 25, 6, 0, tzinfo=timezone.utc)
    assert tg.previous_day(at_dst) == "2026-10-24"


def test_exact_legacy_results_format_and_real_financials():
    rows = [row("top_daily", event="1"), row("value", event="2", state="loss"),
            row("ace", event="3", market="aces", priced=False)]
    output = report(rows)
    assert output["settled"] == 3
    messages = tg.messages(output, CLOSED_DAY)
    assert len(messages) == 3
    assert messages[0]["section"] == "top"
    assert "Data Betting by BackstageTalks" in messages[0]["text"]
    assert "📊 Results | TOP" in messages[0]["text"]
    assert "📅 30.10.26" in messages[0]["text"]
    assert "1️⃣ ✅ Novak | 13:30 | 1.80 | +0.80u" in messages[0]["text"]
    assert "ROI +80.0%" in messages[0]["text"]
    assert "1️⃣ ❌ Novak" in messages[1]["text"]
    assert "ROI -100.0%" in messages[1]["text"]
    assert "ROI —" in messages[2]["text"]
    assert "✅1" in messages[2]["text"]


def test_pending_count_only_for_known_issued_results():
    data = report([row(state="pending", event="missing1"), row(state="win", event="hit1")])
    assert data["pending_known"] == 1 and data["settled"] == 1
    msg = tg.messages(data, CLOSED_DAY)[0]["text"]
    assert "⏳1" in msg and "Pending" in msg
    assert "Potvrdené výsledky v archíve" in msg


def test_exclusions_and_value_precedence_respected():
    top = row("top_daily", event="unique42")
    value = row("value", event="unique42")
    value["market_publications"][0]["result"]["correct"] = False
    result = report([top, value])
    assert len(result["rows"]) == 1
    assert result["rows"][0]["section"] == "value"
    excluded = result_bet_id(top, top["market_publications"][0])
    assert report([top], {excluded})["rows"] == []


def test_report_does_not_shift_to_today_or_guess_results():
    stale = row("top_daily", event="99")
    stale["betting_day"] = "2026-10-29"
    assert report([stale])["rows"] == []
    data = report([row("ace", market="double_faults")])
    assert data["rows"] == []
    with pytest.raises(ValueError):
        tg.messages({"betting_day": CLOSED_DAY, "source": "unknown", "rows": []}, CLOSED_DAY)


def test_result_dispatch_disabled_by_default():
    assert tg.due({"enabled": True, "results_enabled": False, "results_time": "07:00"}, NOW) is None
    assert tg.due({"enabled": False, "results_enabled": True, "results_time": "07:00"}, NOW) is None


def test_reads_are_read_only_and_provenance_checked(monkeypatch):
    payload = report([row()])
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, _): return json.dumps(payload).encode()
    def fake_urlopen(req, timeout=0):
        assert req.get_header("X-blinq-worker-token") == "secret"
        assert "2026-10-30" in req.full_url
        return Response()
    monkeypatch.setattr(tg.urllib.request, "urlopen", fake_urlopen)
    assert tg.fetch("https://example.com/api/v1/internal/telegram-results",
                    "secret", CLOSED_DAY)["settled"] == 1
    with pytest.raises(RuntimeError):
        tg.fetch("https://example.com/api/v1/internal/telegram-results", "", CLOSED_DAY)
