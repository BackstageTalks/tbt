"""Fail-closed canary guards for a one-cell canonical CDB import."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cdb_33_native_one_cell_pilot as pilot

ROW = {
    "pilot": "blinq-native-33-single-cell-v1",
    "policy": pilot.POLICY,
    "utc_year": 2020, "match_id": "hist-js:atp:" + "a" * 24,
    "additions": {"p1_break_point_return_win": 0.5},
}
class CanaryContract(unittest.TestCase):
    def stage_file(self, row):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "stage.jsonl"
        path.write_text(json.dumps(row) + "\n")
        return path

    def test_exactly_one_cell_permitted(self):
        self.assertEqual(pilot.load_stage(self.stage_file(ROW)), [ROW])

    def test_no_second_field(self):
        with self.assertRaises(ValueError):
            pilot.load_stage(self.stage_file({**ROW, "additions": {
                "p1_break_point_return_win": 0.5,
                "p2_break_point_return_win": 0.4,
            }}))

    def test_no_non_bp_fields(self):
        with self.assertRaises(ValueError):
            pilot.load_stage(self.stage_file({**ROW, "additions": {"p1_aces": 99}}))

    def test_no_other_year(self):
        with self.assertRaises(ValueError):
            pilot.load_stage(self.stage_file({**ROW, "utc_year": 2026}))

    def test_no_empty_file(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "empty.jsonl"
        path.write_text("")
        with self.assertRaises(ValueError):
            pilot.load_stage(path)

    def test_no_two_rows(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "two.jsonl"
        path.write_text(json.dumps(ROW) + "\n" + json.dumps(ROW) + "\n")
        with self.assertRaises(ValueError):
            pilot.load_stage(path)

    def test_identity_sidecar_requires_sha_receipt(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "fake-sidecar.jsonl"
        path.write_text(json.dumps({
            "tour": "atp", "source_namespace": "drive-atp-main-sackmann",
            "source_event_id": "2020-8888:300",
            "canonical_match_id": ROW["match_id"],
        }) + "\n")
        with self.assertRaises(ValueError):
            pilot.verified_links(path)

    def test_rank_only_original_event_witness_can_add_one_postmatch_null(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        source = {
            "tourney_id":"2020-8888","match_num":"300",
            "tourney_date":"20200106","round":"F",
            "winner_name":"Novak Djokovic","loser_name":"Rafael Nadal",
            "winner_id":"104925","loser_id":"104745",
        }
        mid,_ = pilot.source_match_id("atp",Path("atp_matches_2020.csv"),source,2)
        match = SimpleNamespace(
            match_id=mid,tour="atp",status="completed",is_completed=True,
            scheduled_at=datetime(2020,1,6,tzinfo=timezone.utc),
            player1_id="hist-js:atp:104925",player2_id="hist-js:atp:104745",
            winner_id="hist-js:atp:104925",stats={},
            provider_payload={"_tbt_rank_provenance":{
                "source":"jeff_sackmann_match_snapshot:atp_matches_2020.csv"}},
            to_storage_dict=lambda:{"match_id":mid,"stats":{}},
        )
        with patch.object(pilot, "_source_rates", return_value={"p1_break_point_return_win":0.5}), \
             patch.object(pilot, "_stats", return_value={}):
            row,reason=pilot.attested_rank_only_candidate(
                match,source,Path("atp_matches_2020.csv"),2,"a"*64)
            self.assertEqual(reason,"staged_attested_rank_only_original")
            self.assertEqual(row["additions"],{"p1_break_point_return_win":0.5})
            match.provider_payload={}
            denied,reason=pilot.attested_rank_only_candidate(
                match,source,Path("atp_matches_2020.csv"),2,"a"*64)
            self.assertIsNone(denied)
            self.assertEqual(reason,"missing_original_rank_source_witness")

    def test_rank_only_rejects_conflicting_original_player_identity(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        source = {"tourney_id":"2020-8888","match_num":"300",
            "tourney_date":"20200106","round":"F",
            "winner_name":"Novak Djokovic","loser_name":"Rafael Nadal",
            "winner_id":"104925","loser_id":"104745"}
        mid,_=pilot.source_match_id("atp",Path("atp_matches_2020.csv"),source,2)
        wrong=SimpleNamespace(match_id=mid,is_completed=True,status="completed",
            scheduled_at=datetime(2020,1,6,tzinfo=timezone.utc),
            player1_id="hist-js:atp:WRONG",player2_id="hist-js:atp:104745",
            winner_id="hist-js:atp:WRONG",stats={},
            provider_payload={"_tbt_rank_provenance":{
                "source":"jeff_sackmann_match_snapshot:atp_matches_2020.csv"}},
            to_storage_dict=lambda:{"match_id":mid,"stats":{}})
        r,reason=pilot.attested_rank_only_candidate(wrong,source,Path("atp_matches_2020.csv"),2,"a"*64)
        self.assertIsNone(r)
        self.assertEqual(reason,"rank_only_original_identity_conflict")

    def test_pinned_private_receipt_scope(self):
        self.assertEqual(pilot.VERIFIED_SHA, "e0945ee8437203b6db2e8a5e3e2eccc72e21df38a3a247925abc17eedc7c0935")
        self.assertEqual(pilot.SOURCE_COMMIT, "83733587353df8a41f2fd4f516147d5aa83f5a8d")

    def test_stage_returns_selected_at_most_one(self):
        with patch.object(pilot, "verified_links", return_value=[]):
            with patch.object(pilot, "indexes", return_value=({}, {}, {})):
                with patch.object(pilot, "cdb_index", return_value={"2020":{}, "2021":{}}):
                    with self.assertRaises(ValueError):
                        pilot.stage(None, None, None, None)

if __name__ == "__main__":
    unittest.main()
