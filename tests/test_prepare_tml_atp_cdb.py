import csv, hashlib, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import prepare_tml_atp_cdb as tml

class TmlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d=Path(self.tmp.name)
        self.h=["tourney_id","tourney_name","tourney_date","match_num",
            "winner_id","loser_id","winner_name","loser_name","surface",
            "round","best_of",*tml.STATS]
        self.row=dict.fromkeys(self.h,"")
        self.row.update(tourney_id="2024-123",tourney_name="Open",
            tourney_date="20240101",match_num="1",
            winner_id="AB12",loser_id="CD34",winner_name="Player A",
            loser_name="Player B",surface="Hard",round="F",best_of="3")
        for side in ("w","l"):
            for k,n in {"ace":5,"df":2,"svpt":80,"1stIn":50,"1stWon":34,
                        "2ndWon":17,"SvGms":12,"bpSaved":2,"bpFaced":3}.items():
                self.row[side+"_"+k]=str(n)
    def save(self,rows):
        path=self.d/"2024.csv"
        with path.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=self.h);w.writeheader();w.writerows(rows)
        return path,tml.blob_sha1(path.read_bytes())
    def test_valid_original_pinned_and_atomic_counter(self):
        p,sha=self.save([self.row])
        with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
            clean,headers,counts,raw_sha=tml.select_source(p,2024)
        self.assertEqual(counts["source_native_valid"],1)
        self.assertEqual(len(clean),1)
        self.assertEqual(len(raw_sha),64)
    def test_wrong_blob_sha_is_rejected(self):
        p,_=self.save([self.row])
        with self.assertRaisesRegex(ValueError,"SHA mismatch"):
            tml.select_source(p,2024)
    def test_missing_source_key_rejected(self):
        self.row["match_num"]=""
        p,sha=self.save([self.row])
        with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
            clean,_,counts,_=tml.select_source(p,2024)
        self.assertFalse(clean)
        self.assertEqual(counts["quarantine_missing_original_identity"],1)
    def test_winner_and_loser_official_id_cannot_collide(self):
        self.row["loser_id"]=self.row["winner_id"]
        p,sha=self.save([self.row])
        with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
            clean,_,counts,_=tml.select_source(p,2024)
        self.assertFalse(clean)
        self.assertEqual(counts["quarantine_missing_original_identity"],1)
    def test_first_won_greater_than_first_in_is_quarantined(self):
        self.row["w_1stWon"]="80"
        p,sha=self.save([self.row])
        with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
            clean,_,counts,_=tml.select_source(p,2024)
        self.assertFalse(clean)
        self.assertEqual(counts["quarantine_impossible_service_counts"],1)
    def test_duplicate_source_event_key_quarantined(self):
        p,sha=self.save([self.row,self.row])
        with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
            clean,_,counts,_=tml.select_source(p,2024)
        self.assertEqual(len(clean),1)
        self.assertEqual(counts["quarantine_duplicate_tournament_match_key"],1)
    def test_partial_csv_row_quarantined(self):
        p,sha=self.save([self.row])
        with p.open("a",encoding="utf-8") as f:f.write("bad,partial\n")
        sha=tml.blob_sha1(p.read_bytes())
        with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
            clean,_,counts,_=tml.select_source(p,2024)
        self.assertEqual(len(clean),1)
        self.assertEqual(counts["quarantine_csv_shape"],1)
    def crosswalk(self,rows):
        p=self.d/"verified.jsonl"
        p.write_text("".join(json.dumps(x)+"\n" for x in rows))
        return p,hashlib.sha256(p.read_bytes()).hexdigest()
    def witness(self,atp="AB12",cid="canonical-1"):
        return {"tour":"atp","source":"BlinQ verified CDB plus Wikidata CC0",
            "evidence":"official_atp_identifier_unique_registry_full_name_and_nonconflicting_cdb",
            "wikidata_qid":"Q123","atp_tour_id":atp,"canonical_player_id":cid}
    def test_official_atp_ids_only_from_independent_witness(self):
        p,sha=self.crosswalk([self.witness(),self.witness("CD34","canonical-2")])
        links,c=tml.verified_links(p,sha)
        self.assertEqual(links,{"AB12":"canonical-1","CD34":"canonical-2"})
        self.assertEqual(c["verified_links"],2)
    def test_crosswalk_rejects_sha_drift(self):
        p,_=self.crosswalk([self.witness()])
        with self.assertRaisesRegex(ValueError,"SHA-256 mismatch"):
            tml.verified_links(p,"0"*64)
    def test_ambiguous_atp_id_is_blocked(self):
        p,sha=self.crosswalk([self.witness("AB12","one"),self.witness("AB12","two")])
        links,c=tml.verified_links(p,sha)
        self.assertFalse(links)
        self.assertEqual(c["ambiguous_source_ids"],1)
    def test_two_official_ids_cannot_share_canonical_id(self):
        p,sha=self.crosswalk([self.witness("AB12","same"),self.witness("CD34","same")])
        links,c=tml.verified_links(p,sha)
        self.assertFalse(links)
        self.assertEqual(c["canonical_id_collisions"],2)
    def test_reader_uses_no_name_mapping(self):
        text=Path(tml.__file__).read_text()
        self.assertNotIn("difflib",text)
        self.assertNotIn("SequenceMatcher",text)
        self.assertIn("row[\"winner_id\"] not in links",text)

if __name__=="__main__":unittest.main()
