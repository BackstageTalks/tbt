import json, pathlib,sys,tempfile,unittest
from collections import Counter
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(ROOT/"api"))
from build_charting_observations import classify,write_gzip,records,day
from tbt.data.charting_observations import ChartingObservations

class SourceOnlyObservationsTest(unittest.TestCase):
    def setUp(self):
        self.event={"tour":"wta","date":"20250812","players":["Gabriella Mikaul","Olivia Gadecki"],
                    "surface":"Hard","tournament":"ITF Saskatoon","round":"R32"}
        self.row={"match_id":"20250812-W-Saskatoon-R32-Mikaul-Gadecki",
                  "player":"Olivia Gadecki","opponent":"Gabriella Mikaul",
                  "date":"20250812","surface":"hard"}
    def classify_row(self,row=None,owners=None,invalid=None):
        row=row or self.row
        return classify("wta",row,{row["match_id"]:self.event},invalid or set(),
                        owners or Counter({(row["match_id"],row["player"]):1}))[0]
    def test_consistent_source_native_not_approved_for_canonical(self):
        self.assertEqual(self.classify_row(),[])
        self.assertEqual(day("2025-08-12"),"20250812")
    def test_date_conflict_quarantined(self):
        self.assertIn("DATE_CONFLICT",self.classify_row(dict(self.row,date="20250813")))
    def test_competitor_conflict_quarantined(self):
        self.assertIn("PLAYER_PAIR_CONFLICT",self.classify_row(dict(self.row,opponent="Different Player")))
    def test_duplicate_quarantined(self):
        self.assertIn("DUPLICATE_SOURCE_PLAYER_ROW",self.classify_row(
            owners=Counter({(self.row["match_id"],self.row["player"]):2})))
    def test_upstream_invalid_quarantined(self):
        self.assertIn("SOURCE_PREFLIGHT_QUARANTINE",self.classify_row(
            invalid={self.row["match_id"]}))
    def test_unmatched_quarantined(self):
        self.assertIn("MISSING_SOURCE_EVENT",classify(
            "wta",self.row,{},set(),Counter({(self.row["match_id"],self.row["player"]):1}))[0])
    def test_deterministic_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)
            self.assertEqual(write_gzip(p/"one.gz",[{"x":"2"}])["sha256"],
                             write_gzip(p/"two.gz",[{"x":"2"}])["sha256"])
    def test_checksum_reader_maintains_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            m={"schema":1,"namespace":"charting_observations/v1",
               "canonical_history_partitions_modified":False,
               "canonical_statistics_changed":False,
               "canonical_event_join_approved":False,
               "training_model_eligible":False,"assets":{}}
            for tour in ("atp","wta"):
                name=f"charting-observations-{tour}-v1.jsonl.gz"
                item={"schema":1,"tour":tour,"source_match_id":"ABC-XYZ",
                      "observation_scope":"charted_point_sample_unknown_completeness",
                      "source_fields_nonempty":{"servebasics_total_pts":"29"},
                      "canonical_match_id":None,"canonical_write_allowed":False,
                      "whole_match_stats_eligible":False,
                      "prediction_training_allowed":False,
                      "independent_provider_event_identity":False}
                info=write_gzip(root/name,[item])
                m["assets"][tour]={"name":name,"rows":1,**info}
            (root/"charting-observations-manifest-v1.json").write_text(json.dumps(m))
            c=ChartingObservations(root)
            out=c.observations("ABC-XYZ",tour="wta")
            self.assertEqual(len(out),1)
            self.assertEqual(out[0]["source_fields_nonempty"]["servebasics_total_pts"],"29")
            self.assertIsNone(out[0]["canonical_match_id"])
            self.assertEqual(c.observations("NONEXISTENT",tour="atp"),[])
            with self.assertRaises(ValueError):c.observations("../history-2025",tour="atp")
            (root/"charting-observations-wta-v1.jsonl.gz").write_bytes(b"tampered")
            with self.assertRaises(ValueError):ChartingObservations(root)
    def test_reject_promoted_source_rows(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            m={"schema":1,"namespace":"charting_observations/v1",
               "canonical_history_partitions_modified":False,"canonical_statistics_changed":False,
               "canonical_event_join_approved":False,"training_model_eligible":False,"assets":{}}
            for tour in ("atp","wta"):
                name=f"charting-observations-{tour}-v1.jsonl.gz"
                row={"schema":1,"tour":tour,"source_match_id":"ABC",
                     "canonical_match_id":"bad-canonical","canonical_write_allowed":False,
                     "prediction_training_allowed":False,"whole_match_stats_eligible":False,
                     "independent_provider_event_identity":False,
                     "observation_scope":"charted_point_sample_unknown_completeness"}
                m["assets"][tour]={"name":name,"rows":1,**write_gzip(root/name,[row])}
            (root/"charting-observations-manifest-v1.json").write_text(json.dumps(m))
            with self.assertRaises(ValueError):ChartingObservations(root).observations("ABC",tour="atp")

if __name__=="__main__":unittest.main()
