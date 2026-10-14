"""Old baseline versus v2 rejection reasons: adversarial research-only tests."""
import unittest
from scripts.research import identity_v2 as v2
from scripts.research import shadow_identity_v2 as old
from scripts.research.identity_v2_loss_diagnosis import (
    diagnose_old_only,aggregate_old_only_diagnostics,
)


def row(*, namespace="s", winner="1", score="", date_kind="tournament_start",
        when="2025-01-01", event_id="one"):
    return v2.Event(
        namespace,event_id,"atp","singles",
        (v2.Player(namespace,"atp","1","Novak Djokovic"),
         v2.Player(namespace,"atp","2","Jannik Sinner")),
        when,date_kind,"Australian Open","R16",score,winner)


class LossReasons(unittest.TestCase):
    def test_winner_orientation_is_real_reason_for_old_only(self):
        source=row(namespace="s",winner="1")
        canonical=row(namespace="CDB",winner="2",date_kind="scheduled")
        self.assertTrue(old.proxy_old_match(source,canonical))
        self.assertEqual(v2.discover_events(source,[canonical]),[])
        self.assertEqual(diagnose_old_only(source,canonical),
                         "winner_orientation_conflict")

    def test_full_score_conflict_is_rejection_not_name_alias_failure(self):
        source=row(namespace="source",score="6-4 6-4")
        canonical=row(namespace="CDB",date_kind="scheduled",score="6-2 6-4")
        self.assertTrue(old.proxy_old_match(source,canonical))
        self.assertEqual(v2.discover_events(source,[canonical]),[])
        self.assertEqual(diagnose_old_only(source,canonical),"set_score_conflict")

    def test_complete_vs_retirement_not_silently_recovered(self):
        source=row(namespace="source",score="6-4 6-4")
        canonical=row(namespace="CDB",date_kind="scheduled",score="6-4 3-1 RET")
        self.assertTrue(old.proxy_old_match(source,canonical))
        self.assertEqual(v2.discover_events(source,[canonical]),[])
        self.assertEqual(diagnose_old_only(source,canonical),
                         "retirement_vs_completed_score_conflict")

    def test_not_lost_is_not_counted_as_rejected(self):
        source=row(namespace="source")
        canonical=row(namespace="CDB",date_kind="scheduled")
        self.assertTrue(old.proxy_old_match(source,canonical))
        self.assertEqual(len(v2.discover_events(source,[canonical])),1)
        self.assertEqual(diagnose_old_only(source,canonical),"not_lost_by_v2")
        q=aggregate_old_only_diagnostics([
            (source,[canonical],[v2.EventCandidate("one",())])
        ])
        self.assertEqual(q["lost_old_candidates_examined"],0)

    def test_mixed_lost_and_retained_are_counted_without_ids(self):
        source=row(namespace="source")
        a=row(namespace="CDB",winner="2",date_kind="scheduled",event_id="bad")
        b=row(namespace="CDB",winner="1",date_kind="scheduled",event_id="good")
        q=aggregate_old_only_diagnostics([
            (source,[a,b],[v2.EventCandidate("good",())])
        ])
        self.assertEqual(q["source_cases_with_lost_candidates"],1)
        self.assertEqual(q["lost_old_candidates_examined"],1)
        self.assertEqual(q["reason_counts"]["winner_orientation_conflict"],1)
        self.assertFalse(q["cdb_write_authorized"])
        self.assertNotIn("bad",str(q))

    def test_reject_preauthorized_research_inputs(self):
        with self.assertRaisesRegex(ValueError,"cannot accept authorized"):
            aggregate_old_only_diagnostics([(
                row(),[],[v2.EventCandidate("m",(),identity_verified=True)]
            )])

    def test_not_proxy_old_is_diagnosed_separately(self):
        source=row()
        canonical=row(namespace="CDB",date_kind="scheduled",when="2025-04-01")
        self.assertEqual(diagnose_old_only(source,canonical),
                         "not_an_old_proxy_candidate")


if __name__=="__main__":
    unittest.main()
