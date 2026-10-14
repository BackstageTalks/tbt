"""Futures risk-root negative controls: explanatory only, never auto-link."""
import unittest

from scripts.research import identity_v2 as ident
from scripts.research.identity_v2_futures_risk_roots import (
    FUTURES_FAMILY, FuturesRiskCounter, inspect_case,
)


def source(*, edition="2025-001", day="2025-01-01", tour="atp"):
    return ident.Event("sackmann","source-row-1",tour,"singles",(
        ident.Player("sackmann",tour,"s1","Novak Djokovic"),
        ident.Player("sackmann",tour,"s2","Jannik Sinner")),
        day,"tournament_start","Paris","R16","6-4 6-4","s1",edition_id=edition)


def target(mid, *, day="2025-01-08", tournament="Paris",
           names=("Novak Djokovic","Jannik Sinner")):
    return ident.Event("CDB",mid,"atp","singles",(
        ident.Player("CDB","atp","c1",names[0]),
        ident.Player("CDB","atp","c2",names[1])),
        day,"scheduled",tournament,"R16",winner_native_id="c1")


def cand(mid, *, strong=False):
    return ident.EventCandidate(mid,("alias_pair_research",),
        context_tier="edition_context_strong" if strong
        else "unresolved_event_edition")


class FuturesCollisionRoots(unittest.TestCase):
    def test_multiple_candidates_stay_unresolved(self):
        s=source()
        c1=target("old",day="2025-01-05")
        c2=target("other",day="2025-01-18",tournament="Paris Futures",
                  names=("N. Djokovic","J. Sinner"))
        report=inspect_case(s,[c1],[cand("old",strong=True),cand("other")],
                            [c1,c2])
        self.assertTrue(report["old_event_retained"])
        self.assertTrue(report["multiple_distinct_cdb_tournament_labels"])
        self.assertTrue(report["multiple_distinct_cdb_scheduled_days"])
        self.assertTrue(report["some_candidates_more_than_14_days_after_source_start"])
        self.assertTrue(report["source_native_tournament_id_present"])
        self.assertEqual(report["strong_context_count"],1)
        self.assertFalse(report["canonical_event_resolved"])
        self.assertFalse(report["cdb_write_authorized"])

    def test_same_day_duplicate_can_be_colliding_events(self):
        s=source(edition="")
        c1=target("old",day="2025-01-03")
        c2=target("dup",day="2025-01-03")
        report=inspect_case(s,[c1],[cand("old"),cand("dup")],[c1,c2])
        self.assertTrue(report["multiple_candidates_on_same_day"])
        self.assertFalse(report["multiple_distinct_cdb_scheduled_days"])
        self.assertFalse(report["source_native_tournament_id_present"])

    def test_old_candidate_can_disappear_from_broader_set(self):
        s=source()
        old=target("old")
        c1=target("new1",day="2025-01-02")
        c2=target("new2",day="2025-01-04")
        case=inspect_case(s,[old],[cand("new1"),cand("new2")],
                          [old,c1,c2])
        self.assertFalse(case["old_event_retained"])
        self.assertFalse(case["canonical_event_resolved"])

    def test_weak_context_not_mistaken_for_authorized_crosswalk(self):
        s=source()
        c1=target("old")
        c2=target("two",day="2025-01-14")
        r=FuturesRiskCounter()
        r.consider(FUTURES_FAMILY,s,[c1],[cand("old"),cand("two")],[c1,c2])
        r.consider("wta/wta_matches_2025.csv",s,[c1],
                   [cand("old"),cand("two")],[c1,c2])
        result=r.report()
        self.assertEqual(result["old_unique_new_ambiguous_source_cases"],1)
        self.assertEqual(result["candidate_count_bins"],{"2":1})
        self.assertEqual(result["strong_context_count_bins"],{"0":1})
        self.assertEqual(result["independently_verified_sackmann_to_cdb_event_links"],0)
        self.assertEqual(result["cdb_writes"],0)
        self.assertNotIn("Novak",str(result))
        self.assertNotIn("source-row",str(result))

    def test_out_of_window_and_duplicate_event_ids_fail(self):
        s=source()
        c1=target("old")
        c2=target("future",day="2025-03-25")
        with self.assertRaisesRegex(ValueError,"Out-of-window"):
            inspect_case(s,[c1],[cand("old"),cand("future")],[c1,c2])
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            inspect_case(s,[c1],[cand("old"),cand("old")],[c1])

    def test_preauthorized_candidate_and_non_futures_date_fail(self):
        s=source()
        c1=target("old")
        c2=target("two",day="2025-01-14")
        with self.assertRaisesRegex(ValueError,"unverified"):
            inspect_case(s,[c1],[cand("old"),ident.EventCandidate(
                "two",(),cdb_write_authorized=True)],[c1,c2])
        with self.assertRaisesRegex(ValueError,"tournament-start"):
            inspect_case(ident.Event(**{**s.__dict__,"date_kind":"played"}),
                         [c1],[cand("old"),cand("two")],[c1,c2])

    def test_other_source_family_is_not_silently_claimed(self):
        s=source()
        c1=target("old")
        c2=target("two",day="2025-01-14")
        count=FuturesRiskCounter()
        count.consider("atp/atp_matches_2025.csv",s,[c1],
                       [cand("old"),cand("two")],[c1,c2])
        self.assertEqual(count.report()["old_unique_new_ambiguous_source_cases"],0)


if __name__=="__main__":
    unittest.main()
