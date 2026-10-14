"""Unified identity research gateway regression tests; no canonical writes."""
import unittest
from scripts.research import identity_v2_gateway as gate
from scripts.research import identity_v2 as idv2
from scripts.research import shadow_identity_v2 as legacy

SHA="a"*64


def row(names=("Djokovic N.","Sinner J."), *, namespace="src", when="2025-01-01",
        kind="tournament_start", winner="p1", tournament="Australian Open",
        round_name="R16", eid="one"):
    return idv2.Event(namespace,eid,"atp","singles",
          (idv2.Player(namespace,"atp","p1",names[0]),
           idv2.Player(namespace,"atp","p2",names[1])),
          when,kind,tournament,round_name,"",winner)


class ResearchGateway(unittest.TestCase):
    def test_sackmann_adapter_preserves_original_native_scope(self):
        raw={"tourney_date":"20250101", "tourney_id":"2025-1111",
             "winner_id":"p1","winner_name":"Djokovic N.",
             "loser_id":"p2","loser_name":"Sinner J.",
             "tourney_name":"Australian Open","round":"R16"}
        staged=gate.stage_sackmann(raw,tour="atp",collection="tour",
                                   source_file_sha256=SHA,line_number=4)
        self.assertIsNotNone(staged.event)
        self.assertEqual(staged.event.edition_id,"2025-1111")
        self.assertTrue(staged.research_only)
        self.assertFalse(staged.cdb_import_authorized)

    def test_season_adapter_rejects_missing_source_player_ids(self):
        raw={"match_id":"123","date":"2025-01-01",
             "home":"Djokovic N.","away":"Sinner J."}
        staged=gate.stage_season(raw,tour="atp",collection="2025",
                    source_file_sha256=SHA,line_number=2)
        self.assertIsNone(staged.event)
        self.assertIn("incomplete_source_native_event",staged.reasons)

    def test_native_source_field_map_preserves_real_provider_ids(self):
        row={"match_no":"native:event:42","h_id":"player-17",
             "a_id":"player-29","h_name":"A. Player","a_name":"B. Player",
             "played":"2025-01-14","tour_name":"Example Event",
             "stage":"Q2","won":"player-29","edition":"event:2025"}
        fields={"event_id":"match_no","player1_id":"h_id",
                "player2_id":"a_id","player1_name":"h_name",
                "player2_name":"a_name","match_day":"played",
                "tournament":"tour_name","round":"stage",
                "winner_id":"won","edition_id":"edition"}
        r=gate.stage_native(row,source_name="externalfeed",tour="atp",
                            collection="native2025",source_file_sha256=SHA,
                            line_number=2,field_map=fields)
        self.assertIsNotNone(r.event)
        self.assertEqual(r.event.event_id,"native:event:42")
        self.assertEqual(r.event.winner_native_id,"player-29")
        self.assertEqual(r.event.round_name,"Q2")
        self.assertFalse(r.cdb_import_authorized)

    def test_native_source_missing_provider_event_id_quarantined(self):
        row={"player1_id":"a1","player1_name":"A. Player",
             "player2_id":"a2","player2_name":"B. Player",
             "match_day":"2025-01-14"}
        r=gate.stage_native(row,source_name="charting",tour="atp",
                            collection="2025",source_file_sha256=SHA,
                            line_number=3)
        self.assertIsNone(r.event)
        self.assertIn("missing_official_source_native_event_id",r.reasons)

    def test_native_source_missing_original_player_ids_quarantined(self):
        row={"event_id":"native123","player1_name":"A. Player",
             "player2_name":"B. Player","match_day":"2025-01-14"}
        r=gate.stage_native(row,source_name="livetennisapi",tour="wta",
                            collection="2025",source_file_sha256=SHA,
                            line_number=5)
        self.assertIsNone(r.event)
        self.assertIn("incomplete_source_native_event",r.reasons)

    def test_native_field_map_refuses_unknown_columns(self):
        with self.assertRaises(ValueError):
            gate.stage_native({},source_name="pbp",tour="atp",
                 collection="2025",source_file_sha256=SHA,line_number=2,
                 field_map={"canonical_match_id":"unsafe"})

    def test_native_sha_pinned_stage_csv_quarantines_unidentified_rows(self):
        from scripts.research import identity_v2_stage as stage
        from hashlib import sha256
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            path=Path(folder)/"native.csv"
            path.write_text(
                "event_id,player1_id,player2_id,player1_name,player2_name,match_day,tournament,round\n"
                "provider-m1,p1,p2,Player One,Player Two,2025-01-03,Sample,R16\n"
                ",p3,p4,Player Three,Player Four,2025-01-03,Sample,R16\n",
                encoding="utf-8")
            digest=sha256(path.read_bytes()).hexdigest()
            out=stage.stage_readonly(path,expected_sha=digest,
                kind="native",fmt="csv",tour="atp",
                collection="2025",source_name="official-atp")
            self.assertEqual(out["counts"]["source_only_normalized_events"],1)
            self.assertEqual(out["counts"]["quarantine_rows"],1)
            self.assertEqual(out["counts"][
                "blocked_missing_official_source_native_event_id"],1)
            self.assertFalse(out["cdb_import_authorized"])
            self.assertEqual(out["cdb_writes"],0)

    def test_canonical_context_can_only_be_read(self):
        raw={"match_id":"cdb-1","tour":"atp",
             "player1_id":"c1","player1_name":"Novak Djokovic",
             "player2_id":"c2","player2_name":"Jannik Sinner",
             "scheduled_at":"2025-01-10T10:00:00+00:00"}
        staged=gate.stage_canonical_context(raw)
        self.assertIsNotNone(staged.event)
        self.assertFalse(staged.cdb_import_authorized)

    def test_unique_strong_context_still_no_write(self):
        s=row()
        c=row(("Novak Djokovic","Jannik Sinner"),
              namespace="CDB",when="2025-01-10",kind="scheduled")
        result=gate.discover(s,[c])
        self.assertEqual(result.state,"research_unique_strong_context")
        self.assertEqual(len(result.candidates),1)
        self.assertFalse(result.identity_verified)
        self.assertFalse(result.cdb_write_authorized)

    def test_repeated_futures_pair_remains_ambiguous(self):
        s=row()
        c1=row(("Novak Djokovic","Jannik Sinner"),namespace="CDB",
              when="2025-01-10",kind="scheduled",eid="one")
        c2=row(("Novak Djokovic","Jannik Sinner"),namespace="CDB",
              when="2025-01-15",kind="scheduled",eid="two")
        result=gate.discover(s,[c1,c2])
        self.assertEqual(result.state,"research_ambiguous_quarantined")
        self.assertEqual(len(result.candidates),2)
        self.assertIn("multiple_possible_canonical_events",result.blockers)

    def test_overflow_is_not_misclassified_as_zero_candidate(self):
        s=row()
        c=[row(namespace="CDB",when="2025-01-10",kind="scheduled",
               eid=str(x)) for x in range(5)]
        result=gate.discover(s,c,max_context_rows=3)
        self.assertEqual(result.state,"source_context_overflow_quarantined")
        with self.assertRaisesRegex(ValueError,"overflow"):
            gate.compare_baseline(s,c,legacy.proxy_old_match,max_context_rows=3)

    def test_duplicate_cdb_context_ref_is_rejected(self):
        s=row()
        c=row(namespace="CDB",when="2025-01-10",kind="scheduled")
        with self.assertRaisesRegex(ValueError,"Duplicate canonical"):
            gate.discover(s,[c,c])

    def test_baseline_comparison_does_not_promote(self):
        s=row()
        c=row(("Novak Djokovic","Jannik Sinner"),namespace="CDB",
              when="2025-01-10",kind="scheduled")
        result,review=gate.compare_baseline(s,[c],legacy.proxy_old_match)
        self.assertEqual(result.state,"research_unique_strong_context")
        self.assertEqual(review.bucket,"new_only_unique_strong_context")
        self.assertFalse(review.cdb_write_authorized)

    def test_no_date_does_not_match_names(self):
        s=row(when="")
        c=row(namespace="CDB",when="",kind="unknown")
        self.assertEqual(gate.discover(s,[c]).state,"no_research_match")


if __name__=="__main__":
    unittest.main()
