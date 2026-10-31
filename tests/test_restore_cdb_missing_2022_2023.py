"""Offline safety tests: never replace a present/newer canonical CDB year."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from restore_cdb_missing_2022_2023 import PIN, YEARS, preflight

def fixtures():
    current, frozen = {"assets": []}, {"assets": []}
    actual, old, bundle = {}, {}, {}
    for year in YEARS:
        name = f"history-{year}.parquet"
        digest, size = PIN.get(year, ("1" * 64, 100))
        old[str(year)] = {"asset": name, "sha256": digest, "bytes": size}
        frozen["assets"].append({"name": "frozen__history__" + name, "state": "uploaded",
                                 "digest": "sha256:" + digest, "size": size})
        if year not in PIN:
            actual[str(year)] = {"asset": name, "sha256": digest, "bytes": size}
            current["assets"].append({"name": name, "state": "uploaded",
                                      "digest": "sha256:" + digest, "size": size})
            bundle[name] = {"sha256": digest, "bytes": size}
    return current, frozen, {"years": actual}, {"years": old}, {"files": bundle}

class TestGuard(unittest.TestCase):
    def test_only_two_years_added(self):
        a,b,c,d,e=fixtures()
        result=preflight(a,b,c,d,e)
        self.assertEqual(len(result["years"]),78)
        self.assertEqual(len(c["years"]),76)
        self.assertEqual(result["years"]["2026"],c["years"]["2026"])
    def test_reject_newer_cdb_metadata(self):
        a,b,c,d,e=fixtures()
        c["years"]["2022"]={"sha256":"9"*64}
        with self.assertRaises(ValueError):preflight(a,b,c,d,e)
    def test_reject_backup_sha_tampering(self):
        a,b,c,d,e=fixtures()
        next(x for x in b["assets"] if x["name"]=="frozen__history__history-2023.parquet")["digest"]="sha256:"+"0"*64
        with self.assertRaises(ValueError):preflight(a,b,c,d,e)
    def test_reject_other_missing_year(self):
        a,b,c,d,e=fixtures()
        a["assets"].pop()
        with self.assertRaises(ValueError):preflight(a,b,c,d,e)
    def test_reject_changed_cdb_sha(self):
        a,b,c,d,e=fixtures()
        e["files"]["history-2024.parquet"]["sha256"]="2"*64
        with self.assertRaises(ValueError):preflight(a,b,c,d,e)
    def test_reject_present_partition(self):
        a,b,c,d,e=fixtures()
        a["assets"].append({"name":"history-2022.parquet","state":"uploaded","digest":"sha256:"+"2"*64,"size":1})
        with self.assertRaises(ValueError):preflight(a,b,c,d,e)

if __name__=="__main__":
    unittest.main()
