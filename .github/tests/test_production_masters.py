from __future__ import annotations

from datetime import datetime, timezone

import build_tournament_venue_master as master
from tbt.schemas import MatchRecord


def match(mid: str, *, tournament_id="55", country="ESP", city="Madrid", env=True):
    payload = {
        "tournament": {"id": tournament_id, "name": "Madrid", "city": city, "country": {"alpha3": country}},
        "venue": {"id": "venue-7", "name": "Caja Magica", "city": city, "country": {"alpha3": country}},
    }
    if env:
        payload["_tbt_environment"] = {
            "venue_resolved": True,
            "venue": {
                "name": "Madrid",
                "latitude": 40.4168,
                "longitude": -3.7038,
                "elevation_m": 667.0,
                "timezone": "Europe/Madrid",
                "country": "ES",
            },
        }
    return MatchRecord(
        match_id=mid,
        tour="atp",
        scheduled_at=datetime(2025, 5, 1, 12, tzinfo=timezone.utc),
        player1_id="1", player1_name="A", player2_id="2", player2_name="B",
        winner_id="1", tournament="Madrid", tournament_id=tournament_id,
        tournament_level="ATP 1000", surface="clay", indoor=False,
        provider_payload=payload,
    )


def test_tournament_and_venue_master_normalize_country_and_resolved_geometry():
    tournaments, venues, report = master.build([match("m1"), match("m2")])
    assert len(tournaments) == 1
    assert len(venues) == 1
    t = tournaments[0]
    v = venues[0]
    assert t["country_code"] == "ES"
    assert t["surface"] == "clay"
    assert t["indoor"] is False
    assert t["venue_resolved_rate"] == 1.0
    assert v["country_code"] == "ES"
    assert v["latitude"] == 40.4168
    assert v["elevation_m"] == 667.0
    assert v["timezone"] == "Europe/Madrid"
    assert report["tournament_coverage"]["country"] == 1.0
    assert report["venue_coverage"]["coordinates"] == 1.0


def test_unresolved_venue_is_reported_without_fabricating_coordinates():
    tournaments, venues, report = master.build([match("m1", env=False)])
    assert tournaments[0]["venue_resolved_rate"] == 0.0
    assert venues[0]["latitude"] is None
    assert venues[0]["elevation_m"] is None
    assert report["venue_coverage"]["coordinates"] == 0.0
    assert report["missing"]["venues_without_coordinates"] == [venues[0]["venue_key"]]
