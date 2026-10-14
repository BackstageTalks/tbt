"""Negative-control and collision tests for the research-only edition registry."""
import unittest

from scripts.research.identity_v2_editions import (
    EditionRecord, ResearchEditionRegistry, no_write_contract
)

SRC = "a" * 64


def edition(namespace, native, key, *, name="Australian Open", aliases=(),
            year=2025, tour="atp", draw="main", discipline="singles",
            level="grand_slam", sha=SRC, reference="source:official-register"):
    return EditionRecord(namespace, native, tour, year, draw, discipline,
                         level, key, name, sha, tuple(aliases), reference)


class EditionResearch(unittest.TestCase):
    def test_source_adapter_keeps_edition_id_without_granting_identity(self):
        from scripts.research import identity_v2_adapters as adapter
        row={"tourney_id":"2025-aus-open","tourney_date":"20250105",
             "winner_id":"123","loser_id":"456",
             "winner_name":"Djokovic N.","loser_name":"Sinner J.",
             "tourney_name":"Australian Open","round":"R16"}
        adapted=adapter.from_sackmann(row,tour="atp",collection="main",
                                      file_sha256="f"*64,line_number=8)
        self.assertIsNotNone(adapted.event)
        self.assertEqual(adapted.event.edition_id,"2025-aus-open")
        self.assertFalse(adapted.cdb_import_authorized)
        self.assertFalse(adapted.research_only is False)

    def test_identical_research_edition_does_not_verify_identity(self):
        a=edition("sackmann","2025-aus-open","ao-2025")
        b=edition("cdb-research","ao-2025","ao-2025",aliases=("AO Melbourne",))
        registry=ResearchEditionRegistry([a,b])
        self.assertEqual(registry.compare(a,b),"same_research_edition_proposal")
        self.assertTrue(no_write_contract([registry.review(a),registry.review(b)]))
        self.assertFalse(registry.review(a).canonical_event_verified)

    def test_sponsor_alias_discovers_only_research(self):
        a=edition("source","123","paris-2025",name="Paris Masters",
                  aliases=("Rolex Paris Masters",))
        registry=ResearchEditionRegistry([a])
        hits=registry.discover_aliases(name="Rolex Paris Masters",
              tour="atp",season=2025,draw="main",
              discipline="singles",level="grand_slam")
        self.assertEqual(len(hits),1)
        self.assertTrue(no_write_contract(hits))
        self.assertEqual(hits[0].status,"research_edition_proposal")

    def test_same_city_other_year_does_not_merge(self):
        a=edition("atp","paris-2024","paris-2024",year=2024)
        b=edition("wta","paris-2025","paris-2025",year=2025,tour="wta")
        reg=ResearchEditionRegistry([a,b])
        self.assertEqual(reg.compare(a,b),"edition_context_conflict")
        self.assertFalse(reg.discover_aliases(name="Australian Open",
              tour="atp",season=2025,draw="main",
              discipline="singles",level="grand_slam"))

    def test_qualifying_main_draw_do_not_merge(self):
        a=edition("source","abc-main","edition",draw="main")
        b=edition("source","abc-qual","edition",draw="qual")
        reg=ResearchEditionRegistry([a,b])
        self.assertEqual(reg.compare(a,b),"edition_context_conflict")
        self.assertEqual(len(reg.discover_aliases(name="Australian Open",
              tour="atp",season=2025,draw="qual",
              discipline="singles",level="grand_slam")),1)

    def test_level_and_discipline_enforced(self):
        a=edition("x","1","event",level="itf")
        b=edition("y","2","event",level="challenger")
        reg=ResearchEditionRegistry([a,b])
        self.assertEqual(reg.compare(a,b),"edition_context_conflict")
        with self.assertRaises(ValueError):
            edition("x","3","event",discipline="undefined")
        with self.assertRaises(ValueError):
            edition("x","3","event",sha="not-a-hash")

    def test_same_native_source_scope_conflicting_keys_quarantine(self):
        a=edition("sackmann","one","key-a")
        b=edition("sackmann","one","key-b")
        reg=ResearchEditionRegistry([a,b])
        r=reg.review(a)
        self.assertEqual(r.status,"source_edition_collision")
        self.assertEqual(r.proposed_edition_keys,("key-a","key-b"))
        self.assertTrue(no_write_contract([r]))

    def test_ambiguous_name_edition_not_silently_collapsed(self):
        a=edition("s1","a","event-a",name="City Open")
        b=edition("s2","b","event-b",name="City Open")
        reg=ResearchEditionRegistry([a,b])
        hits=reg.discover_aliases(name="City Open",
              tour="atp",season=2025,draw="main",
              discipline="singles",level="grand_slam")
        self.assertEqual(len(hits),2)
        self.assertEqual({h.proposed_edition_keys[0] for h in hits},
                         {"event-a","event-b"})
        self.assertTrue(no_write_contract(hits))

    def test_different_research_keys_not_independent_negative(self):
        a=edition("s1","x","event-a",name="AO")
        b=edition("s2","y","event-b",name="Australian Open")
        reg=ResearchEditionRegistry([a,b])
        self.assertEqual(reg.compare(a,b),"different_research_edition_proposals")

    def test_missing_source_edition_proof_remains_unknown(self):
        a=edition("s1","x","event-a")
        unknown=edition("s2","y","event-a")
        reg=ResearchEditionRegistry([a])
        self.assertEqual(reg.compare(a,unknown),"edition_witness_unavailable")


if __name__=="__main__":
    unittest.main()
