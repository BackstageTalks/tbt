import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_tml_native_history_id import history_id, probe


def row(**more):
    x = {
        "tour": "atp", "source_namespace": "tml-atp-2024",
        "source_native_event_key": ["tournament-match", "2024-33", "17"],
        "source_tourney_id": "2024-33", "source_match_num": "17",
        "source_round": "Quarterfinal",
        "linkage_status": "SOURCE_UNLINKED_ORIGINAL_IDS_PRESENT",
        "raw_columns": {
            "winner_name": "Carlos Alcaraz", "loser_name": "Alex de Minaur",
            "tourney_id": "2024-33", "match_num": "17"},
        "canonical_match_id": None, "import_ready": False,
        "write_authorized": False,
    }
    return {**x, **more}


def candidate(mid, **extra):
    data = {
        "source_namespace": "tml-atp-2024",
        "source_native_event_key": ["tournament-match", "2024-33", "17"],
        "candidate_canonical_match_id": mid,
        "independent_event_id_attested": False,
        "candidate_new_null_fields": None,
        "import_ready": False, "write_authorized": False,
    }
    return {**data, **extra}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestHistoricalNativeHash(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.source = self.root / "obs.jsonl.gz"
        self.candidates = self.root / "context.jsonl"
        self.out = self.root / "report"
        self.id = history_id(row())
        self.store([row()], [candidate(self.id)])

    def store(self, observations, candidates):
        with gzip.open(self.source, "wt") as f:
            for item in observations:
                f.write(json.dumps(item) + "\n")
        self.candidates.write_text("".join(json.dumps(x)+"\n" for x in candidates))

    def audit(self):
        return probe(self.source, sha(self.source),
                     self.candidates, sha(self.candidates), self.out)

    def test_exact_hash_only_yields_readonly_lineage(self):
        report = self.audit()
        self.assertTrue(self.id.startswith("hist-js:atp:"))
        self.assertEqual(report["counts"]["equal_deterministic_history_id_review_only"], 1)
        self.assertEqual(report["ready_for_cdb_write"], 0)
        self.assertEqual(report["cdb_writes"], 0)
        data = [json.loads(x) for x in
                (self.out/"native-history-fingerprint-private.jsonl").read_text().splitlines()]
        self.assertFalse(data[0]["independent_event_id_attested"])
        self.assertFalse(data[0]["canonical_provider_provenance_verified"])
        self.assertFalse(data[0]["write_authorized"])

    def test_exact_name_order_invariant_for_source_winner_loser(self):
        swap = row(raw_columns={
            "winner_name": "Alex de Minaur",
            "loser_name": "Carlos Alcaraz", "tourney_id": "2024-33",
            "match_num": "17"})
        self.assertEqual(history_id(row()), history_id(swap))

    def test_alias_round_matches_historical_importer(self):
        self.assertEqual(history_id(row()), history_id(row(source_round="QF")))

    def test_different_canonical_id_keeps_new_cells_blocked(self):
        self.store([row()], [candidate("provider-abc")])
        report = self.audit()
        self.assertEqual(report["counts"]["historical_native_id_not_equal"], 1)
        self.assertEqual(report["ready_for_cdb_write"], 0)

    def test_missing_exact_source_key_fails_review(self):
        self.store([row(source_match_num="999")], [candidate(self.id)])
        self.assertEqual(self.audit()["counts"]["history_fingerprint_unavailable"], 1)

    def test_ambiguous_original_duplicate_quarantined(self):
        self.store([row(), row()], [candidate(self.id)])
        self.assertEqual(self.audit()["counts"]["missing_or_ambiguous_original"], 1)

    def test_unauthorized_source_fails_closed(self):
        self.store([row(import_ready=True)], [candidate(self.id)])
        with self.assertRaisesRegex(ValueError, "authorization"):
            self.audit()

    def test_preauthorized_context_fails_closed(self):
        self.store([row()], [candidate(self.id, write_authorized=True)])
        with self.assertRaisesRegex(ValueError, "Unsafe review"):
            self.audit()

    def test_sha_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            probe(self.source, "b"*64,
                  self.candidates, sha(self.candidates), self.out)

    def test_duplicate_source_key_context_fails_closed(self):
        self.store([row()], [candidate(self.id), candidate(self.id)])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.audit()


if __name__ == "__main__":
    unittest.main()
