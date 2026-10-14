"""Adversarial negative controls for rechecking stored real 50-event evidence.

All mock data are fabricated. Actual 50-case run is the separate SHA-pinned
private-release/CDB workflow, and cannot substitute synthetic unit tests.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from scripts.research.verify_identity_v2_real_provider50 import (
    canonical_by_id, verify_details, check_file,
    EXACT, CDB_SHA, DETAIL_SHA,
)


def records():
    rows = []
    verdicts = []
    for n in range(50):
        tour = "atp" if n < 25 else "wta"
        event_id = str(1_000_001+n)
        p1 = str(2_000_001+n*2)
        p2 = str(2_000_002+n*2)
        match_id = "fixture-cdb-"+str(n)
        rows.append({
            "match_id": match_id, "tour": tour,
            "scheduled_at": datetime(2025,6,1,tzinfo=timezone.utc),
            "status": "finished", "winner_id": p1, "player1_id": p1,
            "player2_id": p2,
            "provider_context_json": {
                "_tbt_provider_event_id": event_id,
                "_tbt_event_identity": {
                    "event_id": event_id, "home": p1, "away": p2,
                    "status": "finished",
                },
            },
        })
        verdicts.append({
            "tour": tour, "provider_event_id": event_id,
            "canonical_match_id": match_id,
            "source_native_home_id": p1, "source_native_away_id": p2,
            "result": EXACT,
            "independently_verified_sofascore_ID": False,
            "writes_authorized": False,
        })
    return rows, verdicts


class RealProviderFiftyContract(unittest.TestCase):
    def test_positive_50_same_provider_still_zero_cross_source(self):
        canonical, detail = records()
        result=verify_details(detail,canonical_by_id(canonical))
        self.assertEqual(result["same_provider_native_match_rechecks"],50)
        self.assertEqual(result["atp_count"],25)
        self.assertEqual(result["wta_count"],25)
        self.assertEqual(result["external_provider_crosswalks_proven"],0)
        self.assertEqual(result["identity_v2_CDB_writes"],0)
        self.assertEqual(result["rapidapi_requests"],0)
        self.assertNotIn("fixture-cdb",str(result))

    def test_same_number_from_unrelated_provider_different_players_rejected(self):
        canonical,detail=records()
        # Mimics TennisData.App ID coincidence with distinct player namespace:
        # same event_id digits do NOT permit cross-source event merge.
        detail[0]["source_native_home_id"]="987654321"
        with self.assertRaisesRegex(ValueError,"participant"):
            verify_details(detail,canonical_by_id(canonical))

    def test_stored_api_verdict_cannot_freshly_redetect_opposite_winner(self):
        canonical, detail = records()
        canonical[0]["winner_id"]=canonical[0]["player2_id"]
        # This replay has no original provider winnerCode payload to compare.
        # Immutable CDB pin and original stored verdict are mandatory.
        result=verify_details(detail,canonical_by_id(canonical))
        self.assertEqual(result["provider_winner_responses_freshly_rechecked"],0)
        self.assertEqual(result["stored_original_provider_winner_verdicts"],50)
        self.assertEqual(result["external_provider_crosswalks_proven"],0)

    def test_winner_outside_pair_rejected(self):
        canonical,detail=records()
        canonical[0]["winner_id"]="999999999"
        with self.assertRaisesRegex(ValueError,"winner"):
            verify_details(detail,canonical_by_id(canonical))

    def test_duplicate_provider_event_mapping_rejected(self):
        canonical,detail=records()
        detail[1]["provider_event_id"]=detail[0]["provider_event_id"]
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            verify_details(detail,canonical_by_id(canonical))

    def test_duplicate_canonical_target_rows_rejected(self):
        canonical,_=records()
        with self.assertRaisesRegex(ValueError,"collision"):
            canonical_by_id(canonical+[deepcopy(canonical[0])])

    def test_wrong_result_or_preauthorized_row_blocked(self):
        canonical,detail=records()
        detail[0]["result"]="NAME_AND_SCORE_MATCH_ONLY"
        with self.assertRaisesRegex(ValueError,"unauthorized|unverified"):
            verify_details(detail,canonical_by_id(canonical))
        canonical,detail=records()
        detail[0]["writes_authorized"]=True
        with self.assertRaisesRegex(ValueError,"unauthorized|unverified"):
            verify_details(detail,canonical_by_id(canonical))

    def test_exact_immutable_digest_required(self):
        with tempfile.TemporaryDirectory() as dir:
            f=Path(dir)/"detail.jsonl"
            f.write_bytes(b"forged original")
            with self.assertRaisesRegex(ValueError,"SHA-256 mismatch"):
                check_file(f,DETAIL_SHA)
            with self.assertRaisesRegex(ValueError,"SHA-256 mismatch"):
                check_file(f,CDB_SHA)

    def test_exact_ATP_WTA_mix_required(self):
        canonical,detail=records()
        # Reassign the last WTA target to ATP while maintaining 50 distinct
        # provider event IDs: full set should still be rejected.
        canonical[49]["tour"]="atp"
        detail[49]["tour"]="atp"
        with self.assertRaisesRegex(ValueError,"ATP/WTA"):
            verify_details(detail,canonical_by_id(canonical))

    def test_selected_canonical_only_ignores_unrelated_collision(self):
        canonical,detail=records()
        unrelated=deepcopy(canonical[0])
        unrelated["match_id"]="not-in-target-sample"
        targets={(z["tour"],z["canonical_match_id"]) for z in detail}
        c=canonical_by_id(canonical+[unrelated],targets)
        self.assertEqual(len(c),50)
        self.assertEqual(verify_details(detail,c)["same_provider_native_match_rechecks"],50)


if __name__ == "__main__":
    unittest.main()
