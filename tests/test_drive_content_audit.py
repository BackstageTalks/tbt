import copy
import hashlib
import unittest

from scripts.drive_content_audit import audit, ROOT, SOURCE_ROOT, CONTAINER_ROOT, DESTINATIONS, FOLDER_MIME


def source(fid, name, body, parent=SOURCE_ROOT):
    return {
        "id": fid, "name": name, "mimeType": "text/csv",
        "size": str(len(body)), "parents": [parent],
        "md5Checksum": hashlib.md5(body).hexdigest(),
        "sha256Checksum": hashlib.sha256(body).hexdigest(),
    }


class FakeReader:
    def __init__(self, items, data, hints=None, fail_sha=False):
        self.items = {i["id"]: copy.deepcopy(i) for i in items}
        self.data = data
        self.hints = hints or {}
        self.fail_sha = fail_sha
        self.bytes_downloaded = 0

    def metadata(self, fid):
        if fid == SOURCE_ROOT:
            return {"id": SOURCE_ROOT, "name": "BlinQ_data", "mimeType": FOLDER_MIME}
        if fid == CONTAINER_ROOT:
            return {"id": CONTAINER_ROOT, "name": "BlinQ", "mimeType": FOLDER_MIME, "parents": [SOURCE_ROOT]}
        for name, value in DESTINATIONS.items():
            if fid == value:
                parent = CONTAINER_ROOT if name in ("11_ZALOHY", "12_NA_KONTROLU") else SOURCE_ROOT
                return {"id": fid, "name": name, "mimeType": FOLDER_MIME, "parents": [parent]}
        return copy.deepcopy(self.items[fid])

    def children(self, parent):
        return iter(copy.deepcopy(i) for i in self.items.values() if i["parents"] == [parent])

    def digest(self, item, limit):
        if self.fail_sha:
            raise ValueError("cannot verify")
        body = self.data[item["id"]]
        if self.bytes_downloaded + len(body) > limit:
            raise ValueError("limit")
        self.bytes_downloaded += len(body)
        return hashlib.sha256(body).hexdigest()

    def sniff_category(self, item):
        return self.hints.get(item["id"])


class ReadOnlyAuditTest(unittest.TestCase):
    def test_two_different_names_same_bytes_detected_without_writes(self):
        rows = [source("a", "matches.csv", b"abc"), source("b", "totally_different.csv", b"abc")]
        api = FakeReader(rows, {"a": b"abc", "b": b"abc"})
        report = audit(api, max_download_mb=1)
        self.assertEqual(report["confirmed_identical_groups"], 1)
        self.assertEqual(report["source_originals_moved"], 0)
        self.assertEqual(report["drive_mutations"], 0)
        self.assertEqual(report["root_loose_files"], 2)
        self.assertEqual({x["status"] for x in report["details"]}, {"byte_identical_duplicate_group"})

    def test_name_is_not_schema_proof(self):
        row = source("a", "matches.csv", b"abc")
        api = FakeReader([row], {"a": b"abc"})
        report = audit(api)
        self.assertEqual(report["details"][0]["status"], "filename_only_or_schema_unknown")

    def test_valid_content_schema_can_confirm_classification(self):
        row = source("a", "matches.csv", b"winner,loser,date")
        api = FakeReader([row], {"a": b"winner,loser,date"}, hints={"a": "01_ZAPASY_A_VYSLEDKY"})
        self.assertEqual(audit(api)["details"][0]["status"], "header_signature_match_plan_only")

    def test_name_schema_disagreement_is_blocked(self):
        row = source("a", "matches.csv", b"player_id,rank,ranking_date")
        api = FakeReader([row], {"a": b"player_id,rank,ranking_date"},
                         hints={"a": "05_REBRICKY_A_ELO"})
        self.assertEqual(audit(api)["details"][0]["status"], "schema_name_disagreement")

    def test_existing_same_name_but_other_bytes_is_conflict(self):
        p = DESTINATIONS["06_HRACI_A_H2H"]
        rows = [source("a", "atp_players.csv", b"A"), source("b", "atp_players.csv", b"B", p)]
        api = FakeReader(rows, {"a": b"A", "b": b"B"})
        self.assertEqual(audit(api)["details"][0]["status"], "target_content_conflict_unverified")

    def test_bytes_unavailable_keeps_unverified(self):
        rows = [source("a", "a.csv", b"A"), source("b", "b.csv", b"B")]
        api = FakeReader(rows, {"a": b"A", "b": b"B"}, fail_sha=True)
        r = audit(api, max_download_mb=1)
        self.assertEqual(r["unverified_equal_size_groups"], 1)
        self.assertEqual(r["statuses"]["bytes_unverified_same_size"], 2)

    def test_invalid_folder_identity_fails(self):
        api = FakeReader([], {})
        baseline = api.metadata
        api.metadata = lambda fid: (
            {"id": fid, "name": "BAD", "mimeType": FOLDER_MIME, "parents": [SOURCE_ROOT]}
            if fid == DESTINATIONS["01_ZAPASY_A_VYSLEDKY"] else baseline(fid))
        with self.assertRaisesRegex(ValueError, "Pinned category"):
            audit(api)

    def test_source_parent_mismatch_blocks(self):
        api = FakeReader([], {})
        baseline = api.metadata
        api.metadata = lambda fid: (
            {"id": fid, "name": "BlinQ_data", "mimeType": FOLDER_MIME, "parents": [CONTAINER_ROOT]}
            if fid == CONTAINER_ROOT else baseline(fid))
        with self.assertRaisesRegex(ValueError, "Pinned child container"):
            audit(api)

    def test_nested_review_category_under_container_valid(self):
        review = source("r", "review.csv", b"R", DESTINATIONS["12_NA_KONTROLU"])
        loose = source("n", "matches.csv", b"N")
        api = FakeReader([review, loose], {"r": b"R", "n": b"N"})
        result = audit(api)
        self.assertEqual(result["root_loose_files"], 1)
        self.assertEqual(result["category_direct_files"], 1)
        self.assertEqual(result["details"][0]["parent"], SOURCE_ROOT)


if __name__ == "__main__":
    unittest.main()
