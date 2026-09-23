from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from enrich_environment_snapshot import VenueKnowledge, _needs_work
from tbt.services.environment import (
    ENVIRONMENT_RESOLVER_VERSION,
    OpenMeteoClient,
    location_candidates,
)


NOW = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)


def make_match(tournament="Unknown Event", tournament_id=17):
    return SimpleNamespace(tournament=tournament, tournament_id=tournament_id, tour="atp")


def negative(at):
    return {
        "_tbt_environment": {
            "venue_resolved": False,
            "resolver_version": ENVIRONMENT_RESOLVER_VERSION,
            "enriched_at_utc": at.isoformat(),
        }
    }


def needs(payload, *, retry=True, knowledge=None, match=None, hours=72):
    return _needs_work(
        match=match or make_match(),
        payload=payload,
        knowledge=knowledge or VenueKnowledge(),
        force=False,
        complete_static=True,
        retry_unresolved=retry,
        now=NOW,
        negative_retry_hours=hours,
    )


def test_recent_negative_is_not_re_geocoded_for_three_days():
    assert needs(negative(NOW - timedelta(hours=2))) == (False, "negative_cooldown")
    assert needs(negative(NOW - timedelta(hours=71))) == (False, "negative_cooldown")


def test_old_negative_or_explicit_zero_cooldown_can_retry():
    assert needs(negative(NOW - timedelta(hours=73))) == (True, "retry_unresolved")
    assert needs(negative(NOW - timedelta(hours=1)), hours=0) == (True, "retry_unresolved")


def test_missing_and_old_resolver_are_prioritized_without_waiting():
    assert needs({}) == (True, "missing")
    payload = negative(NOW - timedelta(hours=1))
    payload["_tbt_environment"]["resolver_version"] -= 1
    assert needs(payload) == (True, "stale_unresolved")


def test_explicit_retry_off_skips_current_negative():
    assert needs(negative(NOW - timedelta(days=30)), retry=False) == (
        False, "unresolved_current_resolver"
    )


def test_fresh_verified_positive_history_overrides_negative_cooldown():
    match = make_match("Monastir", tournament_id=51)
    provider = {"tournament": {"city": "Monastir", "country": {"name": "Tunisia"}}}
    venue = {
        "query": "Monastir, TN", "name": "Monastir",
        "latitude": 35.778, "longitude": 10.8262, "country": "Tunisia",
    }
    knowledge = VenueKnowledge()
    knowledge.add(match, provider, venue)
    payload = {**provider, **negative(NOW - timedelta(hours=1))}
    assert needs(payload, knowledge=knowledge, match=match) == (
        True, "learned_unresolved"
    )


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"results": []}


class FakeHTTP:
    def __init__(self):
        self.calls = 0

    def get(self, url, params):
        self.calls += 1
        return FakeResponse()

    def close(self):
        pass


def test_repeat_geocoder_negative_is_cached_without_extra_http_calls():
    http = FakeHTTP()
    client = OpenMeteoClient(client=http, min_interval_seconds=0)
    assert client.geocode("No-such-city, US") is None
    assert client.geocode("No-such-city, US") is None
    assert http.calls == 1
    assert client.request_count == 1
    assert client.geocode.cache_info().hits >= 1
    client.close()


def test_additional_exact_tennis_city_aliases_are_not_fuzzy():
    assert location_candidates({}, "Pozoblanco, Singles Qualifying")[0] == "Pozoblanco, ES"
    assert location_candidates({}, "Little Rock, Singles")[0] == "Little Rock, Arkansas, US"
    assert location_candidates({}, "Little Pond, Singles")[0] != "Little Rock, Arkansas, US"
