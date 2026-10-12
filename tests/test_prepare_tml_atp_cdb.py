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
            "round","best_of","score",*tml.STATS]
        self.row=dict.fromkeys(self.h,"")
        self.row.update(tourney_id="2024-123",tourney_name="Open",
            tourney_date="20240101",match_num="1",
            winner_id="AB12",loser_id="CD34",winner_name="Player A",
            loser_name="Player B",surface="Hard",round="F",best_of="3",score="6-4 6-4")
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
        self.assertEqual(len(clean),0)
        self.assertEqual(counts["quarantine_duplicate_tournament_match_key"],2)
    def test_conflicting_duplicate_keys_quarantine_all_members(self):
        altered=dict(self.row)
        altered["winner_id"]="EF56"
        altered["w_ace"]="10"
        p,sha=self.save([self.row,altered])
        with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
            clean,_,counts,_=tml.select_source(p,2024)
        self.assertEqual(clean,[])
        self.assertEqual(counts["quarantine_duplicate_tournament_match_key"],2)
        self.assertEqual(counts.get("source_native_valid",0),0)

    def test_different_match_numbers_stay_distinct(self):
        second=dict(self.row, match_num="2")
        p,sha=self.save([self.row,second])
        with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
            clean,_,counts,_=tml.select_source(p,2024)
        self.assertEqual(len(clean),2)
        self.assertEqual(counts.get("quarantine_duplicate_tournament_match_key",0),0)

    def test_impossible_aces_and_second_serve_double_faults_quarantined(self):
        for field,value in (("w_ace","70"),("w_df","40")):
            altered=dict(self.row)
            altered[field]=value
            p,sha=self.save([altered])
            with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
                clean,_,counts,_=tml.select_source(p,2024)
            self.assertFalse(clean,field)
            self.assertEqual(counts["quarantine_impossible_service_counts"],1)

    def test_invalid_calendar_day_cannot_enter_source_stage(self):
        self.row["tourney_date"]="20240230"
        p,sha=self.save([self.row])
        with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
            clean,_,counts,_=tml.select_source(p,2024)
        self.assertFalse(clean)
        self.assertEqual(counts["quarantine_missing_original_identity"],1)

    def test_postmatch_completion_guard_blocks_retired_and_partial(self):
        for score in ("6-4 2-3 RET", "6-4 W/O", "6-4 6-4 DEF",
                      "6-4 3-2", "6-4 4-6", "", "6-4 6-4 0-6",
                      "6-4 4-6 4-6", "6-4 2-6 [10-7]"):
            altered=dict(self.row,score=score)
            p,sha=self.save([altered])
            with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
                clean,_,counts,_=tml.select_source(p,2024)
            self.assertEqual(clean,[],score)
            self.assertEqual(counts["quarantine_incomplete_or_invalid_final_score"],1,score)

    def test_valid_tiebreak_and_three_winning_sets_remain_usable(self):
        for score,best_of in (("7-6(4) 6-2","3"),
                              ("6-4 4-6 6-2","3"),
                              ("6-4 4-6 6-3 5-7 7-6(3)","5")):
            altered=dict(self.row,score=score,best_of=best_of)
            p,sha=self.save([altered])
            with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
                clean,_,counts,_=tml.select_source(p,2024)
            self.assertEqual(len(clean),1,score)
            self.assertEqual(counts["source_native_valid"],1,score)

    def test_inconsistent_best_of_blocks_whole_match_rates(self):
        altered=dict(self.row,score="6-4 6-4",best_of="5")
        p,sha=self.save([altered])
        with patch.dict(tml.YEAR_BLOBS,{2024:sha}):
            clean,_,counts,_=tml.select_source(p,2024)
        self.assertEqual(clean,[])
        self.assertEqual(counts["quarantine_incomplete_or_invalid_final_score"],1)

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


    def test_opt_in_2007_is_sha_pinned_source_only_and_never_cdb_ready(self):
        self.row.update(tourney_id="2007-123",tourney_date="20070101")
        p,sha=self.save([self.row])
        p.rename(self.d/"2007.csv")
        with patch.dict(tml.OPTIONAL_YEAR_BLOBS,{2007:sha}):
            report=tml.audit_all_pinned_sources(self.d,self.d/"out",years=[2007])
        self.assertEqual(report["status"],"PINNED_SOURCE_ONLY_NO_CDB_ACCESS")
        self.assertEqual(report["per_year"]["2007"]["source_native_valid"],1)
        self.assertIsNone(report["per_year"]["2007"]["new_verified_cdb_null_cells"])
        self.assertFalse(report["canonical_mutated"])
        self.assertEqual(report["cdb_imported"],0)

    def test_2026_upload_filename_alias_must_match_original_git_blob(self):
        self.row.update(tourney_id="2026-123",tourney_date="20260101")
        p,sha=self.save([self.row])
        p.rename(self.d/"2026(1).csv")
        with patch.dict(tml.OPTIONAL_YEAR_BLOBS,{2026:sha}):
            report=tml.audit_all_pinned_sources(self.d,self.d/"out",years=[2026])
        self.assertEqual(report["per_year"]["2026"]["file"],"2026(1).csv")
        self.assertEqual(report["per_year"]["2026"]["source_native_valid"],1)
        self.assertEqual(report["independent_cdb_readback"],"NOT_RUN")

    def test_unsupported_year_cannot_bypass_original_sha_pin(self):
        with self.assertRaisesRegex(ValueError,"Unpinned"):
            tml.audit_all_pinned_sources(self.d,self.d/"out",years=[2006])

    def test_opt_in_raw_sha_mismatch_fails_closed(self):
        self.row.update(tourney_id="2007-123",tourney_date="20070101")
        p,sha=self.save([self.row])
        p.rename(self.d/"2007.csv")
        with self.assertRaisesRegex(ValueError,"SHA mismatch"):
            tml.audit_all_pinned_sources(self.d,self.d/"out",years=[2007])

    def test_protected_writer_year_scope_unchanged(self):
        self.assertEqual(sorted(tml.YEAR_BLOBS),[2022,2023,2024,2025])
        self.assertEqual(len(tml.OPTIONAL_YEAR_BLOBS),36)


    def test_complete_1987_score_only_remains_research_and_no_invented_stats(self):
        row=dict(self.row)
        row.update(tourney_id="1987-123",tourney_date="19870101",
                   match_num="1",score="6-4 6-4")
        for col in tml.STATS:
            row[col]=""
        p,sha=self.save([row])
        p.rename(self.d/"1987.csv")
        with patch.dict(tml.OPTIONAL_YEAR_BLOBS,{1987:sha}):
            result=tml.audit_all_pinned_sources(self.d,self.d/"audit",years=[1987])
        one=result["per_year"]["1987"]
        self.assertEqual(one["source_native_valid"],0)
        self.assertEqual(one["source_score_only_valid_unique"],1)
        self.assertIsNone(one["safe_new_cdb_cells"])
        self.assertEqual(result["cdb_imported"],0)

    def test_score_only_synthetic_event_key_collision_is_not_usable(self):
        row=dict(self.row)
        row.update(tourney_id="1987-123",tourney_date="19870101",score="6-4 6-4")
        for col in tml.STATS:
            row[col]=""
        p,sha=self.save([row,row])
        p.rename(self.d/"1987.csv")
        with patch.dict(tml.OPTIONAL_YEAR_BLOBS,{1987:sha}):
            result=tml.audit_all_pinned_sources(self.d,self.d/"audit",years=[1987])
        self.assertEqual(result["per_year"]["1987"]["source_score_only_valid_unique"],0)
        self.assertEqual(result["per_year"]["1987"]["raw_rows_not_in_p0_or_p1"],2)

if __name__=="__main__":unittest.main()
