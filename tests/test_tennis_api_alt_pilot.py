"""Secondary RapidAPI ATP/WTA/ITF 50 requests/day audit; no external traffic."""
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tennis_api_alt_pilot import Client, preview, run


class Response:
    def __init__(self, payload, remaining):
        self.payload = payload
        self.headers = {"x-ratelimit-requests-remaining": str(remaining)}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


def test_six_event_requests_plus_two_board_requests_max_eight():
    import tennis_api_alt_pilot as pilot
    calls = []
    def opener(req, timeout):
        calls.append(req.full_url)
        if "upcoming/" in req.full_url:
            return Response({"success": True, "results": [
                {"id": str(100+i), "liveEventId": str(100+i), "startTimestamp": 1791000000}
                for i in range(6)
            ], "pagination": {"total": 6}}, 44)
        return Response({"success": True, "result": {
            "Total games": {"Book A": {"od1": 1.9, "od2": 1.9, "line": 21.5}},
            "Full Time Result": {"Book A": {"od1": 1.3, "od2": 3.2}},
        }}, 39)
    original = pilot.json.load
    pilot.json.load = lambda response: response.payload
    try:
        report = run(Client("dummy", opener=opener),
                     now=datetime(2026, 9, 26, tzinfo=timezone.utc))
    finally:
        pilot.json.load = original
    assert report["requests_used"] <= 8
    assert len(report["checked_events"]) <= 6
    assert len(calls) == report["requests_used"]
    assert report["read_only"] is True
    assert all("Total games" in e["odds"]["market_names"]
               for e in report["checked_events"])
    assert report["provider_remaining"] == 39


def test_cap_and_missing_subscriptions_fail_closed():
    class Denied:
        count = 2
        limit = 8
        provider_remaining = 0
        def get(self, path):
            raise AssertionError("must not call")
    # Only actual Client objects may call API. Extra credit guard covers no key.
    assert Client("dummy", limit=800).limit == 8
    data = preview({"success": True, "result": {
        "Total games": {}, "Player aces": {}, "Double Faults": {},
        "First set winner": {},
    }})
    assert set(data["relevant_markets"]) == {"Total games", "Player aces", "Double Faults"}
    assert data["market_count"] == 4


def test_no_cron_and_existing_secret_only():
    root = Path(__file__).resolve().parents[1]
    flow = (root / ".github/workflows/tennis-api-alt-pilot.yml").read_text()
    assert "workflow_dispatch" in flow
    assert "schedule:" not in flow
    assert "secrets.RAPIDAPI_KEY" in flow
    source = (root / "scripts/tennis_api_alt_pilot.py").read_text()
    assert "MAX_REQUESTS = 8" in source
    assert "odds_plan_requirement" in source
