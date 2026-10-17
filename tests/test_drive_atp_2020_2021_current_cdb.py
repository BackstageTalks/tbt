"""Offline regression tests for Drive ATP 2020/21 strict native CDB linkage."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_drive_atp_2020_2021_current_cdb import (
    norm, historical_event_id, attest, reconcile,
)

SOURCE = {
    "year": "2020",
    "drive_id": "1_sJoqU9_7buu1R6E7frRrsqYFTdtkI1b",
    "source_line": "2",
    "tourney_id": "2020-8888",
    "match_num": "300",
    "tourney_date": "20200106",
    "winner_id": "104925",
    "loser_id": "104745",
    "winner_name": "Novak Djokovic",
    "loser_name": "Rafael Nadal",
    "tourney_name": "Atp Cup",
    "round": "F",
    "score": "6-2 7-6(4)",
}
def cdb():
    mid = historical_event_id(SOURCE)
    return {
        "match_id": mid,
        "tour": "atp",
        "scheduled_at": "2020-01-06T12:00:00+00:00",
        "player1_id": "hist-js:atp:104925",
        "player2_id": "hist-js:atp:104745",
        "player1_name": "Novak Djokovic",
        "player2_name": "Rafael Nadal",
        "winner_id": "hist-js:atp:104925",
        "round_name": "f",
        "status": "completed",
        "provider_context_json": {
            "_tbt_provider_event_id": mid,
            "_tbt_source_category_name": "historical_main",
            "_tbt_event_identity": {
                "event_id": mid, "home": "Novak Djokovic",
                "away": "Rafael Nadal", "status": "completed",
            },
            "_tbt_statistics": {
                "source": "jeff_sackmann_match_snapshot:atp_matches_2020.csv",
                "event_id": mid,
            },
        },
    }

class NativeIdentityChecks(unittest.TestCase):
    def test_exact_original_lineage_matches(self):
        self.assertEqual(attest(SOURCE, cdb()), "VERIFIED_NATIVE_EVENT_AND_BOTH_PLAYERS")

    def test_only_native_ids_not_names(self):
        x = cdb()
        x["player1_id"] = "external-provider:104925"
        self.assertEqual(attest(SOURCE, x), "CANONICAL_PLAYER_OR_WINNER_ID_MISMATCH")

    def test_no_metadata_only_promotion(self):
        x = cdb()
        x["provider_context_json"] = {}
        self.assertEqual(attest(SOURCE, x), "CANONICAL_ORIGINAL_EVENT_LINEAGE_NOT_PROVEN")

    def test_source_lineage_exact_edition(self):
        x = cdb()
        x["provider_context_json"]["_tbt_statistics"]["source"] = "unverified.csv"
        self.assertEqual(attest(SOURCE, x), "CANONICAL_SOURCE_FILE_PROVENANCE_NOT_PROVEN")

    def test_date_conflict(self):
        x = cdb()
        x["scheduled_at"] = "2020-02-06T12:00:00+00:00"
        self.assertEqual(attest(SOURCE, x), "CANONICAL_DATE_CONFLICT")

    def test_names_source_remains_conservative(self):
        self.assertNotEqual(historical_event_id(SOURCE), historical_event_id({**SOURCE, "loser_name": "Roger Federer"}))

    def test_no_writer_authorization(self):
        res = reconcile([SOURCE], {"2020": {("2020-8888", "300"): SOURCE}},
                        {"2020": {historical_event_id(SOURCE): cdb()}, "2021": {}})
        self.assertEqual(res["verified_ids"], 1)
        self.assertEqual(res["production_cdb_writes"], 0)
        self.assertFalse(res["bulk_import_authorized"])
        self.assertFalse(res["per_event"][0]["write_authorized"])
        self.assertEqual(res["verified_secondary_ids"][0]["canonical_match_id"], historical_event_id(SOURCE))

    def test_disputed_archive_source_goes_to_review(self):
        r = reconcile([SOURCE], {"2020": {("2020-8888", "300"): {**SOURCE, "score": "0-6 0-6"}}},
                      {"2020": {historical_event_id(SOURCE): cdb()}, "2021": {}})
        self.assertEqual(r["verified_ids"], 0)
        self.assertEqual(r["counts"]["SOURCE_ARCHIVE_IDENTITY_DIFFERENCE_REVIEW"], 1)

    def test_normalization(self):
        self.assertEqual(norm("Déjà Vu  CUP"), "deja vu cup")

if __name__ == "__main__":
    unittest.main()
