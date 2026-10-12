import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

FILE = Path(__file__).resolve().parents[1] / "scripts" / "quarantine_tml_recovery_on_cdb_race.py"
spec = importlib.util.spec_from_file_location("quarantine_tml_recovery", FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class NativeRecoveryArchiveGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.original = self.root / "old-manifest"
        self.fresh = self.root / "fresh-manifest"
        self.original.write_bytes(b'{"version":1}')
        self.fresh.write_bytes(b'{"version":1}')
        self.report_dir = self.root / "report"
        self.report_dir.mkdir()
        self.row = {
            "schema": 1,
            "canonical_match_id": None,
            "official_identity_verified": False,
            "import_ready": False,
            "write_authorized": False,
            "model_feature_allowed": False,
            "reason": "SYNTHETIC_LISTING_ID_REQUIRES_OFFICIAL_NATIVE_MATCH",
        }
        self.save_report()

    def tearDown(self):
        self.tmp.cleanup()

    def save_report(self):
        raw = (json.dumps(self.row) + "\n").encode()
        (self.report_dir / "private-native-id-recovery-queue.jsonl").write_bytes(raw)
        (self.report_dir / "private-three-way-candidates.jsonl").write_bytes(b"")
        self.report = {
            "status": "THREE_WAY_OFFICIAL_ATP_READ_ONLY",
            "ready_for_cdb_write": 0,
            "cdb_writes": 0,
            "model_trained": False,
            "api_requests": 0,
            "native_id_recovery_queue_sha256": hashlib.sha256(raw).hexdigest(),
            "counts": {"private_native_id_recovery_candidates": 1,
                       "three_way_official_review_candidates": 0},
        }
        self.write_summary()

    def write_summary(self):
        (self.report_dir / "report.json").write_text(json.dumps(self.report))

    def test_same_snapshot_stays_read_only(self):
        r = mod.guard(self.original, self.fresh, self.report_dir)
        self.assertEqual(r["archive_status"], "CURRENT_READ_ONLY_RESEARCH_SNAPSHOT")
        self.assertEqual(r["ready_for_cdb_write"], 0)

    def test_changed_snapshot_quarantines_private_queue(self):
        self.fresh.write_bytes(b'{"version":2}')
        r = mod.guard(self.original, self.fresh, self.report_dir)
        self.assertEqual(r["archive_status"], "STALE_CDB_SOURCE_ONLY_RECOVERY_QUARANTINE")
        report = json.loads((self.report_dir / "report.json").read_text())
        self.assertFalse(report["canonical_snapshot_current_at_archive_gate"])
        self.assertFalse(report["write_authorized"])
        self.assertFalse(report["model_feature_allowed"])
        self.assertEqual(r["source_only_queue"], 1)

    def test_changed_snapshot_with_canonical_witness_refused(self):
        self.fresh.write_bytes(b'{"version":2}')
        self.report["counts"]["three_way_official_review_candidates"] = 1
        self.write_summary()
        with self.assertRaises(ValueError):
            mod.guard(self.original, self.fresh, self.report_dir)

    def test_changed_snapshot_with_nonempty_canonical_file_refused(self):
        self.fresh.write_bytes(b'{"version":2}')
        (self.report_dir / "private-three-way-candidates.jsonl").write_text('{"match_id":"x"}\n')
        with self.assertRaises(ValueError):
            mod.guard(self.original, self.fresh, self.report_dir)

    def test_preauthorized_queue_never_published(self):
        self.row["write_authorized"] = True
        self.save_report()
        with self.assertRaises(ValueError):
            mod.guard(self.original, self.fresh, self.report_dir)

    def test_tampered_queue_digest_blocked(self):
        (self.report_dir / "private-native-id-recovery-queue.jsonl").write_text('{"x": 3}\n')
        with self.assertRaises(ValueError):
            mod.guard(self.original, self.fresh, self.report_dir)

    def test_model_trained_flag_blocks(self):
        self.report["model_trained"] = True
        self.write_summary()
        with self.assertRaises(ValueError):
            mod.guard(self.original, self.fresh, self.report_dir)


if __name__ == "__main__":
    unittest.main()
