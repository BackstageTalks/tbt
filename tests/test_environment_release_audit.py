from __future__ import annotations

from datetime import datetime, timezone

import audit_environment_release as audit
from tbt.schemas import MatchRecord


def make_match(
    match_id: str,
    *,
    provider_id: str | None = None,
    env: dict | None = None,
    indoor: bool | None = False,
    tour: str = "atp",
    tournament: str = "Test Open",
) -> MatchRecord:
    payload = {}
    if provider_id is not None:
        payload["_tbt_provider_event_id"] = provider_id
    if env is not None:
        payload["_tbt_environment"] = env
    return MatchRecord(
        match_id=match_id,
        tour=tour,
        scheduled_at=datetime(2025, 1, 1, 12, tzinfo=timezone.utc),
        player1_id="1",
        player1_name="A",
        player2_id="2",
        player2_name="B",
        winner_id="1",
        tournament=tournament,
        indoor=indoor,
        provider_payload=payload,
    )


def usable_weather() -> dict:
    return {
        "temperature_c": 24.0,
        "relative_humidity_pct": 55.0,
        "wind_speed_kmh": 12.0,
        "precipitation_mm": 0.0,
    }


def test_indoor_resolved_without_weather_is_expected_not_missing():
    row = make_match(
        "indoor",
        indoor=True,
        env={"venue_resolved": True, "venue": {"name": "Arena"}},
    )
    report = audit._coverage([row])
    assert report["venue_resolved"] == 1
    assert report["indoor_resolved_no_weather_expected"] == 1
    assert report.get("outdoor_resolved_no_weather", 0) == 0
    assert report["coverage"]["usable_environment_or_expected_indoor"] == 1.0


def test_outdoor_usable_weather_counts_as_usable():
    row = make_match(
        "outdoor",
        indoor=False,
        env={"venue_resolved": True, "weather": usable_weather()},
    )
    report = audit._coverage([row])
    assert report["with_environment"] == 1
    assert report["venue_resolved"] == 1
    assert report["with_weather_object"] == 1
    assert report["usable_weather"] == 1
    assert report["coverage"]["usable_weather"] == 1.0


def test_canonicalize_duplicate_provider_event_prefers_enriched_row():
    plain = make_match("a", provider_id="event-7", env=None)
    enriched = make_match(
        "b",
        provider_id="event-7",
        env={"venue_resolved": True, "weather": usable_weather()},
    )
    canonical, duplicate_report = audit.canonicalize([plain, enriched])
    assert len(canonical) == 1
    assert canonical[0].match_id == "b"
    assert duplicate_report["duplicate_groups"] == 1
    assert duplicate_report["duplicate_rows_ignored"] == 1
