import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from build_source_evidence_lake import build, sha256_file


class SourceEvidenceLakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root/"inputs"
        self.src.mkdir()
        self.out = self.root/"private-release"
        self.manifest = self.root/"manifest.json"
        self.header = ("tourney_id","match_num","tourney_date","round","winner_id",
                       "loser_id","winner_name","loser_name","w_ace","l_ace","w_df","l_df")
        self.example = dict(tourney_id="2025-7",match_num="4",tourney_date="20250101",
                            round="F",winner_id="100",loser_id="200",
                            winner_name="Player, A",loser_name="Player B",
                            w_ace="0",l_ace="2",w_df="1",l_df="0")

    def save(self, records, *, namespace="tml-atp-2025", profile="atp-wta-sackmann",
             source="2025.csv", columns=None):
        path = self.src/source
        with path.open("w",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=self.header)
            writer.writeheader()
            writer.writerows(records)
        spec = {"filename":source,"namespace":namespace,"profile":profile,
                "source_ref":"https://example.org/pinned/source/2025.csv",
                "sha256":sha256_file(path),"tour":"atp",
                "source_rights_status":"review_needed"}
        if columns is not None:
            spec["columns"]=columns
        self.manifest.write_text(json.dumps({"schema":1,"sources":[spec]}))
        return spec

    def read_output(self):
        with gzip.open(self.out/"source-observations.jsonl.gz","rt",encoding="utf-8") as f:
            return [json.loads(v) for v in f if v.strip()]

    def test_original_ids_unlinked_not_importable(self):
        self.save([self.example])
        result=build(self.manifest,self.src,self.out)
        self.assertEqual(result["source_rows_retained"],1)
        row=self.read_output()[0]
        self.assertEqual(row["linkage_status"],"SOURCE_UNLINKED_ORIGINAL_IDS_PRESENT")
        self.assertIsNone(row["canonical_match_id"])
        self.assertFalse(row["write_authorized"])
        self.assertFalse(row["import_ready"])
        self.assertEqual(row["source_stats_nonempty"]["w_ace"],"0")

    def test_ambiguous_event_key_quarantines_all_members(self):
        a,b=dict(self.example),dict(self.example)
        b.update(winner_id="999",loser_id="333",w_ace="20")
        self.save([a,b])
        result=build(self.manifest,self.src,self.out)
        self.assertEqual(result["status_counts"]["QUARANTINE_AMBIGUOUS_NATIVE_EVENT_KEY"],2)
        self.assertEqual(len(self.read_output()),2)

    def test_missing_match_num_retained(self):
        a=dict(self.example);a["match_num"]=""
        self.save([a])
        result=build(self.manifest,self.src,self.out)
        self.assertEqual(result["source_rows_retained"],1)
        self.assertEqual(self.read_output()[0]["linkage_status"],"SOURCE_UNLINKED_INCOMPLETE_NATIVE_IDENTITY")

    def test_missing_one_player_id_preserved_not_linked(self):
        a=dict(self.example);a["winner_id"]=""
        self.save([a])
        build(self.manifest,self.src,self.out)
        self.assertFalse(self.read_output()[0]["two_original_player_ids"])
        self.assertEqual(self.read_output()[0]["linkage_status"],"SOURCE_UNLINKED_INCOMPLETE_NATIVE_IDENTITY")

    def test_malformed_row_kept_quarantined(self):
        self.save([self.example])
        with (self.src/"2025.csv").open("a",encoding="utf-8") as f:
            f.write("short,row\n")
        m=json.loads(self.manifest.read_text())
        m["sources"][0]["sha256"]=sha256_file(self.src/"2025.csv")
        self.manifest.write_text(json.dumps(m))
        out=build(self.manifest,self.src,self.out)
        self.assertEqual(out["source_rows_retained"],2)
        self.assertEqual(self.read_output()[1]["linkage_status"],"QUARANTINE_MALFORMED_CSV_ROW")

    def test_source_sha_change_fails_before_creating_evidence(self):
        self.save([self.example])
        (self.src/"2025.csv").write_text("tampered")
        with self.assertRaisesRegex(ValueError,"SHA-256 mismatch"):
            build(self.manifest,self.src,self.out)
        self.assertFalse((self.out/"source-observations.jsonl.gz").exists())

    def test_explicit_header_typo_fails_closed(self):
        self.save([self.example],columns={"event_id":"does_not_exist"})
        with self.assertRaisesRegex(ValueError,"Specified identity column"):
            build(self.manifest,self.src,self.out)

    def test_csv_quotes_names_preserved_privately(self):
        self.save([self.example])
        build(self.manifest,self.src,self.out)
        self.assertEqual(self.read_output()[0]["raw_columns"]["winner_name"],"Player, A")

    def test_gzip_bytes_reproducible(self):
        self.save([self.example])
        build(self.manifest,self.src,self.out)
        digest=sha256_file(self.out/"source-observations.jsonl.gz")
        build(self.manifest,self.src,self.out)
        self.assertEqual(digest,sha256_file(self.out/"source-observations.jsonl.gz"))
        self.assertEqual(digest,json.loads((self.out/"report.json").read_text())["observations_sha256"])

    def test_missing_canonical_fields_never_assumed_new(self):
        self.save([self.example])
        data=build(self.manifest,self.src,self.out)
        self.assertEqual(data["canonical_cells_written"],0)
        self.assertFalse(data["canonical_write_authorized"])
        self.assertEqual(data["sport_api_requests"],0)

    def test_path_traversal_denied(self):
        self.save([self.example])
        m=json.loads(self.manifest.read_text())
        m["sources"][0]["filename"]="../2025.csv"
        self.manifest.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,"Unpinned/unsupported"):
            build(self.manifest,self.src,self.out)

    def test_repeated_namespace_blocked(self):
        spec=self.save([self.example])
        m={"schema":1,"sources":[spec,dict(spec)]}
        self.manifest.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,"repeated"):
            build(self.manifest,self.src,self.out)


if __name__=="__main__":
    unittest.main()
