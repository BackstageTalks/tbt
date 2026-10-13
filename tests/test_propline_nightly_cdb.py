import gzip
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase

from tbt.schemas import MatchRecord
from propline_nightly_cdb import plan_targets, stage_additions, api_pro_gap_reason, gap_inventory


def match(mid="cdb-1", day=10, both=False, pair=("Carlos Alcaraz", "Novak Djokovic"),
          stats=None):
    return MatchRecord(
        match_id=mid, tour="atp",
        scheduled_at=datetime(2026, 10, day, 10, tzinfo=timezone.utc),
        player1_id="11", player1_name=pair[0],
        player2_id="22", player2_name=pair[1],
        winner_id="11", stats={} if stats is None else stats,
    )


def source(player="Carlos Alcaraz", game_day=10, ace=7, df=2, opp=11,
           event_id="812", status="final", pair=("Carlos Alcaraz", "Novak Djokovic")):
    return {"stage": "player_game_stats_probe", "player_name": player,
            "research_only": True, "payload": {"games": [{
                "status": status, "event_id": event_id,
                "commence_time": f"2026-10-{game_day:02d}T10:00:00Z",
                "home_team": pair[0], "away_team": pair[1],
                "stats": {"aces": ace, "dblfaults": df, "opp_aces": opp},
            }]}}


def save(reports, rows):
    with gzip.open(reports / "batch.json.gz", "wt", encoding="utf-8") as fp:
        json.dump({"research_only": True, "records": rows}, fp)


class NightCanonicalGapsTests(TestCase):
    def test_targets_are_from_unfilled_canonical_and_not_upcoming_board(self):
        today = datetime(2026, 10, 12, tzinfo=timezone.utc)
        rows = [
            match("one", day=10),
            match("two", day=9, pair=("Carlos Alcaraz", "Jannik Sinner")),
            match("ready", day=8, pair=("Daniil Medvedev", "Andrey Rublev"),
                  stats={f"{s}_{k}": 3 for s in ("p1", "p2")
                         for k in ("aces", "double_faults")}),
        ]
        targets = plan_targets(rows, today)
        self.assertEqual(targets[0]["player_name"], "Carlos Alcaraz")
        self.assertNotIn("Daniil Medvedev", [row["player_name"] for row in targets])
        self.assertEqual(len(targets), len(set(x["player_name"] for x in targets)))

    def test_gap_inventory_counts_only_missing_cells_and_quarantines_conflicts(self):
        now = datetime(2026, 10, 13, tzinfo=timezone.utc)
        row = match("partial", stats={"p1_aces": 5, "p1_double_faults": None})
        row.provider_payload = {
            "_tbt_event_identity": {"event_id": "777", "home": "11",
                                    "away": "22", "status": "finished"},
            "_tbt_statistics": {"schema": 3, "event_id": "777",
                                 "status": "unavailable",
                                 "reason": "no_supported_fields"},
        }
        conflict = match("conflict", day=9, pair=("Learner Tien", "Casper Ruud"))
        conflict.provider_payload = {
            "_tbt_event_identity": {"event_id": "888", "home": "11",
                                    "away": "22", "status": "finished"},
            "_tbt_statistics": {"schema": 3, "event_id": "888",
                                 "status": "conflict"},
        }
        counts = gap_inventory([row, conflict], now)
        self.assertEqual(counts["eligible_matches"], 1)
        self.assertEqual(counts["missing_cells"], 3)
        self.assertEqual(counts["missing_ace_cells"], 1)
        self.assertEqual(counts["missing_df_cells"], 2)
        self.assertEqual(counts["api_pro_conflict_quarantined_matches"], 1)
        self.assertEqual(counts["missing_cells_by_api_pro_reason"]
                         ["api_pro_unavailable_no_supported_fields"], 3)

    def test_strict_stage_adds_only_exact_ace_df_count_cells(self):
        today = datetime(2026, 10, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root, [source(), source("Novak Djokovic", ace=11, df=3, opp=7)])
            stage, counts = stage_additions([match()], root, today)
        self.assertEqual(len(stage), 1)
        self.assertEqual(stage[0]["incoming_stats"], {
            "p1_aces": 7, "p1_double_faults": 2,
            "p2_aces": 11, "p2_double_faults": 3,
        })
        self.assertEqual(counts["new_stat_cells_staged"], 4)
        self.assertTrue(stage[0]["import_ready"])
        self.assertEqual(stage[0]["provenance"][0]["provider_event_id"], "812")

    def test_existing_stat_conflicts_fail_closed_instead_of_overwriting(self):
        today = datetime(2026, 10, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root, [source()])
            staged, counts = stage_additions(
                [match(stats={"p1_aces": 99})], root, today)
        self.assertFalse(staged)
        self.assertEqual(counts["canonical_stat_conflict"], 1)

    def test_reject_ambiguous_pair_date_wrong_day_and_nonfinal(self):
        today = datetime(2026, 10, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root, [source(), source(game_day=11),
                        source(status="upcoming")])
            staged, counts = stage_additions(
                [match("one"), match("another_same_pair")], root, today)
        self.assertFalse(staged)
        self.assertEqual(counts["ambiguous"], 1)
        self.assertEqual(counts["unmatched"], 1)

    def test_cross_provider_event_identity_conflict_quarantines(self):
        today = datetime(2026, 10, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root, [source(), source(event_id="999")])
            staged, counts = stage_additions([match()], root, today)
        self.assertFalse(staged)
        self.assertEqual(counts["quarantined"], 1)

    def test_source_and_cdb_numeric_stat_disagreement_quarantined(self):
        today = datetime(2026, 10, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root, [source(), source("Novak Djokovic", ace=13, opp=7)])
            staged, counts = stage_additions([match()], root, today)
        self.assertFalse(staged)
        self.assertEqual(counts["quarantined"], 1)

    def test_source_snapshot_is_not_eligible_to_leak_future_results(self):
        today = datetime(2026, 10, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root, [source(game_day=16)])
            staged, counts = stage_additions([match(day=16)], root, today)
        self.assertFalse(staged)
        self.assertEqual(counts["invalid_observation_date"], 1)

    def test_missing_service_point_denominators_are_not_fabricated(self):
        today = datetime(2026, 10, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root, [source()])
            stage, _ = stage_additions([match()], root, today)
        self.assertEqual(set(stage[0]["incoming_stats"]),
                         {"p1_aces", "p1_double_faults", "p2_aces"})

    def test_standard_api_pro_explicit_unavailable_precedes_generic_cdb_gaps(self):
        now = datetime(2026, 10, 12, tzinfo=timezone.utc)
        unavailable = match(
            "failed", pair=("Jannik Sinner", "Carlos Alcaraz"),
            stats={"p1_aces": None},
        )
        unavailable.provider_payload = {
            "_tbt_event_identity": {
                "event_id": "778", "home": "11", "away": "22", "status": "finished",
            },
            "_tbt_statistics": {
                "schema": 3, "event_id": "778", "status": "unavailable",
                "reason": "no_supported_fields",
                "fetched_at": "2026-10-11T17:00:00Z",
            },
        }
        # Many missing fields, but API PRO did not previously fail for them.
        generic = [
            match(f"generic-{i}", day=9-i,
                  pair=("Ben Shelton", f"Different Opponent {i}"))
            for i in range(1, 5)
        ]
        for i, row in enumerate(generic):
            # A valid API PRO event ID with no prior attempt is tier 3;
            # truly missing event IDs must correctly remain tier 1.
            row.provider_payload = {"_tbt_event_identity": {
                "event_id": str(901 + i), "home": "11", "away": "22",
                "status": "finished",
            }}
        candidates = plan_targets(generic + [unavailable], now)
        self.assertEqual(candidates[0]["player_name"], "Carlos Alcaraz")
        self.assertEqual(candidates[0]["api_pro_priority"], 0)
        self.assertIn("api_pro_unavailable_no_supported_fields",
                      candidates[0]["api_pro_gap_reasons"])
        self.assertTrue(any(row["api_pro_priority"] == 3 for row in candidates))

    def test_no_api_pro_event_id_is_an_explicit_standard_collector_skip(self):
        now = datetime(2026, 10, 12, tzinfo=timezone.utc)
        row = match("no-event-id")
        self.assertEqual(api_pro_gap_reason(row), "api_pro_skipped_no_event_id")
        targeted = plan_targets([row], now)
        self.assertTrue(targeted)
        self.assertEqual(targeted[0]["api_pro_priority"], 1)
        self.assertGreater(targeted[0]["api_pro_skipped_fields"], 0)

    def test_partial_api_pro_marks_remaining_fields_and_conflict_quarantines(self):
        now = datetime(2026, 10, 12, tzinfo=timezone.utc)
        partial = match("partial", day=10)
        partial.provider_payload = {
            "_tbt_event_identity": {"event_id": "822", "home": "11",
                                    "away": "22", "status": "finished"},
            "_tbt_statistics": {"schema": 3, "event_id": "822",
                                "status": "available",
                                "fetched_at": "2026-10-11T18:00:00Z"},
        }
        conflict = match("conflict", day=9, pair=("Learner Tien", "Casper Ruud"))
        conflict.provider_payload = {
            "_tbt_event_identity": {"event_id": "912", "home": "11",
                                    "away": "22", "status": "finished"},
            "_tbt_statistics": {"schema": 3, "event_id": "912",
                                "status": "conflict",
                                "reason": "existing_canonical_stat_conflict"},
        }
        self.assertEqual(api_pro_gap_reason(partial), "api_pro_partial_statistics")
        self.assertIsNone(api_pro_gap_reason(conflict))
        planned = plan_targets([partial, conflict], now)
        self.assertEqual(planned[0]["api_pro_priority"], 2)
        self.assertNotIn("Learner Tien", [row["player_name"] for row in planned])
        self.assertNotIn("Casper Ruud", [row["player_name"] for row in planned])

    def test_stale_or_unlinked_api_pro_markers_are_not_false_unavailable_evidence(self):
        row = match()
        row.provider_payload = {
            "_tbt_event_identity": {"event_id": "190", "home": "11",
                                    "away": "22", "status": "finished"},
            "_tbt_statistics": {"schema": 3, "event_id": "different",
                                "status": "unavailable",
                                "reason": "no_supported_fields"},
        }
        self.assertEqual(api_pro_gap_reason(row), "api_pro_not_yet_attempted")
        row.provider_payload["_tbt_statistics"]["event_id"] = "190"
        row.provider_payload["_tbt_statistics"]["schema"] = 2
        self.assertEqual(api_pro_gap_reason(row), "api_pro_not_yet_attempted")

    def test_unambiguous_all_period_failure_is_selected_by_actual_api_pro_reason(self):
        row = match()
        row.provider_payload = {
            "_tbt_event_identity": {"event_id": "190", "home": "11",
                                    "away": "22", "status": "finished"},
            "_tbt_statistics": {"schema": 3, "event_id": "190",
                                "status": "unavailable",
                                "reason": "missing_unambiguous_all_period"},
        }
        self.assertEqual(api_pro_gap_reason(row),
                         "api_pro_unavailable_missing_unambiguous_all_period")

    def test_source_found_via_other_player_still_does_not_import_api_pro_conflict(self):
        row = match()
        row.provider_payload = {
            "_tbt_event_identity": {"event_id": "190", "home": "11",
                                    "away": "22", "status": "finished"},
            "_tbt_statistics": {"schema": 3, "event_id": "190",
                                "status": "conflict",
                                "reason": "existing_canonical_stat_conflict"},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root, [source()])
            staged, counts = stage_additions(
                [row], root, datetime(2026, 10, 12, tzinfo=timezone.utc))
        self.assertFalse(staged)
        self.assertEqual(counts["api_pro_conflict_quarantined"], 1)
