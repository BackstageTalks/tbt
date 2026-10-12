import unittest
from scripts.drive_sort_prefolders import classify, run, ROOT, DESTINATIONS, FOLDER_MIME, SHORTCUT_MIME

class FakeDrive:
    def __init__(self, sources, linked=None, mismatched=False):
        self.sources = sources
        self.linked = linked or {}
        self.mismatched = mismatched
        self.created = []
    def metadata(self, fid):
        if fid == ROOT:
            return {"id": ROOT, "mimeType": FOLDER_MIME}
        for name, catid in DESTINATIONS.items():
            if catid == fid:
                return {"id": fid, "name": name if not self.mismatched else "WRONG",
                        "mimeType": FOLDER_MIME, "parents": [ROOT]}
        for item in self.created:
            if item["id"] == fid:
                return item
        raise AssertionError(fid)
    def children(self, fid):
        if fid == ROOT:
            return iter([{"id": "unsorted", "name": "Unsorted", "mimeType": FOLDER_MIME}])
        if fid == "unsorted":
            return iter(self.sources)
        if fid in DESTINATIONS.values():
            return iter([{"id": "old-" + k, "mimeType": SHORTCUT_MIME, "shortcutDetails": {"targetId": k}}
                         for k, v in self.linked.items() if DESTINATIONS[v] == fid])
        return iter([])
    def create_shortcut(self, source, destination):
        name = next(k for k, v in DESTINATIONS.items() if v == destination)
        if any(x["id"] == source["id"] for x in self.created):
            raise AssertionError("duplicate")
        item = {"id": "shortcut-" + source["id"], "mimeType": SHORTCUT_MIME,
                "shortcutDetails": {"targetId": source["id"]}, "parents": [destination]}
        self.created.append(item)
        self.linked[source["id"]] = name
        return item["id"]

def file(fid, name):
    return {"id": fid, "name": name, "mimeType": "text/csv"}

class ClassifierTests(unittest.TestCase):
    def test_known_types(self):
        self.assertEqual(classify("wta_2025_closing_odds.csv", ()), "02_KURZY_A_ODDS")
        self.assertEqual(classify("atp_rankings.csv", ()), "05_REBRICKY_A_ELO")
        self.assertEqual(classify("point_by_point_2021.csv", ()), "03_POINT_BY_POINT")
        self.assertEqual(classify("match_stats.csv", ()), "04_SERVIS_RETURN_STATISTIKY")
        self.assertEqual(classify("2025.xlsx", ("ATP Mens Tour",)), "01_ZAPASY_A_VYSLEDKY")
        self.assertEqual(classify("2025.xlsx", ("Unsorted",)), "12_NA_KONTROLU")
        self.assertEqual(classify("archive.zip", ()), "10_POVODNE_ZDROJE_ARCHIVY")
        self.assertEqual(classify("README.md", ()), "09_KOD_A_DOKUMENTACIA")
        self.assertEqual(classify("unknown.csv", ()), "12_NA_KONTROLU")

    def test_plan_only_preserves_everything(self):
        api = FakeDrive([file("a", "atp_matches.csv"), file("b", "unknown.csv")])
        report = run(api, apply=False, max_files=10, max_folders=10, max_new=3)
        self.assertEqual(report["new_shortcuts_verified"], 0)
        self.assertEqual(report["pending_unlinked"], 2)
        self.assertFalse(api.created)
        self.assertEqual(report["source_originals_moved"], 0)

    def test_idempotent_with_partial_write_cap(self):
        api = FakeDrive([file("a", "atp_matches.csv"), file("b", "odds.csv")])
        x = run(api, apply=True, max_files=10, max_folders=10, max_new=1)
        self.assertEqual(x["new_shortcuts_verified"], 1)
        self.assertEqual(x["pending_unlinked"], 1)
        y = run(api, apply=True, max_files=10, max_folders=10, max_new=5)
        self.assertEqual(y["already_linked"], 1)
        self.assertEqual(y["new_shortcuts_verified"], 1)
        self.assertEqual(y["pending_unlinked"], 0)

    def test_bad_destination_aborts_before_mutation(self):
        api = FakeDrive([file("a", "atp_matches.csv")], mismatched=True)
        with self.assertRaises(ValueError):
            run(api, apply=True, max_files=10, max_folders=10, max_new=3)
        self.assertFalse(api.created)

    def test_existing_shortcut_never_relocated(self):
        api = FakeDrive([file("a", "odds.csv")], linked={"a": "12_NA_KONTROLU"})
        x = run(api, apply=True, max_files=10, max_folders=10, max_new=2)
        self.assertEqual(x["already_linked"], 1)
        self.assertEqual(x["new_shortcuts_verified"], 0)

    def test_inventory_limit_blocks_before_mutation(self):
        api = FakeDrive([file("a", "odds.csv"), file("b", "scores.csv")])
        with self.assertRaises(ValueError):
            run(api, apply=True, max_files=1, max_folders=10, max_new=2)
        self.assertFalse(api.created)

if __name__ == "__main__":
    unittest.main()
