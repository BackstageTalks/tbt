import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import the_odds_clv_collect as collect_mod
from the_odds_clv_collect import collect
from the_odds_clv_report import _norm, evaluate


class FakeResponse:
    def __init__(self, payload, *, remaining=900, used=100, last=1):
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


def test_player_identity_normalization_handles_diacritics():
    assert _norm("Rebecca Šramková") == _norm("Rebecca Sramkova")
    assert _norm("Karolína Muchová") == _norm("Karolina Muchova")


def test_collector_uses_one_region_one_h2h_market_and_bounds_credits():
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        if "/sports/?" in req.full_url:
            return FakeResponse([
                {"key": "tennis_atp_beijing", "title": "ATP Beijing", "group": "Tennis", "active": True, "has_outrights": False},
                {"key": "tennis_wta_beijing", "title": "WTA Beijing", "group": "Tennis", "active": True, "has_outrights": False},
                {"key": "soccer_epl", "title": "EPL", "group": "Soccer", "active": True, "has_outrights": False},
            ], last=0)
        return FakeResponse([{
            "id": "evt-1",
            "commence_time": "2026-09-30T14:00:00Z",
            "home_team": "Player A",
            "away_team": "Player B",
            "bookmakers": [{
                "key": "book",
                "title": "Book",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Player A", "price": 1.80},
                        {"name": "Player B", "price": 2.05},
                    ],
                }],
            }],
        }], remaining=899, used=101, last=1)

    original = collect_mod.json.load
    collect_mod.json.load = lambda response: response.payload
    try:
        report = collect(
            key="dummy",
            available_credits=2,
            now=datetime(2026, 9, 30, 10, tzinfo=timezone.utc),
            max_sports=2,
            provider_reserve=100,
            priority_terms=["beijing"],
            opener=opener,
        )
    finally:
        collect_mod.json.load = original

    assert len(calls) == 3
    assert report["credits_spent"] == 2
    assert len(report["events"]) == 2
    assert all("regions=eu" in url and "markets=h2h" in url for url in calls[1:])
    assert all("soccer" not in url for url in calls)


def _snapshot(captured, price_a, price_b):
    return {
        "captured_at": captured.isoformat(),
        "events": [{
            "event_id": "odds-event",
            "sport_key": "tennis_atp_test",
            "commence_time": datetime(2026, 9, 30, 14, tzinfo=timezone.utc).isoformat(),
            "home_team": "Player A",
            "away_team": "Player B",
            "bookmakers": [{
                "key": "book",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Player A", "price": price_a},
                        {"name": "Player B", "price": price_b},
                    ],
                }],
            }],
        }],
    }


def test_report_links_only_pre_issue_snapshot_and_near_close_proxy():
    kickoff = datetime(2026, 9, 30, 14, tzinfo=timezone.utc)
    snapshots = [
        _snapshot(kickoff - timedelta(hours=3), 2.00, 1.80),
        _snapshot(kickoff - timedelta(minutes=70), 1.90, 1.90),
        _snapshot(kickoff - timedelta(minutes=30), 1.80, 2.00),
    ]
    ledger = [{
        "event_id": "blinq-event",
        "scheduled_at": kickoff.isoformat(),
        "issued_at": (kickoff - timedelta(minutes=60)).isoformat(),
        "winner_id": "a",
        "player1": {"id": "a", "name": "Player A"},
        "player2": {"id": "b", "name": "Player B"},
    }]
    report = evaluate(snapshots, ledger)
    assert report["blinq_comparable_bookmaker_series"] == 1
    row = report["blinq_examples"][0]
    assert row["issue_decimal"] == 1.9
    assert row["close_proxy_decimal"] == 1.8
    assert row["price_clv_pct"] > 0
    assert datetime.fromisoformat(row["issue_sample_time"]) < datetime.fromisoformat(row["issued_at"])


def test_workflow_is_hourly_bounded_and_publication_triggered():
    workflow = (ROOT / ".github/workflows/the-odds-clv.yml").read_text(encoding="utf-8")
    data = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")
    status = (ROOT / ".github/workflows/match-status.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "  push:" in workflow
    assert '"scripts/the_odds_clv_collect.py"' in workflow
    assert "  schedule:" not in workflow
    assert 'CLV_DAILY_CREDIT_CAP: "300"' in workflow
    assert 'CLV_MAX_SPORTS_PER_RUN: "8"' in workflow
    assert 'CLV_PROVIDER_RESERVE: "100"' in workflow
    assert "THE_ODDS_API_KEY" in workflow
    assert "GH_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}" in workflow
    assert "the-odds-clv.yml" in data
    assert "reason=publication" in data
    assert "the-odds-clv.yml" in status
    assert "reason=hourly" in status
    assert "propline-clv-pilot.yml" in status


def test_report_accepts_first_post_issue_snapshot_within_15_minutes():
    kickoff = datetime(2026, 9, 30, 14, tzinfo=timezone.utc)
    snapshots = [
        _snapshot(kickoff - timedelta(minutes=55), 1.95, 1.85),
        _snapshot(kickoff - timedelta(minutes=30), 1.80, 2.00),
    ]
    ledger = [{
        "event_id": "blinq-event",
        "scheduled_at": kickoff.isoformat(),
        "issued_at": (kickoff - timedelta(minutes=60)).isoformat(),
        "winner_id": "a",
        "player1": {"id": "a", "name": "Player A"},
        "player2": {"id": "b", "name": "Player B"},
    }]
    report = evaluate(snapshots, ledger)
    assert report["blinq_comparable_bookmaker_series"] == 1
    row = report["blinq_examples"][0]
    assert row["issue_sample_relation"] == "post_issue_proxy"
    assert row["issue_sample_time"] == (kickoff - timedelta(minutes=55)).isoformat()
    assert row["price_clv_pct"] > 0
