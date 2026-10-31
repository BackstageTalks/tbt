"""Synthetic regressions for read-only DIL -> CDB native source preflight."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_dil_sackmann_cdb_intake.py"
spec = importlib.util.spec_from_file_location("prepare_dil_sackmann_cdb_intake", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def row(*, ids=True, bad=False, retired=False):
    d = {
        "tourney_date": "20240101", "tourney_name": "Test Open",
        "tourney_id": "2024-001" if ids else "", "match_num": "1",
        "winner_id": "101" if ids else "", "loser_id": "102" if ids else "",
        "winner_name": "Jane A", "loser_name": "Jane B", "surface": "Hard",
        "round": "R32", "score": "6-4 6-3" if not retired else "6-4 RET",
        "best_of": "3",
    }
    for side in ("w", "l"):
        d.update({f"{side}_{key}":str(n) for key, n in {
            "svpt": 60,"1stIn": 36,"1stWon": 28,"2ndWon": 12,
            "ace": 3,"df":2,"bpFaced":3,"bpSaved":2,
        }.items()})
    if bad:
        d["w_1stWon"] = "37"
    return d


def fixture(folder: Path, rows: list[dict], *, altered_receipt=False):
    path = folder / "source.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE dil_sackmann_source_files(filename TEXT,sha256 TEXT,tour TEXT,year INT,row_count INT);
        CREATE TABLE dil_sackmann_source_observations(source_file TEXT,source_row INT,tour TEXT,file_year INT,row_sha256 TEXT,winner_id TEXT,loser_id TEXT,tourney_id TEXT,identity_status TEXT,raw_json TEXT);
        CREATE TABLE dil_sackmann_provenance(match_key TEXT);
        CREATE TABLE dil_sackmann_intake_decisions(decision TEXT);
        CREATE TABLE dil_sackmann_verified_preexisting_links(match_id TEXT);
        CREATE TABLE dil_sackmann_receipts(key TEXT,value TEXT);
    """)
    db.execute("INSERT INTO dil_sackmann_source_files VALUES (?,?,?,?,?)",
               ("atp_matches_2024.csv", "a"*64, "atp", 2024, len(rows)))
    for i, obj in enumerate(rows, 2):
        db.execute("INSERT INTO dil_sackmann_source_observations VALUES (?,?,?,?,?,?,?,?,?,?)",
                   ("atp_matches_2024.csv", i, "atp", 2024, f"{i:064x}",
                    obj["winner_id"], obj["loser_id"], obj["tourney_id"],
                    "NATIVE_IDS_COMPLETE" if obj["winner_id"] else "INCOMPLETE_NATIVE_IDS",json.dumps(obj)))
        db.execute("INSERT INTO dil_sackmann_provenance VALUES (?)",(str(i),))
    receipt = {"state": json.dumps("ISOLATED_SOURCE_ONLY_CDB_PARITY_BLOCKED"),
               "provenance_join_to_observation_verified": "false",
               "production_CDB_modified": "false",
               "source_observations": str(len(rows)),
               "sources_metadata_provenance": str(len(rows))}
    if altered_receipt:
        receipt["production_CDB_modified"] = "true"
    db.executemany("INSERT INTO dil_sackmann_receipts VALUES (?,?)", receipt.items())
    db.commit()
    db.close()
    return path, bridge.digest(path)


class NativeDILBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_missing_ids_kept_out_of_linker_and_cdb(self):
        source, sha = fixture(self.root, [row(ids=False)])
        report = bridge.prepare(source, self.root/"stage", sha)
        self.assertEqual(report["counts"]["review_missing_native_identity"], 1)
        self.assertEqual(report["counts"]["source_valid_two_sided_serve"], 1)
        self.assertEqual(report["counts"].get("linker_input_rows_pending_independent_crosswalk", 0), 0)
        self.assertEqual(report["cdb_null_only_import_ready"], 0)
        self.assertFalse(report["canonical_identity_crosswalk_verified"])
        self.assertEqual(list((self.root/"stage"/"linker_inputs").iterdir()), [])

    def test_source_rows_with_native_ids_are_only_linker_inputs(self):
        source, sha = fixture(self.root, [row(ids=True)])
        report = bridge.prepare(source, self.root/"stage", sha)
        self.assertEqual(report["counts"]["linker_input_rows_pending_independent_crosswalk"], 1)
        self.assertEqual(report["cdb_null_only_import_ready"], 0)
        csv_text = (self.root/"stage"/"linker_inputs"/"atp_matches_2024.csv").read_text()
        self.assertIn("source_record_id",csv_text)
        self.assertIn("2024-001",csv_text)

    def test_bad_breakpoints_or_serve_rejected(self):
        self.assertFalse(bridge.side_valid(row(bad=True),"w"))
        a = row()
        a["l_bpSaved"] = "12"
        self.assertFalse(bridge.side_valid(a,"l"))

    def test_retirement_kept_out(self):
        source, sha = fixture(self.root, [row(retired=True)])
        report = bridge.prepare(source, self.root/"stage", sha)
        self.assertEqual(report["counts"]["noncompleted_or_uncertain_score"],1)
        self.assertEqual(report["cdb_null_only_import_ready"],0)

    def test_unknown_score_and_stale_status_are_not_exported(self):
        self.assertFalse(bridge.score_complete("UNKNOWN"))
        source, _ = fixture(self.root, [row(ids=True)])
        db = sqlite3.connect(source)
        db.execute("UPDATE dil_sackmann_source_observations SET identity_status='INCOMPLETE_NATIVE_IDS'")
        db.commit(); db.close()
        report = bridge.prepare(source, self.root/"stage", bridge.digest(source))
        self.assertEqual(report["counts"].get("linker_input_rows_pending_independent_crosswalk", 0), 0)

    def test_must_pin_source_hash(self):
        source, sha = fixture(self.root, [row()])
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            bridge.prepare(source, self.root/"stage", "0"*64)
        self.assertFalse((self.root/"stage").exists())

    def test_wont_reuse_output(self):
        source, sha = fixture(self.root, [row()])
        bridge.prepare(source, self.root/"stage", sha)
        with self.assertRaisesRegex(ValueError, "Output must not exist"):
            bridge.prepare(source, self.root/"stage", sha)

    def test_fail_closed_on_changed_source_receipt(self):
        source, sha = fixture(self.root, [row()], altered_receipt=True)
        with self.assertRaisesRegex(ValueError, "Unapproved"):
            bridge.prepare(source, self.root/"stage", sha)

    def test_mismatching_raw_identity_fails(self):
        source, _ = fixture(self.root, [row()])
        db = sqlite3.connect(source)
        db.execute("UPDATE dil_sackmann_source_observations SET winner_id='999'")
        db.commit();db.close()
        with self.assertRaisesRegex(ValueError, "differs"):
            bridge.prepare(source, self.root/"stage", bridge.digest(source))

    def test_duplicate_source_origin_fails(self):
        source, _ = fixture(self.root, [row(), row()])
        db = sqlite3.connect(source)
        db.execute("UPDATE dil_sackmann_source_observations SET source_row=2 WHERE source_row=3")
        db.commit();db.close()
        with self.assertRaisesRegex(ValueError, "duplicate source observation"):
            bridge.prepare(source, self.root/"stage", bridge.digest(source))

    def test_inventory_count_mismatch(self):
        source, _ = fixture(self.root, [row()])
        db = sqlite3.connect(source)
        db.execute("UPDATE dil_sackmann_source_files SET row_count=2")
        db.commit();db.close()
        with self.assertRaisesRegex(ValueError, "row counts"):
            bridge.prepare(source, self.root/"stage", bridge.digest(source))

if __name__ == "__main__":
    unittest.main()