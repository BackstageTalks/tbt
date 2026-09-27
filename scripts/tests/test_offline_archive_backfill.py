"""Deterministic offline-only recovery tests; no network or API credentials."""
from __future__ import annotations

from datetime import datetime, timezone
import unittest

from offline_archive_backfill import (
    _direct_indoor, _geo_candidates, _score_from_archived_event,
    _verified_archive_venue,
)
from tbt.schemas import MatchRecord
from tbt.services.environment import Venue


def fixture(payload=None, *, winner="a", surface="hard"):
    return MatchRecord(
        match_id="offline-fixture", tour="atp",
        scheduled_at=datetime(2025, 8, 12, tzinfo=timezone.utc),
        player1_id="a", player1_name="A", player2_id="b", player2_name="B",
        winner_id=winner, status="finished", surface=surface,
        tournament="Saitama", tournament_id="t1", provider_payload=payload or {},
    )


class StaticGazetteer:
    def __init__(self, *, ambiguous=False):
        self.ambiguous = ambiguous
        self.calls = []
    def resolve(self, query, country):
        self.calls.append((query, country))
        if country != "JP":
            return None
        if query.startswith("Saitama"):
            return Venue(query=query, name="Saitama", latitude=35.86,
                         longitude=139.64, country="JP", elevation_m=None, timezone="Asia/Tokyo")
        if query.startswith("Other") and self.ambiguous:
            return Venue(query=query, name="Other", latitude=36.9,
                         longitude=140.7, country="JP", elevation_m=None, timezone="Asia/Tokyo")
        return None


class OfflineArchiveTests(unittest.TestCase):
    def test_surface_proves_indoor(self):
        got, why = _direct_indoor(fixture(surface="indoor_hard"))
        self.assertTrue(got)
        self.assertIn("surface", why)

    def test_outdoor_string_boolean_is_inverted(self):
        got, _ = _direct_indoor(fixture({"isOutdoor": "true"}))
        self.assertIs(got, False)
        got, _ = _direct_indoor(fixture({"isOutdoor": "false"}))
        self.assertIs(got, True)

    def test_explicit_disagreement_fails_closed(self):
        got, why = _direct_indoor(fixture({"indoor": True, "isOutdoor": True}))
        self.assertIsNone(got)
        self.assertIn("conflicting", why)

    def test_never_infer_outdoor_from_clay(self):
        got, why = _direct_indoor(fixture({"surface":"clay"}, surface="clay"))
        self.assertIsNone(got)
        self.assertEqual(why, "no_explicit_indoor_evidence")

    def test_verified_archived_score_without_provider(self):
        raw = {
            "homeTeam": {"id": "a"}, "awayTeam": {"id": "b"},
            "status": {"type": "finished"},
            "homeScore": {"period1": 6, "period2": 6, "current": 2},
            "awayScore": {"period1": 4, "period2": 4, "current": 0},
        }
        stats, best_of, why = _score_from_archived_event(fixture(raw))
        self.assertEqual(best_of, 3)
        self.assertEqual(stats["total_games"], 20)
        self.assertEqual(stats["p1_sets_won"], 2)
        self.assertIn("archived_event", why)

    def test_wrong_winner_never_attached(self):
        raw = {
            "homeTeam": {"id": "a"}, "awayTeam": {"id": "b"},
            "status": {"type": "finished"},
            "homeScore": {"period1": 6, "period2": 6, "current": 2},
            "awayScore": {"period1": 4, "period2": 4, "current": 0},
        }
        stats, best_of, why = _score_from_archived_event(fixture(raw, winner="b"))
        self.assertEqual(stats, {})
        self.assertIsNone(best_of)
        self.assertEqual(why, "score_winner_conflict")

    def test_conflicting_existing_score_never_overwritten(self):
        raw = {
            "homeTeam": {"id": "a"}, "awayTeam": {"id": "b"},
            "status": {"type": "finished"},
            "homeScore": {"period1": 6, "period2": 6, "current": 2},
            "awayScore": {"period1": 4, "period2": 4, "current": 0},
        }
        match = fixture(raw)
        match.stats["total_games"] = 22.0
        stats, _, why = _score_from_archived_event(match)
        self.assertEqual(stats, {})
        self.assertEqual(why, "existing_score_conflict")

    def test_countryless_venue_is_not_guessed(self):
        match = fixture({"venue":{"city":"Saitama"}})
        self.assertEqual(_geo_candidates(match), [])

    def test_verified_country_scoped_location(self):
        raw = {
            "venue":{"city":"Saitama", "country":{"alpha2":"JP"}},
            "tournament":{"country":{"alpha2":"JP"}}
        }
        match = fixture(raw)
        queries = _geo_candidates(match)
        self.assertIn("Saitama, JP", queries)
        gazetteer = StaticGazetteer()
        env, why = _verified_archive_venue(gazetteer, match, queries)
        self.assertIs(env["venue_resolved"], True)
        self.assertFalse(env["training_eligible_weather"])
        self.assertEqual(env["venue"]["country"], "JP")
        self.assertEqual(why,"verified_unique_city_country")

    def test_ambiguous_multiple_cities_refused(self):
        raw = {"venue":{"city":"Saitama", "country":{"alpha2":"JP"}},
               "tournament":{"country":{"alpha2":"JP"}}}
        match = fixture(raw)
        gazetteer = StaticGazetteer(ambiguous=True)
        env, why = _verified_archive_venue(gazetteer, match,
                                            ["Saitama, JP", "Other, JP"])
        self.assertIsNone(env)
        self.assertEqual(why, "ambiguous")


if __name__ == "__main__":
    unittest.main()
