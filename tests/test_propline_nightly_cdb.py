import gzip
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase

from tbt.schemas import MatchRecord
from propline_nightly_cdb import plan_targets, stage_additions


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
