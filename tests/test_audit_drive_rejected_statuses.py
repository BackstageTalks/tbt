import gzip
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import audit_drive_rejected_statuses as mod

class AuditDriveRejectedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.archive=self.root/"old-private-bundle.tar.gz"
        self.out=self.root/"out"
        self.rows=[
            {"id":"A","name":"wta_matches_2025.csv","status":"QUARANTINE","reason":"download timeout"},
            {"id":"B","name":"archive_2025.csv","status":"DEFERRED_BUDGET"},
            {"id":"C","name":"atp-futures.xls","status":"NEEDS_FORMAT_ADAPTER"},
            {"id":"D","name":"atp-profile.json.gz","status":"NEEDS_FORMAT_ADAPTER"},
            {"id":"E","name":"data_big.zip","status":"NEEDS_LARGE_FILE_SHARD"},
            {"id":"F","name":"already.csv","status":"READ_VERIFIED"},
        ]
        self.save()

    def save(self, report=None, rows=None, corrupt=False):
        files={
            "files.json":json.dumps(self.rows if rows is None else rows).encode(),
            "report.json":json.dumps(report or {"cdb_writes":0,"approved_fields":0,"inventory_files":6}).encode(),
            "drive-inventory.json":json.dumps([{"id":r["id"],"path":"BlinQ/"+r["name"],"size":4000} for r in self.rows]).encode(),
            "run-evidence.txt":b"audit_outcome=success\n",
        }
        checksum="".join(f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k,v in files.items())
        if corrupt:checksum=checksum.replace("a","b",1)
        files["SHA256SUMS"]=checksum.encode()
        with tarfile.open(self.archive,"w:gz") as tar:
            for name,contents in files.items():
                info=tarfile.TarInfo("./"+name)
                info.size=len(contents)
                tar.addfile(info,io.BytesIO(contents))
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def test_priority_and_source_only_flags(self):
        sha=hashlib.sha256(self.archive.read_bytes()).hexdigest()
        report=mod.build(self.archive,sha,self.out)
        self.assertEqual(report["quarantine_count"],1)
        self.assertEqual(report["rejected_status_count"],5)
        self.assertEqual(report["current_CDB_NULL_fields_verified_new"],0)
        self.assertEqual(report["sports_api_requests"],0)
        with gzip.open(self.out/"recovery-work-queue-private.jsonl.gz","rt") as f:
            rows=[json.loads(x) for x in f if x.strip()]
        self.assertEqual(rows[0]["drive_file_id"],"A")
        self.assertFalse(any(x["import_ready"] or x["canonical_write_authorized"] for x in rows))
        self.assertIn("DEFERRED_BUDGET",report["original_readonly_file_status_counts"])

    def test_tampered_archive_hash_fails(self):
        with self.assertRaisesRegex(ValueError,"checksum differs"):
            mod.build(self.archive,"0"*64,self.out)

    def test_tampered_inner_hash_fails(self):
        sha=self.save(corrupt=True)
        with self.assertRaisesRegex(ValueError,"embedded file changed"):
            mod.build(self.archive,sha,self.out)

    def test_prior_report_with_cdb_writes_refused(self):
        sha=self.save(report={"cdb_writes":1,"approved_fields":0})
        with self.assertRaisesRegex(ValueError,"nonzero CDB"):
            mod.build(self.archive,sha,self.out)

    def test_duplicate_source_ids_refused(self):
        records=self.rows+[{"id":"A","name":"second.csv","status":"QUARANTINE","reason":"csv parse"}]
        sha=self.save(rows=records)
        with self.assertRaisesRegex(ValueError,"Duplicate original Drive file ID"):
            mod.build(self.archive,sha,self.out)

if __name__=="__main__": unittest.main()
