import copy
import hashlib
import unittest
from collections import defaultdict

from scripts.drive_content_organizer import organize, ROOT, DESTINATIONS, FOLDER_MIME, REVIEW


def item(fid, name, data, parent=ROOT):
    import hashlib
    return {
        "id": fid, "name": name, "size": str(len(data)),
        "mimeType": "text/csv" if name.endswith(".csv") else "application/zip",
        "parents": [parent], "md5Checksum": hashlib.md5(data).hexdigest(),
        "sha256Checksum": hashlib.sha256(data).hexdigest(),
    }


class FakeContentAPI:
    def __init__(self, records, contents, mutate_before=False, fail_on_digest=False):
        self.records = {r["id"]: copy.deepcopy(r) for r in records}
        self.contents = contents
        self.moved = []
        self.bytes_downloaded = 0
        self.mutate_before = mutate_before
        self.fail_on_digest = fail_on_digest

    def metadata(self, fid):
        if fid == ROOT:
            return {"id": ROOT, "mimeType": FOLDER_MIME}
        for name, dest in DESTINATIONS.items():
            if fid == dest:
                return {"id": fid, "name": name, "mimeType": FOLDER_MIME, "parents": [ROOT]}
        r = copy.deepcopy(self.records[fid])
        if self.mutate_before and self.moved == []:
            r["name"] = "interfered.csv"
        return r

    def children(self, fid):
        return iter(copy.deepcopy(x) for x in self.records.values() if x["parents"] == [fid])

    def digest(self, source, max_download):
        if self.fail_on_digest:
            raise ValueError("unverifiable raw file")
        data = self.contents[source["id"]]
        if self.bytes_downloaded + len(data) > max_download:
            raise ValueError("byte budget")
        self.bytes_downloaded += len(data)
        return hashlib.sha256(data).hexdigest()

    def sniff_category(self, source):
        return None

    def move(self, source, dest):
        assert source["parents"] == [ROOT]
        fid = source["id"]
        assert self.records[fid]["parents"] == [ROOT]
        self.records[fid]["parents"] = [dest]
        self.moved.append((fid, dest))


class OrganizeTests(unittest.TestCase):
    def test_plan_reads_content_and_never_mutates(self):
        a = item("1", "matches.csv", b"same")
        b = item("2", "odds.csv", b"same")
        api = FakeContentAPI([a, b], {"1": b"same", "2": b"same"})
        report = organize(api, max_moves=5, max_download_mb=1)
        self.assertEqual(report["confirmed_byte_identical_groups"], 1)
        self.assertEqual(report["moved_readback_verified"], 0)
        self.assertEqual(report["source_originals_deleted"], 0)
        self.assertEqual(api.moved, [])

    def test_identical_root_files_keep_one_and_quarantine_one(self):
        rows = [item("a", "matches.csv", b"A"), item("b", "match_results.csv", b"A")]
        api = FakeContentAPI(rows, {"a": b"A", "b": b"A"})
        r = organize(api, apply=True, max_moves=5, max_download_mb=1)
        self.assertEqual(r["moved_readback_verified"], 2)
        self.assertEqual(api.records["a"]["parents"], [DESTINATIONS["01_ZAPASY_A_VYSLEDKY"]])
        self.assertEqual(api.records["b"]["parents"], [DESTINATIONS[REVIEW]])
        self.assertEqual(r["root_loose_after_verified"], 0)
        self.assertEqual(organize(api, apply=True, max_moves=5, max_download_mb=1)["moved_readback_verified"], 0)

    def test_duplicate_of_categorized_file_moves_only_root_to_review(self):
        canon = item("canonical", "atp_players.csv", b"same", DESTINATIONS["06_HRACI_A_H2H"])
        root = item("another", "tennis_players.csv", b"same")
        api = FakeContentAPI([canon, root], {"canonical": b"same", "another": b"same"})
        r = organize(api, apply=True, max_moves=5, max_download_mb=1)
        self.assertEqual(r["moved_readback_verified"], 1)
        self.assertEqual(api.records["canonical"]["parents"], [DESTINATIONS["06_HRACI_A_H2H"]])
        self.assertEqual(api.records["another"]["parents"], [DESTINATIONS[REVIEW]])

    def test_equal_names_different_contents_block(self):
        rows = [item("a", "matches.csv", b"A"), item("b", "matches.csv", b"B")]
        api = FakeContentAPI(rows, {"a": b"A", "b": b"B"})
        r = organize(api, apply=True, max_moves=5, max_download_mb=1)
        self.assertEqual(r["moved_readback_verified"], 0)
        self.assertEqual(r["statuses"]["root_name_collision"], 2)

    def test_same_name_conflicting_with_existing_category_blocks(self):
        current = item("c", "atp_players.csv", b"C", DESTINATIONS["06_HRACI_A_H2H"])
        new = item("n", "atp_players.csv", b"N")
        api = FakeContentAPI([current, new], {"c": b"C", "n": b"N"})
        r = organize(api, apply=True, max_moves=5, max_download_mb=1)
        self.assertEqual(r["moved_readback_verified"], 0)
        self.assertEqual(r["statuses"]["destination_name_collision"], 1)

    def test_protected_archives_unknown_files_and_folders_not_touched(self):
        rows = [item("zip", "TML data.zip", b"zipdata"), item("unknown", "x.csv", b"unknown")]
        api = FakeContentAPI(rows, {"zip": b"zipdata", "unknown": b"unknown"})
        r = organize(api, apply=True, max_moves=5, max_download_mb=1)
        self.assertEqual(r["moved_readback_verified"], 0)
        self.assertIn("protected_archive", r["statuses"])
        self.assertIn("unknown_content", r["statuses"])

    def test_byte_failure_fails_closed(self):
        rows = [item("a", "matches.csv", b"x"), item("b", "score.csv", b"y")]
        api = FakeContentAPI(rows, {"a": b"x", "b": b"y"}, fail_on_digest=True)
        r = organize(api, apply=True, max_moves=5, max_download_mb=1)
        self.assertEqual(r["moved_readback_verified"], 0)
        self.assertEqual(r["statuses"]["unverified_same_size"], 2)

    def test_preflight_detects_modified_metadata(self):
        rows = [item("a", "atp_players.csv", b"A")]
        api = FakeContentAPI(rows, {"a": b"A"}, mutate_before=True)
        with self.assertRaisesRegex(ValueError, "Source changed"):
            organize(api, apply=True, max_moves=5, max_download_mb=1)
        self.assertEqual(api.moved, [])

    def test_move_cap(self):
        rows = [item(str(x), f"atp_matches_{x}.csv", (b"A" * (x + 1))) for x in range(4)]
        api = FakeContentAPI(rows, {str(x): b"A" * (x + 1) for x in range(4)})
        r = organize(api, apply=True, max_moves=2, max_download_mb=1)
        self.assertEqual(r["moved_readback_verified"], 2)
        self.assertEqual(r["unprocessed_actions"], 2)
        self.assertEqual(len(api.moved), 2)


if __name__ == "__main__":
    unittest.main()
