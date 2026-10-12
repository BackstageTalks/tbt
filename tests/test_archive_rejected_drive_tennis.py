import csv
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import archive_rejected_drive_tennis as a

class RejectedSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.out=self.root/"private"
        self.atp=self.root/a.SOURCES["atp"][0]
        self.wta=self.root/a.SOURCES["wta"][0]
        self.rows=[[ "ATP Event","2024-10-02","ATP Tour","Outdoor","Hard","Final","3",
            "Player A","Player B","Player B","-1","42","-1","1000","-1.0","1.8","6-3 3-6 4-6"],
            [ "ATP Event","2024-10-03","ATP Tour","Outdoor","Hard","Semifinals","3",
            "Player A","Player C","Player A","20","41","1000","999","1.9","2.1","6-4 6-4"],
            [ "ATP Event","2024-10-04","ATP Tour","Outdoor","Hard","Semifinals","3",
            "Player A","Player C","Player A","20","41","1000","999","1.9","2.1","6-4 RET"]]
        with self.atp.open("w",encoding="utf-8",newline="") as f:
            w=csv.writer(f);w.writerow(a.FIELDS_ATP);w.writerows(self.rows)
        self.xlsx_lines=[",".join(a.FIELDS_WTA),
            "WTA Event,2023-06-03,Outdoor,Grass,Final,3,Player C,Player D,Player C,25,41,100,200,1.8,2.2,6-3 6-4",
            "WTA Event,2023-06-04,Outdoor,Grass,Final,3,Player C,Player E,Player E,25,41,100,200,1.8,2.2,6-3 6-4",
            "WTA Event,2023-06-05,Outdoor,Grass,Final,3,Player C,Player E,Player C,25,41,100,200,1.8,2.2,6-2 RET"]
        self.xlsx_fixture(self.xlsx_lines)

    def xlsx_fixture(self,lines,style="inline"):
        from xml.sax.saxutils import escape
        def c(i,v):
            if style=="inline":
                return f'<c r="A{i}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
            return f'<c r="A{i}" t="s"><v>{i-1}</v></c>'
        sheet="<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>"+''.join(
           f'<row r="{i}">{c(i,v)}</row>' for i,v in enumerate(lines,start=1)
        )+"</sheetData></worksheet>"
        wb='<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>'
        rel='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
        with ZipFile(self.wta,"w") as z:
            z.writestr("xl/workbook.xml",wb)
            z.writestr("xl/_rels/workbook.xml.rels",rel)
            z.writestr("xl/worksheets/sheet1.xml",sheet)
            if style=="shared":
                val='<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'+''.join(
                  f'<si><t>{escape(s)}</t></si>' for s in lines)+'</sst>'
                z.writestr("xl/sharedStrings.xml",val)

    def records(self):
        with gzip.open(self.out/"rejected-source-observations.jsonl.gz","rt",encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    def test_preserves_both_sources_and_no_canonical_id_guess(self):
        r=a.build(self.root,self.out)
        self.assertEqual(r["source_rows"],6)
        self.assertEqual(r["canonical_cells_written"],0)
        self.assertEqual(r["accepted_source_matches_eligible_for_cdb"],0)
        for x in self.records():
            self.assertIsNone(x["canonical_match_id"])
            self.assertFalse(x["canonical_write_authorized"])
            self.assertIsNone(x["quote_observed_at"])
            self.assertFalse(x["model_use_authorized"])

    def test_valid_score_and_no_placeholder_rank_or_odds(self):
        a.build(self.root,self.out)
        row=self.records()[0]
        self.assertEqual(row["status"],"RESEARCH_ONLY_NO_INDEPENDENT_EVENT_PLAYER_IDS")
        self.assertIsNone(row["source_rank1_observed"])
        self.assertIsNone(row["source_odd1_observed"])
        self.assertEqual(row["winner_source_side"],2)
        self.assertTrue(row["score_completed_verified"])

    def test_winner_conflict_and_retirement_quarantined(self):
        r=a.build(self.root,self.out)
        self.assertGreaterEqual(r["status_counts"].get("QUARANTINE_SCORE_OR_FINISH_NOT_PROVEN",0),3)
        self.assertEqual(len(self.records()),6)

    def test_malformed_wta_line_preserved_as_quarantine(self):
        self.xlsx_fixture(self.xlsx_lines+["Wrong,Number,Of,Fields"])
        a.build(self.root,self.out)
        rows=self.records()
        self.assertEqual(rows[-1]["status"],"QUARANTINE_CSV_COLUMN_SHAPE")
        self.assertEqual(rows[-1]["source_values_raw"],["Wrong","Number","Of","Fields"])

    def test_two_column_indexed_xlsx_with_blank_index_header(self):
        from xml.sax.saxutils import escape
        wb='<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>'
        rel='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
        rows=[]
        for idx,val in enumerate(self.xlsx_lines,start=1):
            index="" if idx==1 else str(idx-2)
            rows.append(f'<row r="{idx}"><c r="A{idx}" t="inlineStr"><is><t>{index}</t></is></c><c r="B{idx}" t="inlineStr"><is><t>{escape(val)}</t></is></c></row>')
        sheet='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(rows)+'</sheetData></worksheet>'
        with ZipFile(self.wta,"w") as z:
            z.writestr("xl/workbook.xml",wb)
            z.writestr("xl/_rels/workbook.xml.rels",rel)
            z.writestr("xl/worksheets/sheet1.xml",sheet)
        r=a.build(self.root,self.out)
        self.assertEqual(r["by_tour"]["wta"]["rows"],3)

    def test_shared_strings_xlsx_supported(self):
        self.xlsx_fixture(self.xlsx_lines,style="shared")
        r=a.build(self.root,self.out)
        self.assertEqual(r["source_rows"],6)

    def test_source_digest_drift_changes_readback_not_canonical(self):
        a.build(self.root,self.out)
        sha=a._sha(self.atp)
        with self.atp.open("a") as f:f.write("extra,partial\n")
        a.build(self.root,self.out)
        self.assertNotEqual(sha,a._sha(self.atp))
        self.assertEqual(self.records()[-1]["source_tour"],"wta")
        self.assertEqual(self.records()[3]["status"],"QUARANTINE_CSV_COLUMN_SHAPE")

    def test_score_orientation_correctness(self):
        self.assertTrue(a._valid_score("6-3 3-6 4-6",2,3))
        self.assertFalse(a._valid_score("6-3 3-6 4-6",1,3))
        self.assertTrue(a._valid_score("7-6(5) 6-4",1,3))
        self.assertFalse(a._valid_score("6-4 RET",1,3))

    def test_missing_source_file_blocks_all(self):
        self.wta.unlink()
        with self.assertRaisesRegex(ValueError,"Missing/unsafe"):
            a.build(self.root,self.out)
        self.assertFalse(self.out.exists())

    def test_github_release_sanitized_wta_filename_is_strictly_restored(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/blinq-rejected-drive-evidence-once.yml").read_text()
        self.assertIn("gh_name='WTA.Tennis.2007.-.2026.Daily.update.xlsx'", workflow)
        self.assertIn("original='WTA Tennis 2007 - 2026 Daily update.xlsx'", workflow)
        self.assertIn('mv -- "$gh_name" "$original"', workflow)
        self.assertIn('test -f "$original"', workflow)
        self.assertIn("sha256sum -c SHA256SUMS", workflow)
        self.assertIn("duplicate original and GitHub-normalized WTA assets", workflow)
        self.assertNotIn("schedule:", workflow)

if __name__=="__main__":unittest.main()
