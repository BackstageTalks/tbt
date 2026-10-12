import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_tml_event_witnesses import triage


def h(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def context(**v):
    d = {
        "source_namespace": "tml-atp-2024",
        "source_native_event_key": ["tournament-match", "2024-7", "14"],
        "candidate_canonical_match_id": "m1",
        "independent_event_id_attested": False,
        "score_attested": True,
        "import_ready": False, "write_authorized": False,
    }
    return {**d, **v}


def witness(**v):
    d = {
        "schema": 1, "kind": "independent_original_event_witness",
        "from_tml_source": False, "provider_namespace": "verified-other",
        "provider_event_id": "event-14",
        "source_namespace": "tml-atp-2024",
        "source_native_event_key": ["tournament-match", "2024-7", "14"],
        "canonical_match_id": "m1",
        "independent_original_sha256": "a" * 64,
        "write_authorized": False,
    }
    return {**d, **v}


class Tests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.c = self.root / "context.jsonl"
        self.w = self.root / "witnesses.jsonl"
        self.out = self.root / "output"
        self.store([context()], [witness()])

    def store(self, contexts, witnesses):
        self.c.write_text("".join(json.dumps(x) + "\n" for x in contexts))
        self.w.write_text("".join(json.dumps(x) + "\n" for x in witnesses))

    def run_gate(self):
        return triage(self.c, h(self.c), self.w, h(self.w), self.out)

    def output(self):
        return [json.loads(x) for x in
                (self.out / "independent-event-witness-review-private.jsonl").read_text().splitlines()]

    def test_witness_review_never_approves_import(self):
        report = self.run_gate()
        self.assertEqual(report["counts"]["source_event_with_independent_witness_for_review"], 1)
        self.assertFalse(report["cdb_mutated"])
        self.assertEqual(report["ready_for_cdb_write"], 0)
        self.assertEqual(report["provider_api_requests"], 0)
        self.assertFalse(self.output()[0]["independent_provider_event_id_attested"])
        self.assertFalse(self.output()[0]["import_ready"])
        self.assertFalse(self.output()[0]["write_authorized"])

    def test_no_witness_blocks_without_throwing(self):
        self.store([context()], [])
        self.assertEqual(self.run_gate()["counts"]["without_independent_event_witness"], 1)
        self.assertEqual(self.output(), [])

    def test_different_canonical_match_blocks(self):
        self.store([context()], [witness(canonical_match_id="m2")])
        self.assertEqual(self.run_gate()["counts"]["canonical_target_conflict"], 1)

    def test_ambiguous_duplicate_original_witness_blocks(self):
        self.store([context()], [witness(), witness(provider_event_id="event-99")])
        self.assertEqual(self.run_gate()["counts"]["ambiguous_event_witness"], 1)

    def test_same_provider_event_reused_across_canonical_matches_is_ambiguous(self):
        first = witness()
        second = witness(
            source_native_event_key=["tournament-match", "2024-7", "15"],
            canonical_match_id="m2")
        self.store([context()], [first, second])
        self.assertEqual(self.run_gate()["counts"]["ambiguous_provider_event_reuse"], 1)
        self.assertEqual(self.output(), [])

    def test_without_score_corroboration_blocks(self):
        self.store([context(score_attested=False)], [witness()])
        self.assertEqual(self.run_gate()["counts"]["no_independent_full_score_corroboration"], 1)

    def test_preauthorized_witness_fails_closed(self):
        self.store([context()], [witness(write_authorized=True)])
        with self.assertRaisesRegex(ValueError, "preauthorized"):
            self.run_gate()

    def test_preauthorized_context_fails_closed(self):
        self.store([context(import_ready=True)], [witness()])
        with self.assertRaisesRegex(ValueError, "preapproved"):
            self.run_gate()

    def test_sha_mismatch_blocks(self):
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            triage(self.c, "f" * 64, self.w, h(self.w), self.out)

    def test_duplicate_source_context_fails_closed(self):
        self.store([context(), context()], [witness()])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.run_gate()


if __name__ == "__main__":
    unittest.main()
