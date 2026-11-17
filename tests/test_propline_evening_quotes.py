"""Regression tests for exact, model-first morning PropLine archive attachment."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from propline_evening_odds import collect
from propline_evening_quotes import (
    attach_prices, validated_events, load_evening_report, _same_person
)
from ace_working_odds import verified_ace_odds

CAPTURE = datetime(2026, 11, 17, 22, 0, tzinfo=timezone.utc)
MORNING = datetime(2026, 11, 18, 5, 30, tzinfo=timezone.utc)
DAY = "2026-11-18"


def source():
    return {"events": [{
        "id": "1234",
        "home_team": "Alexander Zverev",
        "away_team": "Ben Shelton",
        "commence_time": "2026-11-18T12:00:00Z",
        "sport_title": "ATP Finals",
        "bookmakers": [{
            "key": "napoleon",
            "markets": [{
                "key": "player_aces", "last_update": CAPTURE.isoformat(),
                "outcomes": [
                    {"description": "Ben Shelton", "name": "Over",
                     "point": 10.5, "price": -110},
                    {"description": "Ben Shelton", "name": "Under",
                     "point": 10.5, "price": -105},
                    {"description": "Alexander Zverev", "name": "11+ Aces",
                     "price": 140},
                ],
            }],
        }, {
            "key": "sleeper",
            "markets": [{
                "key": "player_aces",
                "outcomes": [
                    {"description": "Ben Shelton", "name": "Over",
                     "point": 10.5, "price": 150},
                    {"description": "Ben Shelton", "name": "Under",
                     "point": 10.5, "price": -150},
                ],
            }],
        }],
    }]}


def report(data=None):
    return collect(date.fromisoformat(DAY), now=CAPTURE,
                   get=lambda: (data if data is not None else source(), 420))


def card():
    return {
        "event_id": "rapidapi-678",
        "market": "aces",
        "projection_model": "ace-count-projection-v4",
        "price_status": "projection_only",
        "odds": None,
        "scheduled_at": "2026-11-18T12:00:00+00:00",
        "player1": {"id": "p1", "name": "Alexander Zverev"},
        "player2": {"id": "p2", "name": "Ben Shelton"},
        "selection_id": "p2",
        "projection": 12,
        "opponent_projection": 9,
        "projection_confidence": 0.72,
    }


class EveningQuoteAttachment(unittest.TestCase):
    def test_full_exact_sportsbook_pair_attaches_without_altering_pick(self):
        original = card()
        before = deepcopy(original)
        priced, stats = attach_prices([original], report(), now=MORNING, betting_day=DAY)
        self.assertEqual(original, before)
        self.assertEqual(stats["matched_aces"], 1)
        self.assertEqual(len(priced), 1)
        self.assertEqual(priced[0]["event_id"], before["event_id"])
        self.assertEqual(priced[0]["selection_id"], before["selection_id"])
        self.assertEqual(priced[0]["market_line"], 10.5)
        self.assertEqual(priced[0]["price_contract"], "player_total_ou")
        self.assertEqual(priced[0]["odds_source"], "propline")
        self.assertEqual(priced[0]["odds_bookmaker"], "napoleon")
        self.assertEqual(priced[0]["odds_provider_event_id"], "1234")
        self.assertEqual(priced[0]["provider_id"], 2)
        self.assertGreaterEqual(verified_ace_odds(priced[0]), 1.5)

    def test_no_match_does_not_create_or_delete_cards(self):
        first = card()
        first["projection"] = 5  # generated line differs from 10.5
        second = deepcopy(first)
        second["event_id"] = "different-id"
        result, stats = attach_prices([first, second], report(), now=MORNING, betting_day=DAY)
        self.assertEqual(result, [first, second])
        self.assertEqual(stats["matched_aces"], 0)

    def test_explicit_issuer_line_or_direction_never_overwritten(self):
        wrong_line = {**card(), "market_line": 9.5,
                      "price_contract": "player_total_ou", "ou_side": "over"}
        wrong_side = {**card(), "market_line": 10.5,
                      "price_contract": "player_total_ou", "ou_side": "under"}
        priced, stats = attach_prices([wrong_line, wrong_side], report(),
                                      now=MORNING, betting_day=DAY)
        self.assertEqual(priced, [wrong_line, wrong_side])
        self.assertEqual(stats["matched_aces"], 0)

    def test_one_sided_milestone_never_becomes_ou_price(self):
        p = source()
        markets = p["events"][0]["bookmakers"][0]["markets"][0]["outcomes"]
        markets[:] = [o for o in markets if o.get("name") == "11+ Aces"]
        result, stats = attach_prices([card()], report(p), now=MORNING, betting_day=DAY)
        self.assertEqual(result, [card()])
        self.assertEqual(stats["matched_aces"], 0)

    def test_dfs_only_never_becomes_bookmaker_quote(self):
        p = source()
        p["events"][0]["bookmakers"] = p["events"][0]["bookmakers"][1:]
        result, stats = attach_prices([card()], report(p), now=MORNING, betting_day=DAY)
        self.assertEqual(result, [card()])
        self.assertEqual(stats["matched_aces"], 0)

    def test_other_player_and_wrong_start_rejected(self):
        c = card()
        c["selection_id"] = "p1"
        result, _ = attach_prices([c], report(), now=MORNING, betting_day=DAY)
        self.assertEqual(result, [c])
        c = card()
        c["scheduled_at"] = "2026-11-18T17:00:00+00:00"
        result, _ = attach_prices([c], report(), now=MORNING, betting_day=DAY)
        self.assertEqual(result, [c])

    def test_duplicate_fixtures_fail_closed(self):
        raw = source()
        raw["events"].append(deepcopy(raw["events"][0]))
        raw["events"][1]["id"] = "7777"
        result, stats = attach_prices([card()], report(raw), now=MORNING, betting_day=DAY)
        self.assertEqual(result, [card()])
        self.assertEqual(stats["ambiguous_fixtures"], 1)

    def test_published_and_already_priced_untouched(self):
        base = card()
        issued = deepcopy(base)
        issued["issued_at"] = "2026-11-18T05:00:00+00:00"
        priced = deepcopy(base)
        priced["price_status"] = "priced_projection"
        priced["odds"] = 1.80
        result, stats = attach_prices([issued, priced], report(),
                                      now=MORNING, betting_day=DAY)
        self.assertEqual(result, [issued, priced])
        self.assertEqual(stats["matched_aces"], 0)

    def test_stale_wrong_day_and_changed_raw_evidence_rejected(self):
        r = report()
        self.assertEqual(len(validated_events(r, betting_day=DAY, now=MORNING)), 1)
        self.assertEqual(validated_events(r, betting_day="2026-11-19", now=MORNING), [])
        self.assertEqual(validated_events(r, betting_day=DAY, now=MORNING + timedelta(days=2)), [])
        modified = deepcopy(r)
        ou = next(m for m in modified["events_in_target_window"][0]["aces_markets"]
                  if m["kind"] == "player_aces_ou")
        ou["verified_pairs"][0]["over"] = 5.55
        self.assertEqual(validated_events(modified, betting_day=DAY, now=MORNING), [])
        modified = deepcopy(r)
        modified["events_in_target_window"][0]["provider_raw_event"]["id"] = "999"
        self.assertEqual(validated_events(modified, betting_day=DAY, now=MORNING), [])

    def test_no_partial_response_or_unsafe_source(self):
        r = report()
        r["coverage_truncated"] = True
        self.assertEqual(validated_events(r, betting_day=DAY, now=MORNING), [])
        r = report()
        r["cdb_writes"] = 1
        self.assertEqual(validated_events(r, betting_day=DAY, now=MORNING), [])

    def test_real_bookmaker_2_decimal_guard_consistent_with_existing_logic(self):
        data = source()
        outcomes = data["events"][0]["bookmakers"][0]["markets"][0]["outcomes"]
        outcomes[0]["price"] = 100  # bookmaker 2.00 is excluded by current ace contract
        result, stats = attach_prices([card()], report(data), now=MORNING, betting_day=DAY)
        self.assertEqual(result, [card()])
        self.assertEqual(stats["matched_aces"], 0)

    def test_multiple_bookmakers_same_contract_choose_deterministic_price(self):
        data = source()
        napoleon = deepcopy(data["events"][0]["bookmakers"][0])
        napoleon["key"] = "superbet_pl"
        napoleon["markets"][0]["outcomes"][0]["price"] = 125  # 2.25
        data["events"][0]["bookmakers"].append(napoleon)
        result, stats = attach_prices([card()], report(data), now=MORNING, betting_day=DAY)
        self.assertEqual(stats["matched_aces"], 1)
        self.assertEqual(result[0]["odds_bookmaker"], "superbet_pl")
        self.assertEqual(result[0]["odds"], 2.25)

    def test_archival_read_only_does_not_call_propline_and_handles_missing(self):
        r = report()
        encoded = base64.b64encode(json.dumps(r).encode()).decode()
        calls = []

        def runner(args):
            calls.append(args)
            if args[-1].endswith("/" + DAY):
                return json.dumps([{"name": "propline-12345.json",
                                    "type": "file"}]).encode()
            return json.dumps({"encoding": "base64", "content": encoded}).encode()

        loaded, status = load_evening_report(betting_day=DAY, now=MORNING,
                                             runner=runner)
        self.assertEqual(status, "loaded")
        self.assertEqual(loaded["source"], "propline_free")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(args[:2] == ["gh", "api"] for args in calls))
        missing, status = load_evening_report(
            betting_day=DAY, now=MORNING,
            runner=lambda args: (_ for _ in ()).throw(OSError("offline")))
        self.assertIsNone(missing)
        self.assertTrue(status.startswith("unavailable:"))

    def test_strict_initials_not_surname_only(self):
        self.assertTrue(_same_person("Shelton B.", "Ben Shelton"))
        self.assertFalse(_same_person("Shelton", "Ben Shelton"))
        self.assertFalse(_same_person("Shelton C.", "Ben Shelton"))


if __name__ == "__main__":
    unittest.main()
