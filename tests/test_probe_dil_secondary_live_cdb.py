import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR))
import probe_dil_secondary_live_cdb as probe


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fixture(folder, manifest=None, invalid=False):
    folder.mkdir(parents=True, exist_ok=False)
    files = {f"history-{year}.parquet": b"PAR1" + bytes([year % 256]) + b"PAR1" for year in (2001, 2002)}
    year_data = {str(year): {"sha256": sha(files[f"history-{year}.parquet"])} for year in (2001, 2002)}
    if invalid:
        year_data["2002"]["sha256"] = "0" * 64
    manifest_obj = {"years": year_data}
    files["history_manifest.json"] = json.dumps(manifest_obj).encode()
    files["_tbt_bundle_manifest.json"] = json.dumps({"files": {name: {"sha256": sha(data)} for name, data in files.items()}}).encode()
    for name, data in files.items():
        (folder / name).write_bytes(data)
    if manifest is not None:
        manifest.update({"tag_name": "tbt-data-v1", "assets": [{"name": name, "digest": "sha256:" + sha(data), "size": len(data), "id": index}
                                                        for index, (name, data) in enumerate(files.items(), 1)]})


class SnapshotSourceProbeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.meta = {}
        fixture(self.root / "fixture", manifest=self.meta)

    def tearDown(self):
        self.dir.cleanup()

    def _download(self, path):
        path.mkdir()
        for f in (self.root / "fixture").iterdir():
            (path / f.name).write_bytes(f.read_bytes())

    def test_full_source_receipt_is_verified_and_scratch_cleaned(self):
        answer = probe.probe(self.root / "temp", read_metadata=lambda: self.meta,
                             downloader=self._download, expected_parts=2)
        self.assertEqual(answer["partition_count"], 2)
        self.assertTrue(answer["source_binary_sha256s_verified"])
        self.assertEqual(answer["status"], "VERIFIED_TEST_FIXTURE")
        self.assertFalse(answer["cdb_dil_parity_achieved"])
        self.assertFalse((self.root / "temp").exists())

    def test_changed_release_after_download_rejects(self):
        calls = [self.meta, {**self.meta, "assets": [dict(y) for y in self.meta["assets"]]}]
        calls[1]["assets"][0]["digest"] = "sha256:" + "0"*64
        count = [0]
        def moving():
            count[0] += 1
            return calls[0] if count[0] == 1 else calls[1]
        with self.assertRaisesRegex(RuntimeError, "BOUNDED_ATTEMPTS"):
            probe.probe(self.root / "temp", read_metadata=moving,
                        downloader=self._download, attempts=1, expected_parts=2)
        self.assertFalse((self.root / "temp").exists())

    def test_corrupt_source_fails_even_when_release_stable(self):
        def corrupt(path):
            self._download(path)
            (path / "history-2001.parquet").write_bytes(b"PAR1xPAR1")
        with self.assertRaisesRegex(ValueError, "DIGEST MISMATCH"):
            probe.probe(self.root / "temp", read_metadata=lambda: self.meta,
                        downloader=corrupt, expected_parts=2)
        self.assertFalse((self.root / "temp").exists())

    def test_missing_release_partition_is_hard_failure(self):
        incomplete = {**self.meta, "assets": self.meta["assets"][:-1]}
        incomplete["assets"] = [a for a in incomplete["assets"] if a["name"] != "history-2002.parquet"]
        with self.assertRaisesRegex(ValueError, "partition inventory incomplete"):
            probe.probe(self.root / "temp", read_metadata=lambda: incomplete,
                        downloader=self._download, expected_parts=2)

    def test_transient_download_failure_without_release_drift_not_retried(self):
        attempted = []
        def unavailable(path):
            attempted.append(1)
            raise OSError("private failure")
        with self.assertRaisesRegex(RuntimeError, "unchanged release"):
            probe.probe(self.root / "temp", read_metadata=lambda: self.meta,
                        downloader=unavailable, attempts=3, expected_parts=2)
        self.assertEqual(len(attempted), 1)

    def test_drift_retries_and_succeeds_if_new_version_stays_stable(self):
        old = {**self.meta, "assets": [dict(x) for x in self.meta["assets"]]}
        old["assets"][0]["digest"] = "sha256:" + "0"*64
        calls = [0]
        def versions():
            calls[0] += 1
            return old if calls[0] == 1 else self.meta
        answer = probe.probe(self.root / "temp", read_metadata=versions,
                            downloader=self._download, attempts=2, expected_parts=2)
        self.assertEqual(answer["attempt"], 2)
        self.assertFalse((self.root / "temp").exists())

    def test_directory_overwrite_is_refused(self):
        (self.root / "temp").mkdir()
        with self.assertRaises(FileExistsError):
            probe.probe(self.root / "temp", read_metadata=lambda: self.meta,
                        downloader=self._download, expected_parts=2)

    def test_bad_source_year_manifest_rejected(self):
        folder = self.root / "fixture"
        data = json.loads((folder / "history_manifest.json").read_text())
        data["years"]["2002"]["sha256"] = "0" * 64
        changed = json.dumps(data).encode()
        (folder / "history_manifest.json").write_bytes(changed)
        for x in self.meta["assets"]:
            if x["name"] == "history_manifest.json":
                x["digest"] = "sha256:" + sha(changed)
                x["size"] = len(changed)
        bundle_file = folder / "_tbt_bundle_manifest.json"
        bundle = json.loads(bundle_file.read_text())
        bundle["files"]["history_manifest.json"]["sha256"] = sha(changed)
        payload = json.dumps(bundle).encode()
        bundle_file.write_bytes(payload)
        for x in self.meta["assets"]:
            if x["name"] == "_tbt_bundle_manifest.json":
                x["digest"] = "sha256:" + sha(payload)
                x["size"] = len(payload)
        with self.assertRaisesRegex(ValueError, "YEAR MANIFEST DIGEST MISMATCH"):
            probe.probe(self.root / "temp", read_metadata=lambda: self.meta,
                        downloader=self._download, expected_parts=2)


if __name__ == "__main__":
    unittest.main()