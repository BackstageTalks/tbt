"""Protect member Results isolation and observe only opt-in gzip encoding costs."""
import gzip
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import function_app as api
from tbt.services import entitlements as access


def _non_november_row():
    return {
        "event_id": "historical-2026-11-10",
        "scheduled_at": "2026-11-10T11:00:00+00:00",
        "player1": {"id": "p1", "name": "Before", "model": {"confidence": 0.9}},
        "player2": {"id": "p2", "name": "Opponent"},
        "market_publications": [{
            "section": "top_daily", "market": "match_winner",
            "selection_id": "p1", "result": {"correct": True},
        }, {
            "section": "internal_private", "market": "internal_model",
            "selection_id": "private",
        }],
    }


@pytest.mark.parametrize("plan", ["rookie", "pro", "elite"])
def test_historical_issued_day_fast_path_only_reuses_fully_detached_rows(monkeypatch, plan):
    raw = _non_november_row()
    original = deepcopy(raw)
    # Mimic the real upstream authorization boundary: no private publications.
    authorized = access._filter_result_history([raw], None, allowed_categories={"top_daily"})
    assert len(authorized) == 1
    assert len(authorized[0]["market_publications"]) == 1
    assert authorized[0]["market_publications"][0]["section"] == "top_daily"
    baseline = access.filter_results_for_issued_day(
        authorized, {"plan": plan}
    )
    assert baseline == authorized and baseline[0] is not authorized[0]
    assert baseline[0]["player1"] is not authorized[0]["player1"]

    calls = []
    copied = access.deepcopy
    def count_copy(obj):
        calls.append(obj)
        return copied(obj)
    monkeypatch.setattr(access, "deepcopy", count_copy)
    reusable = access.filter_results_for_issued_day(
        authorized, {"plan": plan}, already_detached=True
    )
    assert reusable == baseline
    assert reusable is not authorized
    assert reusable[0] is authorized[0]
    assert calls == [], "No duplicate full historical Results clone"
    reusable[0]["player1"]["model"]["confidence"] = 0.1
    assert raw == original, "Detached response must not mutate serving authority"


def test_gzip_diagnostic_emits_server_timing_without_changing_payload_or_cache():
    payload = {"upcoming": [{"id": "match-1"}], "results": [], "account": {"plan": "elite"}}
    compressed = api._gzip_feed_response(payload)
    timing = compressed.headers["Server-Timing"]
    assert re.fullmatch(r"blinq_json;dur=\d+\.\d, blinq_gzip;dur=\d+\.\d", timing)
    assert compressed.headers["Cache-Control"] == "no-store"
    assert compressed.headers["Content-Encoding"] == "gzip"
    assert json.loads(gzip.decompress(compressed.get_body())) == payload


def test_backend_encode_detail_is_opt_in_and_does_not_touch_normal_json_response():
    root = Path(__file__).resolve().parents[1]
    src = (root / "api/function_app.py").read_text(encoding="utf-8")
    app = (root / "web/app.js").read_text(encoding="utf-8")
    expected = 'return response(data)'
    feed = src[src.index('@app.route(route="v1/feed", methods=["GET"])'):
               src.index('@app.route(route="v1/internal/clv-snapshot"')]
    assert expected in feed
    assert 'return _gzip_feed_response(data)' in feed
    assert 'if trace_started is not None:' in feed
    assert '"Server-Timing": (' in src
    assert "['blinq_json','blinq_gzip'].includes(item.name)" in app
    assert 'Server kódovanie: ' in app
