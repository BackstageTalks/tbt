"""Read-only metadata discovery is NEVER equivalent to cross-provider identity."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_audit_uploaded_atp2025_current_cdb import sample
from audit_atp2025_metadata_candidates import review


class MetadataOnly(unittest.TestCase):
    def test_unique_four_counts_full_score_not_importable(self):
        source, _, canonical = sample()
        report = review([source], list(canonical.values()))
        self.assertEqual(report["counts"]["unique_metadata_candidates_not_verified"], 1)
        self.assertEqual(report["counts"]["metadata_four_count_score_corroborated"], 1)
        self.assertGreater(report["research_null_cells_not_authorized"], 0)
        self.assertEqual(report["canonical_links_authorized"], 0)
        self.assertEqual(report["cdb_writes"], 0)
        self.assertFalse(report["import_ready"])

    def test_name_conflict_never_creates_candidate(self):
        source, _, canonical = sample()
        canonical["synthetic-cdb-1"]["player2_name"] = "Unrelated Person"
        report = review([source], list(canonical.values()))
        self.assertEqual(report["counts"]["no_unique_cdb_metadata_candidate"], 1)
        self.assertEqual(report["research_null_cells_not_authorized"], 0)

    def test_two_sources_to_same_cdb_target_quarantine(self):
        source, _, canonical = sample()
        other = dict(source, match_id="SYNTH002")
        report = review([source, other], list(canonical.values()))
        self.assertEqual(report["counts"]["metadata_reused_cdb_target_groups_quarantined"], 1)
        self.assertEqual(report["research_null_cells_not_authorized"], 0)

    def test_score_conflict_not_new_null_value(self):
        source, _, canonical = sample()
        canonical["synthetic-cdb-1"]["stats_json"] = '{"p1_set1_games":5}'
        report = review([source], list(canonical.values()))
        self.assertEqual(report["counts"]["metadata_set_score_absent_or_conflict"], 1)
        self.assertEqual(report["research_null_cells_not_authorized"], 0)


if __name__ == "__main__":
    unittest.main()
