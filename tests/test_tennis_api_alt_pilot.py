"""Secondary RapidAPI ATP/WTA/ITF BASIC 50/day audit; no external traffic."""
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tennis_api_alt_pilot import Client, MAX_REQUESTS, _odds_summary, run


class Response:
    def __init__(self, payload, remaining):
        self.payload = payload
        self.headers = {"x-ratelimit-requests-remaining": str(remaining)}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


def test_matchodds_parses_game_total_contract_only():
    payload = {"odds": [
        {"id_b_o": 1, "total": 21.5, "ktb": 1.90, "ktm": 1.90},
        {"id_b_o": 2, "k1": 1.35, "k2": 3.10},
    ]}
    out = _odds_summary(payload)
    assert out["has_game_total"] is True
    assert out["game_total_samples"][0] == {
        "bookmaker_id": 1, "line_games": 21.5, "over": 1.9, "under": 1.9
    }


def test_two_boards_plus_six_match_odds_requests_hard_cap_eight():
    import tennis_api_alt_pilot as pilot
    calls = []
    board_payload = {
        "data": [
            {
                "matchId": i, "player1": {"id": 100+i, "name": f"A{i}"},
                "player2": {"id": 200+i, "name": f"B{i}"},
                "tournament": {"id": 300+i}, "roundId": 9,
                "startTime": f"2026-09-27T0{i}:00:00Z",
            } for i in range(1, 7)
        ]
    }
    def opener(req, timeout):
        calls.append(req.full_url)
        if "/upcoming/matches/" in req.full_url:
            return Response(board_payload, 50-len(calls))
        return Response({"odds": [
            {"id_b_o": 1, "total": 22.5, "ktb": 1.85, "ktm": 1.95}
        ]}, 50-len(calls))

    original = pilot.json.load
    pilot.json.load = lambda response: response.payload
    try:
        report = run(Client("dummy", opener=opener),
                     now=datetime(2026, 9, 26, tzinfo=timezone.utc))
    finally:
        pilot.json.load = original
    assert report["requests_used"] == len(calls) == 8
    assert report["requests_used"] <= MAX_REQUESTS == 8
    assert len(report["checked_matches"]) == 6
    assert report["game_total_matches_found"] == 6
    assert calls[0].startswith("https://tennis-api-atp-wta-itf.p.rapidapi.com/tennis/v2/upcoming/matches/atp?")
    assert calls[1].startswith("https://tennis-api-atp-wta-itf.p.rapidapi.com/tennis/v2/upcoming/matches/wta?")
    assert all("/upcoming/matchodds/" in url for url in calls[2:])


def test_provider_reserve_stops_without_burning_50_daily_quota():
    import tennis_api_alt_pilot as pilot
    calls = []
    def opener(req, timeout):
        calls.append(req.full_url)
        return Response({"data": []}, 5)
    original = pilot.json.load
    pilot.json.load = lambda response: response.payload
    try:
        report = run(Client("dummy", opener=opener),
                     now=datetime(2026, 9, 26, tzinfo=timezone.utc))
    finally:
        pilot.json.load = original
    assert report["status"] == "provider_daily_reserve"
    assert report["requests_used"] == 1


def test_workflow_is_manual_only_and_reuses_existing_rapidapi_secret():
    root = Path(__file__).resolve().parents[1]
    flow = (root / ".github/workflows/tennis-api-alt-pilot.yml").read_text()
    assert "workflow_dispatch:" in flow
    assert "schedule:" not in flow
    assert "secrets.RAPIDAPI_KEY" in flow
    source = (root / "scripts/tennis_api_alt_pilot.py").read_text()
    assert "MAX_REQUESTS = 8" in source
    assert "BASIC 50 requests/day" in source
