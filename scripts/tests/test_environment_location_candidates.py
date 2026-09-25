"""Regression tests for conservative Environment location resolution.

Run: PYTHONPATH=api python -m unittest discover -s scripts/tests
"""
import unittest

from tbt.services.environment import (
    ENVIRONMENT_RESOLVER_VERSION,
    _clean_tournament_location_part,
    location_candidates,
    resolve_match_venue,
    venue_context_compatible,
)


class RecordingGeocoder:
    def __init__(self):
        self.queries = []

    def geocode(self, query):
        self.queries.append(query)
        return None


class LocationCandidatesTest(unittest.TestCase):
    def test_utr_ptt_city_only(self):
        self.assertEqual(_clean_tournament_location_part("UTR PTT Saitama Men 06"), "Saitama")
        candidates = location_candidates({}, "UTR PTT Saitama Men 06")
        self.assertEqual(candidates, ["Saitama"])
        self.assertNotIn("UTR PTT Saitama Men 06", candidates)

    def test_itf_city_only(self):
        self.assertEqual(_clean_tournament_location_part("ITF M15 Astana 2 Men"), "Astana")
        self.assertEqual(location_candidates({}, "ITF M15 Astana 2 Men"), ["Astana"])

    def test_provider_country_limits_geocoding(self):
        payload = {"tournament": {"country": {"alpha2": "JP"}}}
        candidates = location_candidates(payload, "UTR PTT Saitama Men 06")
        self.assertEqual(candidates, ["Saitama, JP"])
        client = RecordingGeocoder()
        venue, query = resolve_match_venue(client, payload, "UTR PTT Saitama Men 06")
        self.assertIsNone(venue)
        self.assertIsNone(query)
        self.assertEqual(client.queries, ["Saitama, JP"])

    def test_itf_country_code(self):
        self.assertEqual(
            location_candidates({}, "ITF M15 Astana Men, M-ITF-KAZ-02A"),
            ["Astana, KZ"],
        )

    def test_unparseable_label_does_not_spend_api(self):
        client = RecordingGeocoder()
        self.assertEqual(location_candidates({}, "ATP Challenger Unknown Open 2026"), [])
        self.assertEqual(resolve_match_venue(client, {}, "ATP Challenger Unknown Open 2026"), (None, None))
        self.assertEqual(client.queries, [])

    def test_plain_city_allowed(self):
        self.assertEqual(location_candidates({}, "Saitama"), ["Saitama"])

    def test_existing_alias_preserved(self):
        self.assertIn("Miami, Florida, US", location_candidates({}, "Miami Open"))

    def test_egypt_el_sheikh_city_alias_is_country_scoped(self):
        payload = {
            "tournament": {"city": "Sharm ElSheikh", "country": {"alpha2": "EG"}}
        }
        q = location_candidates(payload, "Sharm ElSheikh, Singles Qualifying, W-ITF-EGY-31A")
        self.assertEqual(q[0], "sharm el sheikh, EG")
        venue = {
            "name": "Sharm El Sheikh", "query": q[0],
            "latitude": 27.86, "longitude": 34.3, "country": "Egypt",
        }
        self.assertTrue(venue_context_compatible(
            payload, "Sharm ElSheikh, Singles Qualifying, W-ITF-EGY-31A", venue
        )[0])

    def test_italian_santa_margherita_alias_is_country_scoped(self):
        payload = {
            "tournament": {"city": "S. Margherita Di Pula", "country": {"alpha2": "IT"}}
        }
        q = location_candidates(payload, "S. Margherita Di Pula, Singles Main, W-ITF-ITA-27A")
        self.assertEqual(q[0], "santa margherita di pula, IT")

    def test_hertogenbosch_tournament_alias_is_country_scoped(self):
        self.assertIn(
            "'s-Hertogenbosch, NL",
            location_candidates({}, "'s-Hertogenbosch"),
        )

    def test_monte_carlo_alias_accepts_monaco_but_rejects_wrong_country(self):
        q = location_candidates({}, "Monte Carlo")
        self.assertIn("Monaco, MC", q)
        self.assertTrue(venue_context_compatible({}, "Monte Carlo", {
            "query": "Monaco, MC", "name": "Monaco",
            "country": "Monaco", "latitude": 43.73, "longitude": 7.42,
        })[0])
        self.assertFalse(venue_context_compatible({}, "Monte Carlo", {
            "query": "Monaco, IT", "name": "Monaco",
            "country": "Italy", "latitude": 43.73, "longitude": 7.42,
        })[0])

    def test_dutch_city_spelling_variants_are_equivalent(self):
        for spelling in ("s-Hertogenbosch", "'s-Hertogenbosch", "Den Bosch"):
            with self.subTest(spelling=spelling):
                self.assertTrue(venue_context_compatible(
                    {}, "'s-Hertogenbosch",
                    {"name": spelling, "query": spelling + ", NL", "country": "Netherlands"},
                )[0])

    def test_antalya_does_not_override_explicit_different_provider_city(self):
        payload = {
            "tournament": {
                "city": "Belek",
                "country": {"alpha2": "TR"},
            }
        }
        accepted, reason = venue_context_compatible(
            payload, "Antalya, Singles Qualifying, M-ITF-TUR-29A",
            {"name": "Antalya", "query": "Antalya, TR", "country": "Turkey"},
        )
        self.assertFalse(accepted)
        self.assertEqual(reason, "provider_city_mismatch")

    def test_resolver_version_invalidates_old_negative_cache(self):
        self.assertGreaterEqual(ENVIRONMENT_RESOLVER_VERSION, 6)


if __name__ == "__main__":
    unittest.main()
