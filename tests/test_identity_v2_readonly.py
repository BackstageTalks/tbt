"""Isolation tests for research-only identity candidate discovery (not CDB writes)."""
import unittest

from scripts.research import identity_v2 as m


def player(name, native="1", namespace="source", tour="atp", aliases=(), dob="", country=""):
    return m.Player(namespace, tour, native, name, tuple(aliases), dob, country)


def event(names, ids=("1","2"), namespace="source", tour="atp",
          when="2026-01-01", when_kind="played", venue="Australian Open",
          round_name="R16", score="6-4 7-6(4)", winner="1",
          discipline="singles", draw="main", event_id="match"):
    p1=player(names[0],ids[0],namespace,tour)
    p2=player(names[1],ids[1],namespace,tour)
    return m.Event(namespace, event_id,tour,discipline,(p1,p2),
                   when,when_kind,venue,round_name,score,winner,draw=draw)


class Names(unittest.TestCase):
    def test_alias_initials_and_particles(self):
        examples=(
            ("Djokovic N.","Novak Djokovic"),
            ("N. Djokovic","Novak Djokovic"),
            ("DJOKOVIC, NOVAK","Novak Djokovic"),
            ("DJOKOVIC NOVAK","Novak Djokovic"),
            ("Auger-Aliassime F.","Félix Auger-Aliassime"),
            ("De Minaur A.","Alex de Minaur"),
            ("Van De Zandschulp B.","Botic van de Zandschulp"),
            ("Etcheverry T. M.","Tomás Martín Etcheverry"),
            ("Cerundolo J. M.","Juan Manuel Cerundolo"),
            ("Tsonga J. W.","Jo-Wilfried Tsonga"),
            ("Bautista Agut R.","Roberto Bautista Agut"),
        )
        for a,b in examples:
            with self.subTest(a=a):
                matches=m.discover_players(player(a),[player(b,namespace="canonical")])
                self.assertEqual(len(matches),1,(a,b,m.name_keys(a),m.name_keys(b)))
                self.assertFalse(matches[0].identity_verified)
                self.assertFalse(matches[0].cdb_write_authorized)

    def test_exact_and_spelling_cleanup(self):
        self.assertEqual(m.exact_name_key("Łukasz  Kubot"),"lukasz kubot")
        self.assertEqual(m.exact_name_key("Novak   Đoković"),"novak dokovic")
        self.assertEqual(m.exact_name_key("MÃ¡rton Fucsovics"),"marton fucsovics")
        self.assertEqual(m.exact_name_key("Новак Джокович"),"novak dzhokovich")
        self.assertIn("exact:coco gauff",player("Cori Gauff",aliases=("Coco Gauff",)).names())

    def test_cyrillic_transliteration_is_research_only(self):
        src=player("Новак Джокович",namespace="championat")
        target=player("Novak Djokovic",namespace="cdb")
        found=m.discover_players(src,[target])
        self.assertEqual(len(found),1)
        self.assertIn("transliteration_research_only",found[0].evidence)
        self.assertTrue(m.no_write_contract(found))

    def test_short_name_collisions_not_verified(self):
        src=player("Zhang R.",native="z")
        dests=[player("Rui Zhang",namespace="cdb",native="1"),
               player("Rong Zhang",namespace="cdb",native="2")]
        candidates=m.discover_players(src,dests)
        self.assertEqual(len(candidates),2)
        self.assertTrue(m.no_write_contract(candidates))

    def test_scoped_id_and_tour_protection(self):
        self.assertNotEqual(m.scoped_id("tML","atp","123"),m.scoped_id("provider","atp","123"))
        self.assertNotEqual(m.scoped_id("tML","atp","123"),m.scoped_id("tML","wta","123"))
        with self.assertRaises(ValueError):
            m.scoped_id("","atp","123")
        self.assertEqual(m.discover_players(player("Novak Djokovic"),[
            player("Novak Djokovic",tour="wta",namespace="cdb")]),[])

    def test_dob_conflict_is_hard_negative(self):
        self.assertFalse(m.discover_players(player("Novak Djokovic",dob="1987-05-22"),
            [player("Novak Djokovic",namespace="cdb",dob="1986-05-22")]))
        self.assertFalse(m.discover_players(player("Alpha Bravo",dob="2000-01-01"),
            [player("Unrelated Player",namespace="cdb",dob="2000-01-01",country="USA")]))

    def test_exact_same_source_scoped_id_still_no_write(self):
        matches=m.discover_players(player("N Djokovic"),[player("N. Djokovic")])
        self.assertEqual(len(matches),1)
        self.assertIn("same_native_identity",matches[0].evidence)
        self.assertTrue(m.no_write_contract(matches))


class TournamentAndScore(unittest.TestCase):
    def test_rounds_and_qualification_not_equated(self):
        self.assertEqual(m.normalize_round("Semifinal"),"sf")
        self.assertEqual(m.normalize_round("Round of 16"),"r16")
        self.assertEqual(m.normalize_round("Q2"),"q2")
        self.assertNotEqual(m.normalize_round("R2"),m.normalize_round("Q2"))

    def test_scores(self):
        regular=m.parse_score("6-4 7-6(4)")
        self.assertTrue(regular.valid)
        self.assertEqual(regular.sets,((6,4),(7,6)))
        short=m.parse_score("4-3 4-3 4-3")
        self.assertTrue(short.valid)
        self.assertEqual(len(short.sets),3)
        ret=m.parse_score("6-4 3-2 RET")
        self.assertTrue(ret.valid)
        self.assertIn("ret",ret.status)
        self.assertFalse(m.parse_score("weird unknown").valid)

    def test_reject_wrong_date_semantics(self):
        with self.assertRaises(ValueError):
            event(("A Player","B Player"),when_kind="maybe")


class Events(unittest.TestCase):
    def setUp(self):
        self.src=event(("Djokovic N.","Sinner J."),namespace="src",when="2026-01-01",
                       when_kind="tournament_start",round_name="R16",score="6-4 7-6(4)")
        self.cdb=event(("Novak Djokovic","Jannik Sinner"),namespace="cdb",
                       when="2026-01-13",round_name="Round of 16",score="6-4 7-6(4)")

    def test_candidates_not_verified(self):
        got=m.discover_events(self.src,[self.cdb])
        self.assertEqual(len(got),1)
        self.assertIn("tournament_start_window",got[0].evidence)
        self.assertIn("round",got[0].evidence)
        self.assertTrue(m.no_write_contract(got))

    def test_opponent_orientation_and_score(self):
        swapped=event(("Jannik Sinner","Novak Djokovic"),namespace="cdb",
                      when="2026-01-13",round_name="R16",score="4-6 6-7(4)",winner="2")
        self.assertEqual(len(m.discover_events(self.src,[swapped])),1)

    def test_event_edition_strength_never_identity_attestation(self):
        same=m.discover_events(self.src,[self.cdb])
        self.assertEqual(len(same),1)
        self.assertEqual(same[0].context_tier,"edition_context_strong")
        unknown=m.Event(**{**self.cdb.__dict__,"tournament":"Another Open"})
        broad=m.discover_events(self.src,[unknown])
        self.assertEqual(len(broad),1)
        self.assertEqual(broad[0].context_tier,"unresolved_event_edition")
        self.assertIn("tournament_edition_unresolved",broad[0].evidence)
        self.assertTrue(m.no_write_contract(broad+same))

    def test_missing_or_invalid_date_cannot_create_event_match(self):
        # Previous loose branch could match two undated events by name.
        for source_date,target_date in (("", ""), ("", "2026-01-13"),
                                        ("2026-01-01", ""),
                                        ("2026-13-90", "2026-01-13")):
            with self.subTest(source_date=source_date,target_date=target_date):
                src=m.Event(**{**self.src.__dict__, "event_date":source_date})
                dest=m.Event(**{**self.cdb.__dict__,"event_date":target_date})
                self.assertEqual(m.discover_events(src,[dest]),[])

    def test_date_window_reject(self):
        distant=event(("Novak Djokovic","Jannik Sinner"),namespace="cdb",
                      when="2026-03-02")
        self.assertFalse(m.discover_events(self.src,[distant]))

    def test_draw_round_discipline_must_not_conflate(self):
        base=("Novak Djokovic","Jannik Sinner")
        for options in (dict(draw="qual"),
                        dict(round_name="Q2"),dict(tour="wta")):
            with self.subTest(options=options):
                self.assertFalse(m.discover_events(self.src,[event(
                    base,namespace="cdb",when="2026-01-13",**options)]))

    def test_doubles_need_explicit_four_player_team_schema(self):
        with self.assertRaises(ValueError):
            event(("Novak Djokovic","Jannik Sinner"),discipline="doubles")

    def test_missing_round_allows_research_discovery(self):
        q=event(("Novak Djokovic","Jannik Sinner"),namespace="cdb",
                when="2026-01-13",round_name="")
        self.assertEqual(len(m.discover_events(self.src,[q])),1)

    def test_result_conflict_rejects(self):
        bad=event(("Novak Djokovic","Jannik Sinner"),namespace="cdb",
                  when="2026-01-13",score="6-1 6-0")
        self.assertFalse(m.discover_events(self.src,[bad]))

    def test_cross_provider_winner_orientation_conflict_rejected(self):
        opposite=event(("Novak Djokovic","Jannik Sinner"),namespace="cdb",
                       when="2026-01-13",winner="2")
        self.assertFalse(m.discover_events(self.src,[opposite]))

    def test_retirement_not_equated_with_complete_score(self):
        partial=event(("Novak Djokovic","Jannik Sinner"),namespace="cdb",
                      when="2026-01-13",score="6-4 3-2 RET")
        self.assertFalse(m.discover_events(self.src,[partial]))

    def test_reject_source_namespace_player_mismatch(self):
        src=event(("Djokovic N.","Sinner J."),namespace="src")
        other=m.Player("provider", "atp", "1", "Djokovic N.")
        with self.assertRaises(ValueError):
            m.Event(**{**src.__dict__,"players":(other,src.players[1])})

    def test_same_namespace_different_native_ids_rejected(self):
        bad=event(("Novak Djokovic","Jannik Sinner"),ids=("100","200"),namespace="src",
                  when="2026-01-13")
        self.assertFalse(m.discover_events(self.src,[bad]))

    def test_candidate_conflicts_with_duplicate_targets_remain_research(self):
        q=event(("Novak Djokovic","Jannik Sinner"),namespace="cdb",when="2026-01-13")
        r=m.Event(**{**q.__dict__,"event_id":"another"})
        got=m.discover_events(self.src,[q,r])
        self.assertEqual(len(got),2)
        self.assertTrue(m.no_write_contract(got))




class Shadow(unittest.TestCase):
    def test_broader_discovery_without_false_import_claim(self):
        from scripts.research import shadow_identity_v2 as sh
        src=event(("Djokovic N.","Sinner J."),namespace="sackmann",
                  when="2026-01-05",when_kind="tournament_start")
        target=event(("Novak Djokovic","Jannik Sinner"),namespace="cdb",
                     when="2026-01-18")
        result=sh.comparison([src],[target])
        self.assertEqual(result["counts"]["old_any"],0)
        self.assertEqual(result["counts"]["new_any"],1)
        self.assertEqual(result["counts"]["new_only_any"],1)
        self.assertEqual(result["CDB_writes"],0)
        self.assertEqual(result["independently_verified_event_links"],0)

    def test_pinned_jsonl_input_contract(self):
        from scripts.research import shadow_identity_v2 as sh
        import tempfile
        from pathlib import Path
        import json
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"source.jsonl"
            d={
                "namespace":"sackmann","event_id":"src-event-1",
                "tour":"atp","discipline":"singles",
                "players":[
                    {"namespace":"sackmann","native_id":"a","name":"Djokovic N."},
                    {"namespace":"sackmann","native_id":"b","name":"Sinner J."}],
                "date_kind":"tournament_start","event_date":"2026-01-05",
                "tournament":"Australian Open","round_name":"R16"
            }
            path.write_text(json.dumps(d)+"\n",encoding="utf-8")
            rows=sh.read_events(path,max_rows=5)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0].event_id,"src-event-1")
            self.assertEqual(len(sh.sha(path)),64)

    def test_duplicate_event_candidates_not_auto_accepted(self):
        from scripts.research import shadow_identity_v2 as sh
        src=event(("Djokovic N.","Sinner J."),namespace="src",
                  when="2026-01-01",when_kind="tournament_start")
        cdb=event(("Novak Djokovic","Jannik Sinner"),namespace="cdb",
                  when="2026-01-13",event_id="one")
        other=m.Event(**{**cdb.__dict__,"event_id":"two"})
        result=sh.comparison([src],[cdb,other])
        self.assertEqual(result["counts"]["new_ambiguous"],1)
        self.assertEqual(result["independently_verified_event_links"],0)

class AdapterContract(unittest.TestCase):
    def test_sackmann_source_native_event_no_cdb_write(self):
        from scripts.research import identity_v2_adapters as a
        row={"tourney_date":"20250105","winner_id":"p1","loser_id":"p2",
             "winner_name":"Djokovic N.","loser_name":"Sinner J.",
             "tourney_name":"Australian Open","round":"R16","score":"6-4 6-4"}
        r=a.from_sackmann(row,tour="atp",collection="tour",
                          file_sha256="f"*64,line_number=12)
        self.assertIsNotNone(r.event)
        self.assertEqual(r.event.date_kind,"tournament_start")
        self.assertFalse(r.cdb_import_authorized)
        self.assertTrue(a.require_source_only(r).research_only)

    def test_sackmann_same_ids_fail_closed(self):
        from scripts.research import identity_v2_adapters as a
        row={"tourney_date":"20250105","winner_id":"p1","loser_id":"p1",
             "winner_name":"Name One","loser_name":"Name Two"}
        r=a.from_sackmann(row,tour="atp",collection="tour",
                          file_sha256="f"*64,line_number=2)
        self.assertIsNone(r.event)
        self.assertIn("source_player_id_collision",r.reasons)

    def test_season_requires_native_player_ids(self):
        from scripts.research import identity_v2_adapters as a
        row={"date":"2025-01-05","home":"Djokovic N.","away":"Sinner J."}
        r=a.from_season(row,tour="atp",collection="2025",
                        file_sha256="f"*64,line_number=2)
        self.assertIsNone(r.event)
        self.assertIn("incomplete_source_native_event",r.reasons)

    def test_cdb_is_context_only(self):
        from scripts.research import identity_v2_adapters as a
        row={"tour":"atp","match_id":"cdb1","scheduled_at":"2025-01-06T16:00:00Z",
             "player1_id":"c1","player2_id":"c2","player1_name":"Novak Djokovic",
             "player2_name":"Jannik Sinner","winner_id":"c1"}
        r=a.from_cdb_metadata(row)
        self.assertIsNotNone(r.event)
        self.assertFalse(r.cdb_import_authorized)
        self.assertEqual(r.event.date_kind,"scheduled")

    def test_true_zero_not_null_invalid_values_are_quarantined(self):
        from scripts.research import identity_v2_adapters as a
        self.assertEqual(a.parse_nonnegative_int(0),0)
        self.assertIsNone(a.parse_nonnegative_int(""))
        self.assertIsNone(a.parse_nonnegative_int(None))
        self.assertEqual(a.parse_nonnegative_int("007"),7)
        for x in (True,-1,1.5,"3.5","50%","Inf"):
            with self.subTest(x=x), self.assertRaises(ValueError):
                a.parse_nonnegative_int(x)


class SourcePreflight(unittest.TestCase):
    def test_sha_pinned_sackmann_csv_preflight(self):
        from scripts.research import identity_v2_stage as stage
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import hashlib
        with TemporaryDirectory() as folder:
            path=Path(folder)/"input.csv"
            path.write_text(
                "tourney_date,winner_id,loser_id,winner_name,loser_name,tourney_name,round\n"
                "20250105,p1,p2,Djokovic N.,Sinner J.,Australian Open,R16\n"
                "20250105,p1,p1,Same,Player,Australian Open,R32\n",encoding="utf-8")
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            result=stage.stage_readonly(path,expected_sha=digest,
                                        kind="sackmann",fmt="csv",
                                        tour="atp",collection="main")
            self.assertEqual(result["counts"]["input_rows"],2)
            self.assertEqual(result["counts"]["source_only_normalized_events"],1)
            self.assertEqual(result["counts"]["quarantine_rows"],1)
            self.assertFalse(result["cdb_import_authorized"])
            self.assertEqual(result["cdb_writes"],0)

    def test_sha_gate_must_precede_parsing(self):
        from scripts.research import identity_v2_stage as stage
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            path=Path(folder)/"input.csv"
            path.write_text("invalid",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"SOURCE_SHA_GATE_FAILED"):
                stage.stage_readonly(path,expected_sha="0"*64,
                    kind="sackmann",fmt="csv",tour="atp",collection="main")


if __name__=="__main__":
    unittest.main()
