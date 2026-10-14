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
                      when="2026-01-13",round_name="R16",score="4-6 6-7(4)")
        self.assertEqual(len(m.discover_events(self.src,[swapped])),1)

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


if __name__=="__main__":
    unittest.main()
