"""Adversarial unverified A/B conflict-triage regression tests."""
import unittest

from scripts.research import identity_v2 as identity
from scripts.research.identity_v2_triage import (
    review_case, safe_aggregate, ReviewCase
)


def source(*, round_name="R16", score="6-4 6-4", winner="w"):
    return identity.Event(
        "source", "native-match", "atp", "singles",
        (identity.Player("source","atp","w","Djokovic N."),
         identity.Player("source","atp","l","Sinner J.")),
        "2025-01-01", "tournament_start", "Australian Open",
        round_name, score, winner)


def old(mid):
    return identity.Event(
        "CDB","cdb-"+mid,"atp","singles",
        (identity.Player("CDB","atp","w-"+mid,"Novak Djokovic"),
         identity.Player("CDB","atp","l-"+mid,"Jannik Sinner")),
        "2025-01-12","scheduled","Australian Open","R16")


def new(mid, *, strong=False):
    return identity.EventCandidate(
        "cdb-"+mid, ("name_candidates","round"),
        context_tier=("edition_context_strong" if strong else "unresolved_event_edition"))


class ResearchTriage(unittest.TestCase):
    def test_regression_old_unique_new_ambiguous_is_highest_priority(self):
        r=review_case(source(),[old("one")],[new("one"),new("two")])
        self.assertEqual(r.bucket,"old_unique_became_ambiguous")
        self.assertEqual(r.priority,0)
        self.assertIn("multiple_event_candidates",r.blockers)
        self.assertFalse(r.independently_verified)
        self.assertFalse(r.cdb_write_authorized)

    def test_old_unique_replaced_cannot_be_accepted(self):
        r=review_case(source(),[old("one")],[new("two")])
        self.assertEqual(r.bucket,"old_unique_replaced")
        self.assertFalse(r.cdb_write_authorized)

    def test_old_candidate_lost(self):
        r=review_case(source(),[old("one")],[])
        self.assertEqual(r.bucket,"old_candidate_lost")
        self.assertEqual(r.old_count,1)
        self.assertEqual(r.new_count,0)

    def test_new_only_unique_strong_context_still_unverified(self):
        r=review_case(source(),[],[new("one",strong=True)])
        self.assertEqual(r.bucket,"new_only_unique_strong_context")
        self.assertNotIn("tournament_edition_unresolved",r.blockers)
        self.assertIn("independent_event_and_both_players_crosswalk_missing",r.blockers)
        self.assertFalse(r.independently_verified)

    def test_new_only_unique_weak_context(self):
        r=review_case(source(round_name="",score="",winner=""),[],[new("one")])
        self.assertEqual(r.bucket,"new_only_unique_weak_context")
        for flag in ("tournament_edition_unresolved","source_round_missing",
                     "source_score_missing","source_winner_unverified"):
            self.assertIn(flag,r.blockers)

    def test_agreed_single_metadata_match_is_still_not_cdb_proof(self):
        r=review_case(source(),[old("one")],[new("one",strong=True)])
        self.assertEqual(r.bucket,"old_and_new_same_unique")
        self.assertFalse(r.independently_verified)
        self.assertFalse(r.cdb_write_authorized)

    def test_overlapping_candidate_sets_differ_without_silent_promotion(self):
        r=review_case(source(),[old("one"),old("two")],
                      [new("one"),new("three")])
        self.assertEqual(r.bucket,"old_ambiguous_changed")
        self.assertTrue(r.priority<=2)

    def test_duplicate_ids_and_authorized_candidates_raise(self):
        with self.assertRaisesRegex(ValueError,"Duplicate event"):
            review_case(source(),[old("one"),old("one")],[new("one")])
        with self.assertRaisesRegex(ValueError,"Duplicate event"):
            review_case(source(),[],[new("one"),new("one")])
        with self.assertRaisesRegex(ValueError,"no-write"):
            review_case(source(),[],[identity.EventCandidate(
                 "evil",(),cdb_write_authorized=True)])

    def test_safe_aggregate_never_exports_player_names_or_event_ids(self):
        r=safe_aggregate([
            review_case(source(),[old("one")],[new("one"),new("two")]),
            review_case(source(),[],[new("alpha")])
        ])
        self.assertEqual(r["total_source_cases"],2)
        self.assertEqual(r["priority_bucket_counts"]["old_unique_became_ambiguous"],1)
        self.assertEqual(r["priority_bucket_counts"]["new_only_unique_weak_context"],1)
        self.assertEqual(r["cdb_writes"],0)
        self.assertFalse(r["cdb_import_authorized"])
        rendered=str(r)
        for secret in ("Djokovic","Sinner","native-match","cdb-one","alpha"):
            self.assertNotIn(secret,rendered)


if __name__=="__main__":
    unittest.main()
