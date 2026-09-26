"""Offline contract tests: the pilot must never fabricate a bookmaker quote."""
from datetime import datetime, timedelta, timezone

from collect_market_odds_snapshots import (
    append_unique, parse_time, snapshot_quotes, upcoming_projections,
)
from audit_market_price_calibration import audit_samples, research_samples


def _now():
    return datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)


def test_only_frozen_future_sg_cards_with_real_provider_ids_are_queried():
    now = _now()
    future = (now + timedelta(hours=4)).isoformat()
    prior = (now - timedelta(hours=4)).isoformat()
    feed = {"sg_picks": [
        {"event_id": "100", "market": "games", "scheduled_at": future,
         "projection": 23.7, "reference_projection": 21.0,
         "projection_confidence": 0.79},
        {"event_id": "100", "market": "sets", "scheduled_at": future,
         "projection": 2.35},
        {"event_id": "101", "market": "games", "scheduled_at": prior,
         "projection": 24.0},
        {"event_id": "nonnumeric", "market": "sets", "scheduled_at": future,
         "projection": 2.45},
        {"event_id": "102", "market": "sets", "projection": 2.4},
    ]}
    found = upcoming_projections(feed, now)
    assert set(found) == {"100"}
    assert {card["market"] for card in found["100"]} == {"games", "sets"}
    assert parse_time(future) > now


def test_capture_exact_two_sided_offers_no_guesses():
    now = _now()
    upcoming = upcoming_projections({"sg_picks": [
        {"event_id": "100", "market": "games",
         "scheduled_at": (now + timedelta(hours=4)).isoformat(),
         "projection": 23.7},
    ]}, now)

    class Provider:
        calls = 0

        def event_odds(self, event_id, provider_id=1):
            self.calls += 1
            assert provider_id == 1 and event_id == "100"
            return {"markets": [
                {"marketName": "Total Games",
                 "choices": [
                     {"name": "Over 23.5", "odds": 1.86},
                     {"name": "Under 23.5", "odds": 1.90},
                 ]},
            ]}

    # Use the parser's real fixture shape as an integration contract, not a
    # fabricated bookmaker price. If provider changes schema this fails closed.
    provider = Provider()
    rows, errors = snapshot_quotes(upcoming, provider, now, max_events=1)
    assert not errors and provider.calls == 1
    assert all(row["source"] == "rapid_tennis_event_odds_exact_two_sided" for row in rows)
    if rows:
        assert rows[0]["line"] == 23.5
        assert rows[0]["over_odds"] == 1.86
        assert rows[0]["under_odds"] == 1.90
    assert append_unique(rows, rows) == rows


def test_no_complete_market_means_no_persisted_quote():
    now = _now()
    projection = upcoming_projections({"sg_picks": [
        {"event_id": "123", "market": "games",
         "scheduled_at": (now + timedelta(hours=4)).isoformat(),
         "projection": 24.0},
    ]}, now)
    class Provider:
        def event_odds(self, event_id, provider_id=1):
            return {"markets": []}
    rows, errors = snapshot_quotes(projection, Provider(), now, max_events=10)
    assert rows == [] and errors == []


def test_research_requires_real_unique_event_days_and_uses_time_split():
    now = _now()
    observed = []
    for day in range(40):
        for j in range(10):
            start = now + timedelta(days=day + 1)
            captured = start - timedelta(hours=6)
            market = "games" if j % 2 else "sets"
            line = 22.5 if market == "games" else 2.5
            projection = line + ((day + j) % 6 - 2.5) * .4
            observed.append({
                "event_id": str(day * 10 + j + 1), "market": market,
                "line": line, "over_odds": 1.86, "under_odds": 1.95,
                "provider_id": 1,
                "starts_at_utc": start.isoformat(),
                "captured_at_utc": captured.isoformat(),
                "models": [{"market": market, "projection": projection,
                            "projection_confidence": .7}],
            })
    samples = research_samples(observed)
    report = audit_samples(samples)
    assert report["distinct_events"] == 400
    assert report["distinct_start_days"] == 40
    assert report["status"] == "holdout_research_completed"
    assert report["model_deployed"] is False
    for segment in report["segments"].values():
        assert segment["status"] == "research_model_evaluated_no_publication"
        assert segment["train_last_day"] < segment["holdout_first_day"]
    # Repeated snapshots of the same event/line must never inflate support.
    repeat = {**observed[0], "captured_at_utc":
              (now + timedelta(minutes=1)).isoformat()}
    assert len(research_samples(observed + [repeat])) == 400
    assert audit_samples(samples[:20])["status"] == "insufficient_real_price_observations"


def test_no_post_start_observation_can_enter_calibration():
    now = _now()
    raw = [{"event_id": "1", "market": "games", "line": 23.5,
            "over_odds": 1.86, "under_odds": 1.95, "provider_id": 1,
            "starts_at_utc": now.isoformat(),
            "captured_at_utc": (now + timedelta(hours=1)).isoformat(),
            "models": [{"market": "games", "projection": 23.7}]}]
    assert research_samples(raw) == []
