import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("PROPL", "unit-test-key")
os.environ.setdefault("TBT_DATA_GH_TOKEN", "unit-test-token")
collector = importlib.import_module("propline_clv_collect")


def event(tier):
    return {
        "blinq_section": tier, "event_id": "123",
        "home_team": "A", "away_team": "B",
        "commence_time": "2026-11-02T15:00:00Z",
        "captured_at": "2026-11-02T12:00:00Z",
        "bookmakers": [
            {"key": "Book A", "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "A", "price": 2}, {"name": "B", "price": 1.5},
                ]},
                {"key": "player_aces", "outcomes": [{"name": "A", "price": 4}]},
            ]}
        ],
    }


def test_publishes_only_top_value_h2h_without_extra_provider_calls(monkeypatch):
    monkeypatch.setenv("BLINQ_LIVE_WORKER_TOKEN", "secret")
    monkeypatch.setenv("BLINQ_PUBLIC_BASE_URL", "https://blinq.example")
    posted = []
    def fake(url, headers, method, payload):
        import json
        posted.append((url, headers, method, json.loads(payload)))
        return {"ok": True, "accepted": 2, "verified": 2,
                "written": 2, "already_present": 0, "rejected_events": 0}

    monkeypatch.setattr(collector, "request_json", fake)
    result = collector.publish_detail_clv({
        "events": [event("top"), event("value"), event("prime")],
    })
    assert result["status"] == "verified"
    assert result["submitted_events"] == 2
    assert len(posted) == 1
    assert posted[0][0] == "https://blinq.example/api/v1/internal/clv-snapshot"
    assert posted[0][1]["X-Blinq-Worker-Token"] == "secret"
    assert len(posted[0][3]["events"]) == 2
    assert all(len(b["markets"]) == 1 and b["markets"][0]["key"] == "h2h"
               for e in posted[0][3]["events"] for b in e["bookmakers"])


def test_rejects_incomplete_persistent_readback(monkeypatch):
    monkeypatch.setenv("BLINQ_LIVE_WORKER_TOKEN", "secret")
    monkeypatch.setenv("BLINQ_PUBLIC_BASE_URL", "https://blinq.example")
    monkeypatch.setattr(collector, "request_json", lambda *a, **k:
                        {"ok": True, "accepted": 2, "verified": 1})
    with pytest.raises(RuntimeError, match="incomplete"):
        collector.publish_detail_clv({"events": [event("top")]})


def test_missing_worker_secret_is_not_claimed_published(monkeypatch):
    monkeypatch.delenv("BLINQ_LIVE_WORKER_TOKEN", raising=False)
    monkeypatch.setenv("BLINQ_PUBLIC_BASE_URL", "https://blinq.example")
    with pytest.raises(RuntimeError, match="not configured"):
        collector.publish_detail_clv({"events": [event("top")]})
