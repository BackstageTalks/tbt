import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from propline_clv_report import evaluate


def _snapshot(captured, price, *, priority=True):
    return {
        "api_calls": 1,
        "events": [{
            "event_id": "evt",
            "commence_time": "2026-09-30T14:00:00+00:00",
            "captured_at": captured,
            "blinq_priority": priority,
            "bookmakers": [{
                "key": "book",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [{
                        "name": "Player A",
                        "description": "",
                        "point": None,
                        "price": price,
                    }],
                }],
            }],
        }],
    }


def test_report_separates_blinq_priority_movement():
    snapshots = [
        _snapshot("2026-09-30T10:00:00+00:00", 2.00),
        _snapshot("2026-09-30T13:00:00+00:00", 1.80),
    ]
    report = evaluate(snapshots)
    assert report["blinq_priority_events"] == 1
    assert report["comparable_series"] == 1
    assert report["blinq_comparable_series"] == 1
    assert report["blinq_by_market"]["h2h"]["comparable_selections"] == 1
    assert report["blinq_examples"][0]["blinq_priority"] is True
    assert report["blinq_examples"][0]["observed_clv_percent"] > 0
