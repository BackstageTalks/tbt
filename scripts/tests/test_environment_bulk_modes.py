"""Bulk Environment safety regression tests; no live API access."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from enrich_environment_snapshot import (
    _build_venue_knowledge, _learned_environment, _needs_work
)
from tbt.services.environment import (
    OpenMeteoBudgetExceeded, OpenMeteoClient, GEOCODE_URL,
    location_candidates, venue_context_compatible,
)


class ForbiddenNetwork:
    def get(self, *args, **kwargs):
        raise AssertionError("Cache-only attempted a network request")

    def close(self):
        pass


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"results": [{
            "name": "Saitama",
            "latitude": 35.86,
            "longitude": 139.65,
            "elevation": 15,
            "timezone": "Asia/Tokyo",
            "country": "Japan",
            "country_code": "JP",
        }]}


class RecordingNetwork:
    def __init__(self):
        self.calls = []

    def get(self, url, params):
        self.calls.append((url, params))
        if url != GEOCODE_URL:
            raise AssertionError("Unexpected non-geocoding request")
        return FakeResponse()

    def close(self):
        pass


def fixture_match(*, resolved):
    payload = {
        "tournament": {
            "name": "UTR PTT Saitama Men 06",
            "city": "Saitama",
            "country": {"alpha2": "JP"},
        }
    }
    if resolved:
        payload["_tbt_environment"] = {
            "venue_resolved": True,
            "resolver_version": 6,
            "venue": {
                "name": "Saitama",
                "query": "Saitama, JP",
                "latitude": 35.86,
                "longitude": 139.65,
                "elevation_m": 15,
                "country": "Japan",
                "timezone": "Asia/Tokyo",
            },
        }
    return SimpleNamespace(
        match_id="fixture", tour="ITF", tournament_id="saitama",
        tournament="UTR PTT Saitama Men 06",
        provider_payload=payload,
        scheduled_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


class BulkEnvironmentSafetyTests(unittest.TestCase):
    def test_history_cache_recovery_zero_network(self):
        resolved, missing = fixture_match(resolved=True), fixture_match(resolved=False)
        knowledge = _build_venue_knowledge([resolved])
        client = OpenMeteoClient(request_limit=1, min_interval_seconds=0, client=ForbiddenNetwork())
        env, key = _learned_environment(
            client=client, match=missing, payload=missing.provider_payload,
            knowledge=knowledge, include_weather=False,
        )
        self.assertIsNotNone(key)
        self.assertEqual(env["source"], "history-venue-cache")
        self.assertTrue(env["venue_resolved"])
        self.assertEqual(client.request_count, 0)
        self.assertNotIn("weather", env)

    def test_existing_compatible_venue_not_pending(self):
        match = fixture_match(resolved=True)
        pending, reason = _needs_work(
            match=match, payload=match.provider_payload,
            knowledge=_build_venue_knowledge([match]),
            force=False, complete_static=True, retry_unresolved=False,
        )
        self.assertFalse(pending)
        self.assertEqual(reason, "resolved")

    def test_country_mismatch_rejected(self):
        match = fixture_match(resolved=False)
        incompatible = {
            "name": "Saitama", "latitude": 1, "longitude": 1,
            "country": "United States", "query": "Saitama, US",
        }
        self.assertFalse(venue_context_compatible(
            match.provider_payload, match.tournament, incompatible
        )[0])

    def test_identical_preferred_query_is_single_request(self):
        network = RecordingNetwork()
        client = OpenMeteoClient(request_limit=1, min_interval_seconds=0, client=network)
        query = location_candidates(fixture_match(resolved=False).provider_payload,
                                    "UTR PTT Saitama Men 06")[0]
        first, second = client.geocode(query), client.geocode(query)
        self.assertEqual(first, second)
        self.assertEqual(len(network.calls), 1)
        self.assertEqual(client.request_count, 1)
        self.assertEqual(query, "Saitama, JP")
        with self.assertRaises(OpenMeteoBudgetExceeded):
            client.geocode("Tokyo, JP")


if __name__ == "__main__":
    unittest.main()
