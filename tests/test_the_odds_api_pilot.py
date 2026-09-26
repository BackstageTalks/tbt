"""Mocked The Odds API free-plan monthly pilot regression checks."""
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from the_odds_api_pilot import collect, _markets


class FakeResponse:
    def __init__(self, payload, *, remaining, used, last):
        self.payload = payload
        self.headers = {
            "x-requests-remaining": str(remaining),
            "x-requests-used": str(used),
            "x-requests-last": str(last),
        }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_totals_market_is_research_only_and_preserves_exact_bookmaker_pair():
    listed, samples = _markets([{
        "id": "a", "home_team": "Novak Djokovic", "away_team": "Carlos Alcaraz",
        "bookmakers": [{"title": "Testbook", "markets": [
            {"key": "totals", "outcomes": [
                {"name": "Over", "point": 22.5, "price": 1.9},
                {"name": "Under", "point": 22.5, "price": 1.9},
                {"name": "Over", "point": 18.5, "price": 1.5},
            ]}
        ]}]
    }])
    assert listed == 1
    assert len(samples) == 1
    assert samples[0]["contract_verified"] is False
    assert samples[0]["line"] == 22.5


def test_free_sports_discovery_and_one_market_one_region_bounded_requests():
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        if "/sports/?" in req.full_url:
            return FakeResponse([
                {"key": "tennis_atp_a", "group": "Tennis", "active": True, "has_outrights": False},
                {"key": "tennis_wta_b", "group": "Tennis", "active": True, "has_outrights": False},
                {"key": "soccer_epl", "group": "Soccer", "active": True, "has_outrights": False},
            ], remaining=499, used=1, last=0)
        return FakeResponse([], remaining=498, used=2, last=1)

    # Inject network-free parser by replacing json.load for FakeResponse.
    import the_odds_api_pilot as pilot
    orig = pilot.json.load
    pilot.json.load = lambda r: r.payload
    try:
        report = collect(key="dummy", now=datetime(2026, 9, 26, 7, tzinfo=timezone.utc),
                         run_cap=3, opener=opener)
    finally:
        pilot.json.load = orig
    assert len(calls) == 3  # free /sports plus two active tennis tournaments
    assert report["requests_made"] == 2
    assert report["credits_spent"] == 2
    assert report["published_bets"] == 0
    assert all("regions=eu" in c and "markets=totals" in c for c in calls[1:])
    assert all("soccer" not in c for c in calls)


def test_monthly_budget_stop_and_absent_secret_make_no_spend():
    assert collect(key="")["requests_made"] == 0

    def opener(req, timeout):
        return FakeResponse([], remaining=90, used=410, last=0)

    import the_odds_api_pilot as pilot
    orig = pilot.json.load
    pilot.json.load = lambda r: r.payload
    try:
        report = collect(key="dummy", opener=opener)
    finally:
        pilot.json.load = orig
    assert report["status"] == "monthly_budget_stop"
    assert report["requests_made"] == 0


def test_free_plan_budget_31_day_month():
    assert 2 * 3 * 31 == 186
    assert 500 - 186 == 314
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/the-odds-api-pilot.yml").read_text(encoding="utf-8")
    assert "THE_ODDS_API_KEY: ${{ secrets.THE_ODDS_API_KEY }}" in workflow
    assert "25 6,18 * * *" in workflow
