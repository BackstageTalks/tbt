import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from audit_source_identity_gaps import audit


class IdentityGapsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.obs=self.root/"observations.jsonl.gz"
        self.links=self.root/"crosswalk.jsonl"
        self.out=self.root/"out"
        proof={"tour":"atp","source":"BlinQ verified CDB plus Wikidata CC0",
               "evidence":"official_atp_identifier_unique_registry_full_name_and_nonconflicting_cdb",
               "wikidata_qid":"Q333","atp_tour_id":"A1","canonical_player_id":"canonical1"}
        self.links.write_text(json.dumps(proof)+"\n")
        self.sha=hashlib.sha256(self.links.read_bytes()).hexdigest()

    def item(self,left="A1",right="B2",status="SOURCE_UNLINKED_ORIGINAL_IDS_PRESENT"):
        return {"schema":1,"source_namespace":"tml-atp-2024",
                "canonical_match_id":None,"write_authorized":False,"import_ready":False,
                "source_winner_id":left,"source_loser_id":right,"linkage_status":status,
                "source_stats_nonempty":{"w_ace":"5","w_df":"1","l_ace":"2"},
                "raw_columns":{"winner_name":"Example One","loser_name":"Example Two"}}

    def save(self,rows):
        with gzip.open(self.obs,"wt",encoding="utf-8") as f:
            for r in rows: f.write(json.dumps(r)+"\n")

    def test_prioritizes_missing_other_side_exact_id(self):
        self.save([self.item(),self.item("A1","B2"),self.item("C3","D4")])
        r=audit(self.obs,self.links,self.sha,self.out)
        self.assertEqual(r["rows_checked"],3)
        self.assertEqual(r["source_row_identity_coverage"]["exactly_one_player_id_has_independent_crosswalk"],2)
        self.assertEqual(r["source_player_id_gaps"],3)
        priority=[json.loads(x) for x in (self.out/"identity-crosswalk-priority-private.jsonl").read_text().splitlines()]
        self.assertEqual(priority[0]["source_player_id"],"B2")
        self.assertEqual(priority[0]["rows_with_other_id_verified"],2)
        self.assertEqual(r["ready_for_canonical_write"],0)

    def test_quarantined_does_not_become_priority(self):
        self.save([self.item(status="QUARANTINE_AMBIGUOUS_NATIVE_EVENT_KEY")])
        r=audit(self.obs,self.links,self.sha,self.out)
        self.assertEqual(r["source_player_id_gaps"],0)
        self.assertEqual(r["source_row_identity_coverage"]["rows_quarantined_or_missing_event_key"],1)

    def test_canonical_match_mapping_or_write_claim_fails(self):
        i=self.item()
        i["canonical_match_id"]="some-match"
        self.save([i])
        with self.assertRaisesRegex(ValueError,"Untrusted"):
            audit(self.obs,self.links,self.sha,self.out)
        i["canonical_match_id"]=None;i["write_authorized"]=True
        self.save([i])
        with self.assertRaisesRegex(ValueError,"Untrusted"):
            audit(self.obs,self.links,self.sha,self.out)

    def test_wrong_namespace_not_mixed_and_pinned_sha_enforced(self):
        self.save([self.item()])
        with self.assertRaisesRegex(ValueError,"SHA"):
            audit(self.obs,self.links,"0"*64,self.out)
        i=self.item();i["source_namespace"]="non-ATP-other-provider"
        self.save([i])
        with self.assertRaisesRegex(ValueError,"Unexpected ID namespace"):
            audit(self.obs,self.links,self.sha,self.out)


if __name__=="__main__":
    unittest.main()
