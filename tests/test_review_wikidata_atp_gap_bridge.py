import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_wikidata_atp_gap_bridge import build


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gap(sid, alias="Player One"):
    return {
        "source_player_id": sid, "source_display_aliases_review_only": [alias],
        "review_only": True, "canonical_player_id": None,
        "evidence_required": "independent_official_ATP_ID_to_canonical_player",
        "rows_with_other_id_verified": 20, "priority_score": 120,
    }


def link(code="AB12", qid="Q123", cid="canonical-one", name="Player One"):
    return {
        "schema": 1, "source": "Wikidata", "license": "CC0-1.0",
        "tour": "atp", "evidence": "unique_exact_name_both_sides_plus_tour_specific_id",
        "wikidata_qid": qid, "player_id": cid, "canonical_name": name,
        "external_ids": {"atp": [code]},
    }


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.gaps = self.root / "gaps.jsonl"
        self.links = self.root / "links.jsonl.gz"
        self.out = self.root / "private"
        self.write([gap("AB12")], [link()])

    def write(self, gaps, links):
        self.gaps.write_text("".join(json.dumps(x) + "\n" for x in gaps))
        with gzip.open(self.links, "wt") as f:
            for x in links:
                f.write(json.dumps(x) + "\n")

    def run_build(self):
        return build(self.gaps, sha(self.gaps), self.links, sha(self.links), self.out)

    def proposals(self):
        return [json.loads(line) for line in
                (self.out / "atp-gap-cc0-review-private.jsonl").read_text().splitlines()]

    def test_unique_official_id_is_only_a_research_candidate(self):
        report = self.run_build()
        self.assertEqual(report["counts"]["existing_cc0_evidence_review_candidates"], 1)
        row = self.proposals()[0]
        self.assertEqual(row["source_atp_player_id"], "AB12")
        self.assertEqual(row["candidate_canonical_player_id"], "canonical-one")
        self.assertEqual(row["wikidata_qid"], "Q123")
        self.assertIsNone(row["canonical_match_id"])
        self.assertFalse(row["import_ready"])
        self.assertFalse(row["write_authorized"])
        self.assertFalse(report["event_identity_attested"])
        self.assertFalse(report["canonical_source_snapshot_reverified"])
        self.assertEqual(report["ready_for_cdb_write"], 0)
        self.assertEqual(report["sports_api_requests"], 0)
        self.assertEqual(report["cdb_writes"], 0)
        self.assertEqual(report["private_proposals_sha256"],
                         sha(self.out / "atp-gap-cc0-review-private.jsonl"))

    def test_same_code_multiple_qids_quarantined(self):
        self.write([gap("AB12")], [link(), link(qid="Q444", cid="canonical-two")])
        self.assertEqual(self.run_build()["counts"]["ambiguous_atp_id"], 1)
        self.assertEqual(self.proposals(), [])

    def test_one_qid_multiple_atp_codes_quarantined(self):
        self.write([gap("AB12")], [link(), link(code="EF34")])
        self.assertEqual(self.run_build()["counts"]["ambiguous_qid_or_canonical_owner"], 1)
        self.assertEqual(self.proposals(), [])

    def test_one_canonical_player_multiple_qids_quarantined(self):
        self.write([gap("AB12")], [link(), link(code="ZZ99", qid="Q777")])
        self.assertEqual(self.run_build()["counts"]["ambiguous_qid_or_canonical_owner"], 1)
        self.assertEqual(self.proposals(), [])

    def test_names_are_only_corroboration_not_weak_identity_promotion(self):
        self.write([gap("AB12", "Different Player")], [link()])
        self.assertEqual(self.run_build()["counts"]["name_disagreement_requires_manual_review"], 1)
        self.assertEqual(self.proposals(), [])

    def test_name_owner_collision_is_not_promoted(self):
        self.write([gap("AB12")],
                   [link(), link(code="EF34", qid="Q444",
                                 cid="canonical-two", name="Player One")])
        self.assertEqual(self.run_build()["counts"]["ambiguous_canonical_name_owners"], 1)
        self.assertEqual(self.proposals(), [])

    def test_missing_official_id_produces_zero(self):
        self.write([gap("AB12")], [link(code="EF34")])
        self.assertEqual(self.run_build()["counts"]["no_existing_cc0_canonical_reference"], 1)
        self.assertEqual(self.proposals(), [])

    def test_duplicate_source_ids_fail_closed(self):
        self.write([gap("AB12"), gap("ab12")], [link()])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.run_build()

    def test_preauthorized_source_is_not_accepted(self):
        row = gap("AB12")
        row["write_authorized"] = True
        row["canonical_player_id"] = "canonical-one"
        self.write([row], [link()])
        with self.assertRaisesRegex(ValueError, "authorized"):
            self.run_build()

    def test_sha_mismatch_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            build(self.gaps, "f" * 64, self.links, sha(self.links), self.out)
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            build(self.gaps, sha(self.gaps), self.links, "f" * 64, self.out)

    def test_invalid_profiles_are_not_promoted(self):
        bad = link()
        bad["evidence"] = "same_name_only"
        self.write([gap("AB12")], [bad])
        self.assertEqual(self.run_build()["counts"]["no_existing_cc0_canonical_reference"], 1)
        self.assertEqual(self.proposals(), [])

    def test_rank_by_unlocked_partner_rows(self):
        self.write([gap("EF34", "Player Two"), gap("AB12")],
                   [link(code="EF34", qid="Q444", cid="canonical-two", name="Player Two"),
                    link()])
        self.run_build()
        self.assertEqual(len(self.proposals()), 2)


if __name__ == "__main__":
    unittest.main()
