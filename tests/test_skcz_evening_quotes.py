"""Fortuna evening quote attachment: no UI changes, exact match or local fallback."""
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api"))
from skcz_evening_quotes import (
    _same_person, attach_prices, load_evening_report, validated_events,
    FORTUNA_PROVIDER_ID,
)
from ace_working_odds import local_player_aces_ou, verified_ace_odds
from tbt.services.most_aces_pricing import (
    freeze_most_aces_price, verified_api_pro_most_aces_odds,
)

NOW = datetime(2026, 11, 10, 4, 15, tzinfo=timezone.utc)
CAPTURE = "2026-11-09T21:00:00+00:00"
START = "2026-11-10T12:00:00+00:00"
EVENT = "ufo:mtch:1xl-1gk"


def row(market):
    return {
        "event_id": "provider-model-7123",
        "market": market, "price_status": "projection_only",
        "price_contract": "player_superiority" if market == "most_aces" else None,
        "odds": None,
        "scheduled_at": START, "selection_id": "model-p1",
        "player1": {"id": "model-p1", "name": "Alex Michelsen"},
        "player2": {"id": "model-p2", "name": "Juan Manuel Cerundolo"},
        "projection_model": "ace-count-projection-v4",
        "projection": 9.0, "opponent_projection": 4.0,
        "projection_confidence": 0.75,
    }


def report(*, markets=None, captured=CAPTURE, scheduled=START, names=None):
    markets = markets if markets is not None else [
        {"kind": "player_aces_ou", "market_name": "Michelsen A.: počet es",
         "verified_pairs": [
             {"market_id": "ufo:aces-7", "player": "Michelsen A.", "line": 7.5,
              "over": 1.87, "under": 1.91}
         ]},
        {"kind": "most_aces_match", "market_name": "Kto má viac es v zápase",
         "verified_pairs": [
             {"market_id": "ufo:more", "settlement": "bookmaker_rules_not_yet_verified",
              "two_way_outcomes": [
                  {"selection": "Michelsen A.", "odds": 1.69, "market_id": "ufo:more"},
                  {"selection": "Cerundolo J.M.", "odds": 2.13, "market_id": "ufo:more"},
              ]}
         ]},
    ]
    return {
        "schema": 1, "source": "public_fortuna_sk", "status": "audited",
        "target_betting_day": "2026-11-10", "captured_at": captured,
        "cdb_writes": 0, "published_picks_changed": 0,
        "events_in_target_window": [{
            "provider": "fortuna_sk", "event_id": EVENT,
            "players": names if names is not None else ["Michelsen A.", "Cerundolo J.M."],
            "scheduled_at": scheduled, "captured_at": captured,
            "aces_markets": markets,
        }],
    }


class FortunaMorningAttachment(unittest.TestCase):
    def test_names_require_surname_and_all_initials(self):
        self.assertTrue(_same_person("Michelsen A.", "Alex Michelsen"))
        self.assertTrue(_same_person("Cerundolo J.M.", "Juan Manuel Cerundolo"))
        self.assertFalse(_same_person("Cerundolo J.", "Juan Manuel Cerundolo"))
        self.assertFalse(_same_person("Michelsen X.", "Alex Michelsen"))
        self.assertFalse(_same_person("Michelsen", "Alex Michelsen"))

    def test_exact_player_aces_uses_fortuna_price_without_new_pick(self):
        a = row("aces")
        before = local_player_aces_ou(a)
        self.assertEqual(before["market_line"], 7.5)
        aces, most, info = attach_prices([a], [], report(), now=NOW)
        self.assertEqual(len(aces), 1)
        self.assertEqual(len(most), 0)
        self.assertEqual(info["aces"], 1)
        selected = aces[0]
        self.assertEqual(selected["odds"], 1.87)
        self.assertEqual(selected["ou_side"], "over")
        self.assertEqual(selected["market_line"], 7.5)
        self.assertEqual(selected["selection_id"], "model-p1")
        self.assertEqual(selected["odds_source"], "fortuna_sk")
        self.assertEqual(selected["odds_bookmaker"], "Fortuna SK")
        self.assertEqual(selected["provider_id"], FORTUNA_PROVIDER_ID)
        self.assertEqual(verified_ace_odds(selected), 1.87)

    def test_fallback_if_no_exact_line_and_do_not_create_missing_picks(self):
        a = row("aces")
        r = report(markets=[{
            "kind": "player_aces_ou", "market_name": "Michelsen A.: počet es",
            "verified_pairs": [{
                "market_id": "line-6.5", "player": "Michelsen A.",
                "line": 6.5, "over": 1.7, "under": 2.2,
            }],
        }])
        aces, _, info = attach_prices([a], [], r, now=NOW)
        self.assertEqual(aces, [a])
        self.assertEqual(info["aces"], 0)
        self.assertIsNotNone(local_player_aces_ou(aces[0]))

    def test_more_aces_uses_exact_selected_player_then_freezes_without_overwrite(self):
        a = row("most_aces")
        aces, most, info = attach_prices([], [a], report(), now=NOW)
        self.assertEqual(len(aces), 0)
        self.assertEqual(info["most_aces"], 1)
        self.assertEqual(most[0]["odds"], 1.69)
        self.assertEqual(most[0]["odds_source"], "fortuna_sk")
        self.assertEqual(verified_api_pro_most_aces_odds(most[0]), 1.69)
        self.assertEqual(freeze_most_aces_price(most[0]), most[0])

    def test_no_quote_keeps_approved_statistical_fallback(self):
        a = row("most_aces")
        _, result, info = attach_prices([], [a], report(markets=[]), now=NOW)
        self.assertEqual(result, [a])
        self.assertEqual(info["most_aces"], 0)
        local = freeze_most_aces_price(result[0])
        self.assertEqual(local["odds_source"], "blinq_statistical")
        self.assertGreaterEqual(local["odds"], 1.5)
        self.assertLessEqual(local["odds"], 1.7)

    def test_unpublishable_short_fortuna_prices_preserve_both_fallbacks(self):
        r = report()
        r["events_in_target_window"][0]["aces_markets"][0]["verified_pairs"][0]["over"] = 1.20
        r["events_in_target_window"][0]["aces_markets"][1]["verified_pairs"][0]["two_way_outcomes"][0]["odds"] = 1.20
        a, w = row("aces"), row("most_aces")
        aces, most, info = attach_prices([a], [w], r, now=NOW)
        self.assertEqual((aces, most), ([a], [w]))
        self.assertEqual((info["aces"], info["most_aces"]), (0, 0))
        self.assertIsNotNone(local_player_aces_ou(aces[0]))
        self.assertEqual(freeze_most_aces_price(most[0])["odds_source"], "blinq_statistical")

    def test_set_specific_market_not_used_for_full_match(self):
        a = row("most_aces")
        r = report(markets=[{"kind": "aces_set_other", "market_name": "1. set: Viac es",
                             "verified_pairs": [
                                 {"market_id": "set", "settlement": "bookmaker_rules_not_yet_verified",
                                  "two_way_outcomes": [
                                      {"selection": "Michelsen A.", "odds": 1.2},
                                      {"selection": "Cerundolo J.M.", "odds": 4.0},
                                  ]}]}])
        _, most, info = attach_prices([], [a], r, now=NOW)
        self.assertEqual(most, [a])
        self.assertEqual(info["most_aces"], 0)

    def test_wrong_entrant_or_changed_schedule_does_not_match(self):
        a = row("aces")
        cases = [
            report(names=["Michelsen X.", "Cerundolo J.M."]),
            report(scheduled="2026-11-10T14:00:00+00:00"),
            report(captured="2026-11-10T14:00:00+00:00"),
        ]
        for candidate in cases:
            with self.subTest(candidate=candidate["captured_at"]):
                aces, _, info = attach_prices([a], [], candidate, now=NOW)
                self.assertEqual(aces, [a])
                self.assertEqual(info["aces"], 0)

    def test_ambiguous_multiple_fortuna_events_use_fallback(self):
        r = report()
        r["events_in_target_window"].append({
            **r["events_in_target_window"][0], "event_id": "ufo:mtch:other",
        })
        a = row("aces")
        aces, _, info = attach_prices([a], [], r, now=NOW)
        self.assertEqual(aces, [a])
        self.assertEqual(info["aces"], 0)

    def test_already_priced_provider_is_not_overwritten(self):
        a = row("aces")
        a.update(odds=1.73, price_status="priced_projection", odds_source="rapidapi")
        aces, _, info = attach_prices([a], [], report(), now=NOW)
        self.assertEqual(aces, [a])
        self.assertEqual(info["aces"], 0)

    def test_invalid_report_and_early_next_day_match(self):
        r = report()
        r["source"] = "untrusted"
        self.assertEqual(validated_events(r, betting_day="2026-11-10", now=NOW), [])
        r = report(scheduled="2026-11-11T03:30:00+00:00")
        r["events_in_target_window"][0]["scheduled_at"] = "2026-11-11T03:30:00+00:00"
        self.assertEqual(len(validated_events(r, betting_day="2026-11-10", now=NOW)), 1)

    def test_private_snapshot_read_and_provenance(self):
        r = report()
        contents = base64.b64encode(json.dumps(r).encode()).decode()
        directory = [{"name": "fortuna-12345.json", "type": "file"}]

        def mocked_gh(argv):
            return json.dumps(directory if argv[-1].endswith("2026-11-10") else
                              {"content": contents}).encode()

        loaded, state = load_evening_report(
            betting_day="2026-11-10", now=NOW, runner=mocked_gh,
        )
        self.assertEqual(state, "loaded")
        self.assertEqual(loaded["events_in_target_window"][0]["event_id"], EVENT)


if __name__ == "__main__":
    unittest.main()
