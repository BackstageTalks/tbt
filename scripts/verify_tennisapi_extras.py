"""Independent persisted CDB release read-back of post-match TennisApi extras."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def verify_markers(rows, expected):
    found = set()
    count = 0
    for match in rows:
        key = str(match.match_id)
        if key not in expected:
            continue
        if key in found:
            raise ValueError("Duplicate persisted extras match identity")
        found.add(key)
        for marker, content in expected[key].items():
            if (match.provider_payload or {}).get(marker) != content:
                raise ValueError("Missing/changed persisted TennisApi extras marker")
            if marker == "_tbt_tennisapi_markets":
                if content.get("pre_match_asof_verified") is not False:
                    raise ValueError("Unsafe historical odds as-of claim")
            if marker == "_tbt_tennisapi_pbp":
                if content.get("eligible_for_cdb_point_features") is not False:
                    raise ValueError("Unsafe same-match PBP feature claim")
            count += 1
    if found != set(expected):
        raise ValueError("Persisted extras match missing")
    return count


def main():
    from _bootstrap import ROOT  # noqa: F401
    from tbt.data.history_snapshot import load_snapshot
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-repository", required=True)
    ap.add_argument("--history-dir", default=".cache/tbt/history")
    args = ap.parse_args()
    root = Path(args.history_dir)
    evidence = json.loads((root / "extras_expected.json").read_text())
    expected = dict(evidence["markers"])
    names = [f"history-{int(y):04d}.parquet" for y in evidence["years"]]
    proof = {}
    with tempfile.TemporaryDirectory() as directory:
        remote = Path(directory)
        for name in names + ["_tbt_bundle_manifest.json"]:
            subprocess.run(["gh", "release", "download", "tbt-data-v1",
                            "--repo", args.data_repository, "--pattern", name,
                            "--dir", str(remote)], check=True)
        manifest = json.loads((remote / "_tbt_bundle_manifest.json").read_text())["files"]
        total = 0
        pending = dict(expected)
        for name in names:
            digest = hashlib.sha256((remote / name).read_bytes()).hexdigest()
            if digest != hashlib.sha256((root / name).read_bytes()).hexdigest():
                raise ValueError("Remote/local partition differs")
            if digest != manifest[name]["sha256"]:
                raise ValueError("Remote partition does not match persisted manifest")
            rows = load_snapshot(remote / name)
            mids = {str(m.match_id) for m in rows}
            subset = {mid: pending[mid] for mid in mids & pending.keys()}
            total += verify_markers(rows, subset)
            for mid in subset:
                del pending[mid]
            proof[name] = digest
        if pending:
            raise ValueError("Expected event extras missing in remote CDB release")
    expected_count = sum(len(markers) for markers in expected.values())
    if total != expected_count:
        raise ValueError("Persisted marker count differs from collector")
    report = {
        "status": "VERIFIED" if total else "VERIFIED_NO_NEW_MARKERS",
        "persisted_new_marker_count": total, "persisted_matches": len(expected),
        "partition_sha256": proof, "policy": "Post-match only, no as-of/point-model proof",
    }
    (root / "extras_readback.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
