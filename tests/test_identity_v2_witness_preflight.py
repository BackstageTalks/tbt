"""Synthetic negative controls for independent original event witness intake."""
import unittest
from copy import deepcopy

from scripts.research import identity_v2 as v2
from scripts.research.identity_v2_witness_preflight import (
    check_witness_shape,aggregate_witness_graph
)

S="a"*64
O="b"*64
C="c"*64


def event(namespace, event_id, p1="1",p2="2", winner="1",
          when="2025-01-08", date_kind="played"):
    return v2.Event(namespace,event_id,"atp","singles",
        (v2.Player(namespace,"atp",p1,"Novak Djokovic"),
         v2.Player(namespace,"atp",p2,"Jannik Sinner")),
        when,date_kind,"Melbourne","R16","6-4 6-4",winner)


def claim(source=None,canonical=None,**updates):
    source=source or event("sackmann:atp_2025","row:42")
    canonical=canonical or event("CDB","cdb:88","c1","c2","c1")
    data={
        "schema":1,"kind":"independent_original_event_witness",
        "source_namespace":source.namespace,
        "source_event_key":source.event_id,
        "source_native_player_ids":[x.native_id for x in source.players],
        "provider_namespace":"official_atp",
        "provider_event_id":"atp-match-88",
        "official_provider_player_ids":["atp-p1","atp-p2"],
        "canonical_match_id":canonical.event_id,
        "canonical_player_ids":[x.native_id for x in canonical.players],
        "canonical_tour":"atp",
        "source_file_sha256":S,
        "independent_original_sha256":O,
        "canonical_snapshot_sha256":C,
        "source_lineage":"Sackmann 2025 CSV",
        "original_lineage":"original ATP primary provider",
        "original_kind":"official_provider_native_event_with_both_players",
        "source_key_kind":"source_file_row_coordinate",
        "coordinate_to_official_event_bridge_attested":True,
        "official_played_day":"2025-01-08",
        "import_ready":False,"write_authorized":False
    }
    data.update(updates)
    return source,canonical,data


def assess(source,canonical,record):
    return check_witness_shape(source,canonical,record,
                              pinned_source_sha256=S,pinned_cdb_sha256=C)


class WitnessIntake(unittest.TestCase):
    def test_consistent_claim_is_still_not_independently_verified(self):
        s,c,r=claim()
        result=assess(s,c,r)
        self.assertEqual(result.status,"witness_shape_consistent_for_PRIVATE_review")
        self.assertFalse(result.identity_verified)
        self.assertFalse(result.canonical_match_attested)
        self.assertFalse(result.cdb_write_authorized)
        g=aggregate_witness_graph([(s,c,r)],
                pinned_source_sha256=S,pinned_cdb_sha256=C)
        self.assertEqual(g["status_counts"][
            "witness_shape_consistent_private_review_only"],1)
        self.assertEqual(g["verified_canonical_events"],0)
        self.assertEqual(g["actual_independent_originals_byte_verified"],0)

    def test_sackmann_file_row_is_not_a_provider_native_id(self):
        s,c,r=claim(coordinate_to_official_event_bridge_attested=False)
        self.assertEqual(assess(s,c,r).status,
                         "source_row_not_official_event_ID")

    def test_fake_same_source_sha_is_not_independent(self):
        s,c,r=claim(independent_original_sha256=S)
        self.assertEqual(assess(s,c,r).status,
                         "same_source_bytes_not_independent")

    def test_correlated_lineage_is_blocked(self):
        s,c,r=claim(original_lineage="Sackmann 2025 CSV")
        self.assertEqual(assess(s,c,r).status,
                         "unproven_independent_upstream_lineage")

    def test_wrong_canonical_snapshot_is_blocked(self):
        s,c,r=claim(canonical_snapshot_sha256="9"*64)
        self.assertEqual(assess(s,c,r).status,"snapshot_sha_mismatch")

    def test_both_player_ids_required(self):
        s,c,r=claim(official_provider_player_ids=["atp-p1"])
        self.assertEqual(assess(s,c,r).status,
                         "both_player_native_IDs_not_attested")
        s,c,r=claim(canonical_player_ids=["c1","c1"])
        self.assertEqual(assess(s,c,r).status,
                         "both_player_native_IDs_not_attested")

    def test_canonical_player_mismatch_blocks(self):
        s,c,r=claim(canonical_player_ids=["c2","c1"])
        self.assertEqual(assess(s,c,r).status,"canonical_player_pair_mismatch")

    def test_source_player_mismatch_blocks(self):
        s,c,r=claim(source_native_player_ids=["2","1"])
        self.assertEqual(assess(s,c,r).status,"source_player_pair_mismatch")

    def test_no_unsigned_pre_authorization(self):
        s,c,r=claim(write_authorized=True)
        with self.assertRaisesRegex(ValueError,"pre-authorized"):
            assess(s,c,r)
        s,c,r=claim(import_ready=True)
        with self.assertRaisesRegex(ValueError,"pre-authorized"):
            assess(s,c,r)

    def test_conflicting_winner_not_crosswalked(self):
        s=event("sackmann:atp_2025","row:42",winner="1")
        c=event("CDB","cdb:88","c1","c2","c2")
        _,_,r=claim(source=s,canonical=c)
        self.assertEqual(assess(s,c,r).status,"winner_side_conflict")

    def test_original_day_must_agree_with_canonical_played_date(self):
        s,c,r=claim(official_played_day="2025-05-08")
        self.assertEqual(assess(s,c,r).status,
                         "official_event_day_conflicts_with_CDB")

    def test_provider_event_id_collision_quarantined(self):
        a=claim()
        s2=event("sackmann:atp_2025","row:43",p1="3",p2="4",winner="3")
        c2=event("CDB","cdb:89","c3","c4","c3")
        b=claim(source=s2,canonical=c2)
        report=aggregate_witness_graph([a,b],
                   pinned_source_sha256=S,pinned_cdb_sha256=C)
        self.assertEqual(report["status_counts"]["event_identity_graph_collision"],2)
        self.assertEqual(report["verified_canonical_events"],0)

    def test_one_source_player_claims_two_canonical_ids_quarantined(self):
        a=claim()
        s2=event("sackmann:atp_2025","row:43",p1="1",p2="3",winner="1")
        c2=event("CDB","cdb:89","c9","c3","c9")
        b=claim(source=s2,canonical=c2,provider_event_id="atp-match-89")
        report=aggregate_witness_graph([a,b],
                   pinned_source_sha256=S,pinned_cdb_sha256=C)
        self.assertEqual(report["status_counts"]["player_crosswalk_graph_collision"],2)

    def test_duplicate_original_provider_rows_stay_review_only(self):
        a=claim()
        report=aggregate_witness_graph([a,deepcopy(a)],
                   pinned_source_sha256=S,pinned_cdb_sha256=C)
        self.assertEqual(report["verified_canonical_events"],0)
        self.assertEqual(report["source_claim_rows"],2)

    def test_invalid_sha_and_scope_rejected(self):
        s,c,r=claim(source_file_sha256="wrong")
        self.assertEqual(assess(s,c,r).status,"missing_immutable_source_provenance")
        s,c,r=claim(source_namespace="other")
        self.assertEqual(assess(s,c,r).status,"event_scope_or_target_mismatch")


if __name__=="__main__":
    unittest.main()
