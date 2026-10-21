import importlib.util
import io
import json
import unittest
import tempfile
from datetime import datetime, timezone
from unittest import mock
from urllib.error import HTTPError
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "closeout", Path(__file__).resolve().parents[1] / "scripts/propline_nightly_closeout.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CloseoutContractTests(unittest.TestCase):
    def setUp(self):
        mod.STATE.update(calls=0, remaining=None, reason="", batches=0)
        mod.DATA.clear()
        # The production workflow exports the CDB gap path before running tests.
        # Isolate fixture tests from that path; targeted tests set their own index.
        patcher = mock.patch.dict(mod.os.environ, {"CLOSEOUT_GAP_TARGETS": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_utc_cutoff_excludes_new_quota(self):
        self.assertTrue(mod.allowed(datetime(2026, 10, 10, 21, 0, tzinfo=timezone.utc)))
        self.assertTrue(mod.allowed(datetime(2026, 10, 10, 22, 0, tzinfo=timezone.utc)))
        self.assertFalse(mod.allowed(datetime(2026, 10, 10, 23, 55, tzinfo=timezone.utc)))
        self.assertFalse(mod.allowed(datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)))

    def test_git_blob_sha_uses_nul_byte(self):
        import hashlib
        payload = b"test"
        expected = hashlib.sha1(b"blob 4" + bytes([0]) + payload).hexdigest()
        self.assertEqual(mod.blob_sha(payload), expected)

    def test_capped_before_provider_request(self):
        with mock.patch.object(mod, "MAX_CALLS", 750), mock.patch.object(mod, "now", return_value=datetime(2026, 10, 10, 22, tzinfo=timezone.utc)), mock.patch.object(mod.urllib.request, "urlopen", side_effect=AssertionError("No outbound call")):
            mod.STATE["calls"] = 750
            self.assertIsNone(mod.request("/sports/tennis/events"))
            self.assertEqual(mod.STATE["reason"], "run_cap")

    def test_exhausted_provider_quota_stops(self):
        with mock.patch.object(mod, "now", return_value=datetime(2026, 10, 10, 22, tzinfo=timezone.utc)), mock.patch.object(mod.urllib.request, "urlopen", side_effect=AssertionError("No outbound call")):
            mod.STATE["remaining"] = 0
            self.assertIsNone(mod.request("/sports/tennis/events"))
            self.assertEqual(mod.STATE["reason"], "daily_quota_exhausted")


    def test_unique_priced_tennis_markets_prioritized_over_generic_odds(self):
        self.assertEqual(
            mod.SPECIAL_MARKETS,
            ("player_break_points_won", "total_tiebreaks", "total_aces",
             "player_games_won"),
        )
        self.assertTrue(set(mod.SPECIAL_MARKETS).issubset(mod.MARKETS))
        self.assertLess(mod.odds_priority({"player_break_points_won"}),
                        mod.odds_priority({"player_aces"}))
        self.assertLess(mod.odds_priority({"total_tiebreaks"}),
                        mod.odds_priority({"h2h"}))
        self.assertLess(mod.odds_priority({"total_aces"}),
                        mod.odds_priority({"totals"}))
        self.assertEqual(mod.odds_priority(set()), len(mod.MARKETS))
        self.assertEqual(mod.MAX_CALLS, 750)

    def test_night_only_closeout_requests_all_advertised_niche_props_in_one_odds_call(self):
        utc = datetime(2026, 10, 11, 21, 0, tzinfo=timezone.utc)
        paths = []
        niche = {"player_break_points_won", "total_tiebreaks", "total_aces",
                 "player_games_won", "player_double_faults"}
        def fake_request(path, params=None):
            paths.append((path, params))
            if path == "/sports/tennis/events":
                return {"events": [
                    {"id": "101", "commence_time": "2026-10-12T01:00:00Z"},
                    {"id": "202", "commence_time": "2026-10-12T03:00:00Z"},
                ]}
            if path.endswith("/101/markets"):
                return {"markets": [{"key": "h2h"}]}
            if path.endswith("/202/markets"):
                return {"markets": [{"key": k} for k in sorted(niche)]}
            if path.endswith("/odds"):
                return {"bookmakers": []}
            raise AssertionError("Unexpected path: " + path)

        with mock.patch.object(mod, "KEY", "offline"), \
             mock.patch.object(mod, "TOKEN", "offline"), \
             mock.patch.object(mod, "now", return_value=utc), \
             mock.patch.object(mod, "request", side_effect=fake_request), \
             mock.patch.object(mod, "save"), \
             mock.patch.object(mod, "flush_if_needed"):
            mod.collect()

        odds = [(path, params) for path, params in paths if path.endswith("/odds")]
        self.assertEqual(len(odds), 2)
        self.assertEqual(odds[0][0], "/sports/tennis/events/202/odds")
        self.assertEqual(set(odds[0][1]["markets"].split(",")), niche)
        self.assertEqual(odds[1][0], "/sports/tennis/events/101/odds")
        self.assertEqual(odds[1][1]["markets"], "h2h")


    def test_player_game_probe_targets_only_unambiguous_atp_wta_singles(self):
        future = [
            (datetime(2026, 10, 12, tzinfo=timezone.utc),
             {"tour": "ATP", "home_team": "Carlos Alcaraz", "away_team": "Novak Djokovic"}),
            (datetime(2026, 10, 13, tzinfo=timezone.utc),
             {"tour": "WTA", "home_team": "Iga Swiatek", "away_team": "Carlos Alcaraz"}),
            (datetime(2026, 10, 14, tzinfo=timezone.utc),
             {"tour": "ITF", "home_team": "Other Player", "away_team": "Another Person"}),
            (datetime(2026, 10, 15, tzinfo=timezone.utc),
             {"tour": "ATP", "home_team": "Player A / Player B", "away_team": "Fake Pair"}),
        ]
        self.assertEqual(mod.select_player_game_targets(future),
                         ["Carlos Alcaraz", "Novak Djokovic", "Iga Swiatek"])

    def test_player_game_probe_is_research_only_and_excludes_partial_values(self):
        payload = {"games": [
            {"status": "final", "stats": {"aces": 5, "dblfaults": 2, "breakpts_w": 3}},
            {"status": "in_progress", "stats": {"aces": 99}},
            {"status": "final", "stats": {"aces": None, "sets_won": 2}},
            {"status": "final", "stats": {"aces": True}},
        ]}
        summary = mod.summarize_player_games(payload)
        self.assertTrue(summary["response_shape_valid"])
        self.assertEqual(summary["games"], 4)
        self.assertEqual(summary["completed_with_focus"], 2)
        self.assertEqual(summary["focus_fields"],
                         {"aces": 1, "dblfaults": 1, "breakpts_w": 1, "sets_won": 1})
        self.assertFalse(mod.summarize_player_games({"other": []})["response_shape_valid"])

    def test_nightly_player_game_probe_archives_raw_and_keeps_max_750_and_same_odds_paths(self):
        utc = datetime(2026, 10, 11, 21, 0, tzinfo=timezone.utc)
        calls = []
        stored = []
        def fake_request(path, params=None, **kw):
            calls.append((path, params, kw))
            if path == "/sports/tennis/events":
                return {"events": [
                    {"id": "17", "tour": "ATP", "home_team": "Carlos Alcaraz",
                     "away_team": "Novak Djokovic",
                     "commence_time": "2026-10-12T01:00:00Z"},
                ]}
            if path.endswith("/games"):
                return {"player_name": "Carlos Alcaraz", "games": [
                    {"status": "final", "event_id": "1", "stats":
                     {"aces": 12, "dblfaults": 2}},
                ]}
            if path.endswith("/markets"):
                return {"markets": [{"key": "player_aces"}]}
            if path.endswith("/odds"):
                return {"bookmakers": []}
            raise AssertionError(path)
        def flush(day, runid):
            stored.extend(mod.DATA)
            mod.DATA.clear()

        with mock.patch.object(mod, "KEY", "offline"), \
             mock.patch.object(mod, "TOKEN", "offline"), \
             mock.patch.object(mod, "now", return_value=utc), \
             mock.patch.object(mod, "request", side_effect=fake_request), \
             mock.patch.object(mod, "save", side_effect=lambda *a: flush(*a)), \
             mock.patch.object(mod, "flush_if_needed"):
            mod.collect()
        player_calls = [x for x in calls if x[0].endswith("/games")]
        self.assertEqual(len(player_calls), 2)
        self.assertTrue(all(x[1] == {"limit": 100} for x in player_calls))
        self.assertTrue(all(x[2].get("allow_not_found") is True for x in player_calls))
        self.assertEqual(len([x for x in calls if x[0].endswith("/odds")]), 1)
        raw = [x for x in stored if x.get("stage") == "player_game_stats_probe"]
        self.assertEqual(len(raw), 2)
        self.assertEqual(raw[0]["summary"]["focus_fields"]["aces"], 1)
        self.assertEqual(raw[0]["payload"]["games"][0]["stats"]["dblfaults"], 2)
        self.assertTrue(raw[0]["research_only"])
        self.assertEqual(mod.MAX_CALLS, 750)

    def test_missing_player_game_log_does_not_block_night_odds(self):
        utc = datetime(2026, 10, 11, 22, tzinfo=timezone.utc)
        error = HTTPError("https://api.prop-line.com/v1/x", 404, "Not Found", {}, None)
        with mock.patch.object(mod, "now", return_value=utc), \
             mock.patch.object(mod.urllib.request, "urlopen", side_effect=error), \
             mock.patch.object(mod.time, "sleep", return_value=None):
            self.assertIsNone(mod.request("/sports/tennis/players/A/games",
                                          allow_not_found=True))
        self.assertEqual(mod.STATE["reason"], "")
        self.assertEqual(mod.STATE["calls"], 1)


    def test_optional_player_games_403_does_not_starve_existing_night_odds(self):
        utc = datetime(2026, 10, 11, 22, tzinfo=timezone.utc)
        error = HTTPError("https://api.prop-line.com/v1/x", 403, "Forbidden", {}, None)
        with mock.patch.object(mod, "now", return_value=utc), \
             mock.patch.object(mod.urllib.request, "urlopen", side_effect=error), \
             mock.patch.object(mod.time, "sleep", return_value=None):
            with self.assertRaises(mod.OptionalStatsAccessUnavailable):
                mod.request("/sports/tennis/players/A/games", allow_not_found=True)
        self.assertEqual(mod.STATE["reason"], "")
        self.assertEqual(mod.STATE["calls"], 1)
        targets = [(utc, {"tour": "ATP", "home_team": "Carlos Alcaraz",
                          "away_team": "Novak Djokovic"})]
        attempts = []
        def unsupported(*args, **kwargs):
            attempts.append(args)
            raise mod.OptionalStatsAccessUnavailable()
        with mock.patch.object(mod, "request", side_effect=unsupported):
            mod.probe_player_games(targets, "2026-10-11", "123")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(mod.STATE["reason"], "")


    def test_night_target_index_uses_canonical_players_not_next_slate(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "gaps.json"
            path.write_text(json.dumps({
                "schema": 1, "source": "canonical_cdb_2026",
                "partition_sha256": "a" * 64,
                "targets": [{"player_name": "Carlos Alcaraz", "score": 6},
                            {"player_name": "Novak Djokovic", "score": 2}],
            }), encoding="utf-8")
            with mock.patch.dict(mod.os.environ, {"CLOSEOUT_GAP_TARGETS": str(path)}):
                self.assertEqual(mod._targeted_player_names(),
                                 ["Carlos Alcaraz", "Novak Djokovic"])

    def test_night_target_reserves_fifty_remaining_calls_for_odds(self):
        utc = datetime(2026, 10, 12, 21, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "gaps.json"
            path.write_text(json.dumps({
                "schema": 1, "source": "canonical_cdb_2026",
                "partition_sha256": "b" * 64,
                "targets": [{"player_name": f"Player{j} Person", "score": 1}
                            for j in range(90)],
            }), encoding="utf-8")
            mod.STATE["remaining"] = 70
            def respond(*args, **kwargs):
                mod.STATE["calls"] += 1
                mod.STATE["remaining"] -= 1
                return {"games": [{"status": "final", "stats": {"aces": 3}}]}
            with mock.patch.dict(mod.os.environ, {"CLOSEOUT_GAP_TARGETS": str(path)}), \
                 mock.patch.object(mod, "request", side_effect=respond), \
                 mock.patch.object(mod, "now", return_value=utc), \
                 mock.patch.object(mod, "flush_if_needed"):
                mod.probe_player_games([], "2026-10-12", "test")
            self.assertEqual(mod.STATE["calls"], 20)
            self.assertEqual(mod.STATE["remaining"], 50)

    def test_night_player_probe_stops_after_thirty_empty_lookups(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "gaps.json"
            path.write_text(json.dumps({
                "schema": 1, "source": "canonical_cdb_2026",
                "partition_sha256": "b" * 64,
                "targets": [{"player_name": f"Missing{j} Person", "score": 1}
                            for j in range(90)],
            }), encoding="utf-8")
            def respond(*args, **kwargs):
                mod.STATE["calls"] += 1
                return {"games": []}
            with mock.patch.dict(mod.os.environ, {"CLOSEOUT_GAP_TARGETS": str(path)}), \
                 mock.patch.object(mod, "request", side_effect=respond), \
                 mock.patch.object(mod, "flush_if_needed"):
                mod.probe_player_games([], "2026-10-12", "test")
            self.assertEqual(mod.STATE["calls"], 30)
            self.assertEqual(mod.STATE["reason"], "")

    def test_gap_probes_rotate_between_nights_within_priority_tiers(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "gaps.json"
            targets = [
                {"player_name": f"Tierzero{j} Player", "api_pro_priority": 0}
                for j in range(90)
            ] + [
                {"player_name": f"Tierone{j} Player", "api_pro_priority": 1}
                for j in range(30)
            ]
            path.write_text(json.dumps({
                "schema": 1, "source": "canonical_cdb_2026",
                "partition_sha256": "c" * 64, "targets": targets,
            }), encoding="utf-8")
            with mock.patch.dict(mod.os.environ, {"CLOSEOUT_GAP_TARGETS": str(path)}):
                first = mod._targeted_player_names("2026-10-12")
                second = mod._targeted_player_names("2026-10-13")
            self.assertEqual(len(first), 120)
            self.assertEqual(len(second), 120)
            self.assertEqual(set(first), set(second))
            self.assertFalse(set(first[:30]) & set(second[:30]))
            self.assertTrue(all(name.startswith("Tierzero") for name in first[:90]))
            self.assertTrue(all(name.startswith("Tierzero") for name in second[:90]))


    def test_recent_final_scores_fetch_all_raw_boxscore_types_for_exact_cdb_pair(self):
        utc = datetime(2026, 10, 21, 21, 0, tzinfo=timezone.utc)
        seen = []
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "targets.json"
            path.write_text(json.dumps({
                "schema": 1, "source": "canonical_cdb_2026",
                "partition_sha256": "e" * 64,
                "recent_event_targets": [{
                    "date_utc": "2026-10-20",
                    "players": ["Carlos Alcaraz", "Jannik Sinner"],
                }],
            }))
            def fake_request(endpoint, params=None, **kw):
                seen.append((endpoint, params, kw))
                if endpoint.endswith("/scores"):
                    return {"scores": [
                        {"id": "111", "status": "final",
                         "commence_time": "2026-10-20T13:00:00Z",
                         "home_team": "Carlos Alcaraz", "away_team": "Jannik Sinner"},
                        {"id": "222", "status": "final",
                         "commence_time": "2026-10-20T14:00:00Z",
                         "home_team": "Different Player", "away_team": "Other Opponent"},
                    ]}
                if endpoint.endswith("/111/stats"):
                    return {"id": "111", "status": "final",
                            "commence_time": "2026-10-20T13:00:00Z",
                            "home_team": "Carlos Alcaraz", "away_team": "Jannik Sinner",
                            "stats": [
                                {"player_name": "Carlos Alcaraz", "stat_type": "total_games",
                                 "stat_value": 22},
                                {"player_name": "Jannik Sinner", "stat_type": "sets_won",
                                 "stat_value": 1},
                            ]}
                raise AssertionError(endpoint)
            with mock.patch.dict(mod.os.environ, {"CLOSEOUT_GAP_TARGETS": str(path)}), \\
                 mock.patch.object(mod, "now", return_value=utc), \\
                 mock.patch.object(mod, "request", side_effect=fake_request), \\
                 mock.patch.object(mod, "flush_if_needed"):
                mod.probe_recent_event_stats("2026-10-21", "123")
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0][1], {"days_from": 3})
        self.assertTrue(all(kw["optional_stats"] for _, _, kw in seen))
        self.assertEqual(len(mod.DATA), 1)
        self.assertEqual(mod.DATA[0]["stage"], "event_stats_probe")
        self.assertEqual(mod.DATA[0]["payload"]["stats"][0]["stat_type"], "total_games")

    def test_score_phase_keeps_remaining_odds_quota(self):
        mod.STATE["remaining"] = mod.NIGHTLY_ODDS_RESERVE
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "targets.json"
            path.write_text(json.dumps({
                "schema": 1, "source": "canonical_cdb_2026",
                "partition_sha256": "e" * 64,
                "recent_event_targets": [{"date_utc": "2026-10-20",
                                          "players": ["Carlos Alcaraz", "Jannik Sinner"]}],
            }))
            with mock.patch.dict(mod.os.environ, {"CLOSEOUT_GAP_TARGETS": str(path)}), \\
                 mock.patch.object(mod, "request", side_effect=AssertionError("spent reserve")):
                mod.probe_recent_event_stats("2026-10-21", "123")
        self.assertEqual(mod.STATE["calls"], 0)

    def test_player_logs_with_games_and_sets_do_not_trigger_aces_only_stop(self):
        utc = datetime(2026, 10, 21, 21, 0, tzinfo=timezone.utc)
        requested = []
        def respond(path, *args, **kwargs):
            requested.append(path)
            mod.STATE["calls"] += 1
            return {"games": [{"status": "final", "stats": {"total_games": 21,
                      "sets_won": 2, "set_1_games": 10}}]}
        with mock.patch.object(mod, "_targeted_player_names",
                               return_value=[f"Player{i} Name" for i in range(40)]), \\
             mock.patch.object(mod, "now", return_value=utc), \\
             mock.patch.object(mod, "request", side_effect=respond), \\
             mock.patch.object(mod, "flush_if_needed"):
            mod.probe_player_games([], "2026-10-21", "test")
        self.assertEqual(len(requested), 40)
        self.assertEqual(len(mod.DATA), 40)
        self.assertIn("set_1_games", mod.DATA[0]["summary"]["focus_fields"])

    def test_optional_stats_network_errors_do_not_block_later_odds(self):
        utc = datetime(2026, 10, 21, 21, 0, tzinfo=timezone.utc)
        error = TimeoutError("upstream socket")
        with mock.patch.object(mod, "now", return_value=utc), \\
             mock.patch.object(mod.urllib.request, "urlopen", side_effect=error), \\
             mock.patch.object(mod.time, "sleep", return_value=None):
            self.assertIsNone(mod.request("/sports/tennis/scores", optional_stats=True))
        self.assertEqual(mod.STATE["reason"], "")
        self.assertEqual(mod.STATE["calls"], 1)

    def test_persistence_retries_transient_github_503(self):
        transient = HTTPError("https://api.github.com/x", 503, "unavailable", {}, None)
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(b'{"sha": "a"}')
        with mock.patch.object(mod.urllib.request, "urlopen",
                               side_effect=[transient, response]) as urlopen, \
             mock.patch.object(mod.time, "sleep") as nap:
            result = mod.github("research/test.json.gz")
        self.assertEqual(result, {"sha": "a"})
        self.assertEqual(urlopen.call_count, 2)
        nap.assert_called_once()

    def test_save_batch_preserves_on_readback_failure(self):
        mod.DATA.append({"event_id": "123", "odds": {"bookmakers": []}})
        with mock.patch.object(mod, "github", return_value=None), \
             mock.patch.object(mod.time, "sleep"), \
             mock.patch("pathlib.Path.write_bytes", return_value=1):
            with self.assertRaisesRegex(RuntimeError, "read-back FAILED"):
                mod.save("2026-10-10", "123")
        self.assertEqual(len(mod.DATA), 1)
        self.assertEqual(mod.STATE["batches"], 0)


if __name__ == "__main__":
    unittest.main()
