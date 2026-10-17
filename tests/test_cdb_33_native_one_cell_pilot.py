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

    def test_sha_pinned_multisegment_original_tournament_ids(self):
        rows = []
        for n in range(33):
            native = ("2020-M-DC-2020-WG-M-USA-ITA-01:11" if n == 0
                      else f"2021-8888:{100+n}")
            rows.append({
                "tour": "atp",
                "source_namespace": "drive-atp-main-sackmann",
                "source_event_id": native,
                "canonical_match_id": f"hist-js:atp:{n:024x}",
            })
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "original-id-sidecar.jsonl"
        payload = "".join(json.dumps(row) + "\n" for row in rows)
        path.write_text(payload)
        import hashlib
        with patch.object(pilot, "VERIFIED_SHA", hashlib.sha256(payload.encode()).hexdigest()):
            self.assertEqual(len(pilot.verified_links(path)), 33)
            rows[0]["source_event_id"] = "2020-../../unsafe:11"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            with patch.object(pilot, "VERIFIED_SHA", hashlib.sha256(path.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError, "Unexpected tournament-match"):
                    pilot.verified_links(path)

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
