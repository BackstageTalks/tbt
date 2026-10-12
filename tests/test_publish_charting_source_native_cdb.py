"""Offline, no-GitHub tests for the protected Charting CDB sidecar publisher."""
import gzip
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import publish_charting_source_native_cdb as publish


class ProtectedChartingStageTests(unittest.TestCase):
    def make_stage(self, root):
        root = pathlib.Path(root)
        assets = {}
        for tour, (csvsha, rows) in publish.EXPECTED_SOURCE.items():
            filename = f"charting-observations-{tour}-v1.jsonl.gz"
            path = root / filename
            row = {
                "tour": tour, "source_csv_sha256": csvsha, "source_match_id": "TEST",
                "canonical_match_id": None, "canonical_player_id": None,
                "independent_provider_event_identity": False,
                "canonical_write_allowed": False, "whole_match_stats_eligible": False,
                "prediction_training_allowed": False, "available_at": None,
                "observation_scope": "charted_point_sample_unknown_completeness",
            }
            line = (json.dumps(row, sort_keys=True) + "\n").encode()
            with gzip.open(path, "wb") as target:
                target.write(line * rows)
            assets[tour] = {"name": filename, "rows": rows,
                            "source_csv_sha256": csvsha,
                            "bytes": path.stat().st_size,
                            "sha256": publish.sha(path)}
        m = {
            "namespace": "charting_observations/v1", "source_total_matches": 11822,
            "total_source_rows": 23635, "total_source_native_rows": 23618,
            "total_quarantined_rows": 17, "fields_preserved_nonempty": 7315237,
            "canonical_event_join_approved": False,
            "canonical_statistics_changed": False,
            "canonical_history_partitions_modified": False,
            "training_model_eligible": False, "provider_api_requests": 0,
            "assets": assets,
        }
        (root / publish.MANIFEST).write_text(json.dumps(m))
        return m

    def test_stage_readonly_without_github(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.make_stage(root)
            result = publish.perform(root, root / "backup", root / "readback", write=False)
            self.assertEqual(result["canonical_writes"], 0)
            self.assertEqual(result["rows"], 23635)
            self.assertFalse((root / "backup").exists())

    def test_refuse_publish_off_authorized_github_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.make_stage(root)
            with patch.dict("os.environ", {"GITHUB_ACTIONS": "false", "GITHUB_REPOSITORY": "untrusted/repo"}):
                with self.assertRaisesRegex(ValueError, "approved"):
                    publish.perform(root, root / "backup", root / "readback", write=True)

    def test_refuse_canonical_event_link_and_training_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.make_stage(root)
            manifest_path = root / publish.MANIFEST
            manifest = json.loads(manifest_path.read_text())
            manifest["training_model_eligible"] = True
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "Untrusted"):
                publish.stage_check(root)

    def test_refuse_changed_binary_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.make_stage(root)
            with (root / "charting-observations-wta-v1.jsonl.gz").open("ab") as stream:
                stream.write(b"tamper")
            with self.assertRaisesRegex(ValueError, "byte/hash mismatch"):
                publish.stage_check(root)


if __name__ == "__main__":
    unittest.main()
