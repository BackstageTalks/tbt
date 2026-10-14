"""Local-only gated reviewer case export (synthetic fixture data only)."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from scripts.research import identity_v2 as ident
from scripts.research import identity_v2_triage as triage
from scripts.research.identity_v2_private_review import PrivateReviewPack


def synthetic_source():
    return ident.Event("src","native-row-1","atp","singles",
                       (ident.Player("src","atp","11","Djokovic N."),
                        ident.Player("src","atp","12","Sinner J.")),
                       "2025-01-01","tournament_start","Australian Open",
                       "R16","6-4 6-4","11")


def synthetic_target(identifier="cdb-one"):
    return ident.Event("cdb",identifier,"atp","singles",
                       (ident.Player("cdb","atp","p1","Novak Djokovic"),
                        ident.Player("cdb","atp","p2","Jannik Sinner")),
                       "2025-01-12","scheduled","Australian Open","R16")


class PrivateReviewExport(unittest.TestCase):
    def _pack(self):
        source=synthetic_source()
        old=[synthetic_target()]
        new=[ident.EventCandidate("cdb-one",("alias","round")),
             ident.EventCandidate("cdb-two",("alias","round"))]
        review=triage.review_case(source,old,new)
        p=PrivateReviewPack(max_items=5)
        p.consider("atp/main",source,old,new,review)
        self.assertEqual(len(p.selected),1)
        return p

    def test_ci_guard_blocks_raw_review_export(self):
        p=self._pack()
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ,{"CI":"true"},clear=False):
                with self.assertRaisesRegex(PermissionError,"forbidden in CI"):
                    p.write_private(Path(directory)/"private.jsonl")
            self.assertFalse((Path(directory)/"private.jsonl").exists())

    def test_local_export_requires_explicit_private_parent_and_exclusive_file(self):
        p=self._pack()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"private.jsonl"
            with patch.dict(os.environ,{"CI":"","GITHUB_ACTIONS":""},clear=False):
                r=p.write_private(path)
                self.assertTrue(path.exists())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
                self.assertEqual(len(r["sha256"]),64)
                self.assertFalse(r["cdb_import_authorized"])
                self.assertNotIn("Djokovic",json.dumps(r))
                content=[json.loads(line) for line in path.read_text().splitlines()]
                self.assertEqual(len(content),2)
                self.assertEqual(content[1]["review_bucket"],
                                 "old_unique_became_ambiguous")
                self.assertFalse(content[1]["cdb_import_authorized"])
                with self.assertRaises(FileExistsError):
                    p.write_private(path)

    def test_public_parent_and_non_jsonl_refused(self):
        p=self._pack()
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/"review.jsonl"
            os.chmod(directory,0o755)
            with patch.dict(os.environ,{"CI":"","GITHUB_ACTIONS":""},clear=False):
                with self.assertRaisesRegex(PermissionError,"mode 0700"):
                    p.write_private(output)
                with self.assertRaisesRegex(ValueError,".jsonl"):
                    p.write_private(Path(directory)/"review.txt")

    def test_only_disagreement_cases_included(self):
        p=PrivateReviewPack(max_items=5)
        src=synthetic_source()
        old=[synthetic_target()]
        new=[ident.EventCandidate("cdb-one",("source_alias",),
                                 context_tier="edition_context_strong")]
        p.consider("atp/main",src,old,new,triage.review_case(src,old,new))
        self.assertEqual(p.selected,[])

    def test_selection_ranks_highest_risk_first(self):
        p=PrivateReviewPack(max_items=1)
        src=synthetic_source()
        weak=[ident.EventCandidate("new-one",("names",))]
        p.consider("wta/itf",src,[],weak,triage.review_case(src,[],weak))
        regression=[ident.EventCandidate("cdb-one",("names",)),
                    ident.EventCandidate("cdb-two",("names",))]
        old=[synthetic_target()]
        p.consider("atp/futures",src,old,regression,
                   triage.review_case(src,old,regression))
        self.assertEqual(len(p.selected),1)
        self.assertEqual(p.selected[0]["review_bucket"],
                         "old_unique_became_ambiguous")


if __name__=="__main__":
    unittest.main()
