#!/usr/bin/env python3
"""Restore only ABSENT CDB 2022/23 partitions from exact immutable private SHA backup.

Never overwrites a present year, reuses the existing global lock and ReleaseStore
guarded transaction, preserves untouched partitions and verifies remote readback.
2026 remains deliberately untouched pending separate lossless reconciliation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

REPO = "BackstageTalks/tbt-data"
TAG = "tbt-data-v1"
BACKUP = "blinq-full-training-backup-40554915730-1"
PIN = {2022: ("eba4ccbdb9f864a51d3488f6ab081b67de02cf97e0d48f7e017be5ac6b9bb382", 13290631),
       2023: ("55c5e5106b7c82c3c58484c8a87599cbdbde5bf8d6ac28f922bf1f9c9a446eb6", 17324308)}
YEARS = set(range(1949, 2027))
YEAR_RE = re.compile(r"history-(\d{4})\.parquet")

def cmd(*args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-900:])
    return p.stdout

def release(tag):
    return json.loads(cmd("gh", "api", f"repos/{REPO}/releases/tags/{tag}"))

def assets(record):
    names = [x["name"] for x in record["assets"] if x.get("state") == "uploaded"]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate release asset names")
    return {x["name"]: x for x in record["assets"] if x.get("state") == "uploaded"}

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def get_asset(tag, name, target, expected):
    target.mkdir(parents=True, exist_ok=True)
    cmd("gh", "release", "download", tag, "--repo", REPO,
        "--pattern", name, "--dir", str(target), "--clobber")
    p = target / name
    if (not p.is_file() or sha(p) != expected["digest"].removeprefix("sha256:")
            or p.stat().st_size != expected["size"]):
        raise ValueError("Not byte-identical: " + name)
    return p

def preflight(current, frozen, manifest, old_manifest, bundle):
    ca, ba = assets(current), assets(frozen)
    actual = {int(m.group(1)) for name in ca if (m := YEAR_RE.fullmatch(name))}
    if actual != YEARS - PIN.keys():
        raise ValueError("Unexpected CDB inventory; fail closed")
    target, orig, files = manifest.get("years"), old_manifest.get("years"), bundle.get("files")
    if not isinstance(target, dict) or not isinstance(orig, dict) or not isinstance(files, dict):
        raise ValueError("Invalid manifest")
    if set(map(int, target)) not in (actual, YEARS):
        raise ValueError("Unexpected manifest years")
    for y in actual:
        name = f"history-{y}.parquet"
        digest = ca[name]["digest"].removeprefix("sha256:")
        if target[str(y)]["sha256"] != digest or files[name]["sha256"] != digest:
            raise ValueError("Current year SHA mismatch: " + name)
    for y, (digest, size) in PIN.items():
        name = f"history-{y}.parquet"
        frozen_name = f"frozen__history__{name}"
        meta = orig.get(str(y))
        if (not isinstance(meta, dict) or meta.get("sha256") != digest
                or meta.get("bytes") != size or frozen_name not in ba
                or ba[frozen_name].get("digest") != "sha256:" + digest
                or ba[frozen_name].get("size") != size):
            raise ValueError("Unverified frozen year: " + str(y))
        if str(y) in target and target[str(y)].get("sha256") != digest:
            raise ValueError("Newer canonical year exists: " + str(y))
        if name in files and files[name]["sha256"] != digest:
            raise ValueError("Newer bundle year exists: " + str(y))
    for name, item in ca.items():
        if name == "_tbt_bundle_manifest.json":
            continue
        if name in files and files[name]["sha256"] != item.get("digest", "").removeprefix("sha256:"):
            raise ValueError("Untouched asset SHA mismatch: " + name)
    updated = json.loads(json.dumps(manifest))
    for y in PIN:
        updated["years"][str(y)] = orig[str(y)]
    updated["years"] = dict(sorted(updated["years"].items(), key=lambda x: int(x[0])))
    updated["recovery"] = {
        "kind": "restore_two_missing_release_assets_only",
        "backup_tag": BACKUP, "years": sorted(PIN),
        "proof": "exact_backup_SHA_current_CDB_manifest_and_ID_preflight",
    }
    return updated

def ids_by_partitions(files):
    import pyarrow.parquet as pq
    all_ids = set()
    for file in files:
        table = pq.read_table(file, columns=["match_id", "scheduled_at", "player1_id", "player2_id"])
        ids = table.column("match_id").to_pylist()
        dates = table.column("scheduled_at").to_pylist()
        p1 = table.column("player1_id").to_pylist()
        p2 = table.column("player2_id").to_pylist()
        expected_year = int(file.stem.split("-")[-1])
        for mid, date, a, b in zip(ids, dates, p1, p2):
            if (not mid or not a or not b or a == b or date is None
                    or date.year != expected_year or str(mid) in all_ids):
                raise ValueError("Malformed/duplicate cross-year canonical identity: " + file.name)
            all_ids.add(str(mid))
    return len(all_ids)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default=".cache/tbt/restore-cdb-2022-2023")
    args = p.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("Restoration only through GitHub Actions")
    from cdb_global_writer_lock import verify
    from release_store import ReleaseStore
    from download_stable_cdb import download_stable
    verify(REPO, Path(".cdb-global-writer-lock.json"))
    root = Path(args.out_dir)
    root.mkdir(parents=True, exist_ok=True)
    store = ReleaseStore(REPO, TAG, root)
    recovery = store.recover_interrupted_swaps()
    current, frozen = release(TAG), release(BACKUP)
    live, back = assets(current), assets(frozen)
    if {f"history-{y}.parquet" for y in PIN}.issubset(live):
        print(json.dumps({"status": "already_restored", "previous_recovery": recovery}))
        return
    for name in ("history_manifest.json", "_tbt_bundle_manifest.json"):
        get_asset(TAG, name, root / "current", live[name])
    frozen_manifest_name = "frozen__history__history_manifest.json"
    get_asset(BACKUP, frozen_manifest_name, root / "backup", back[frozen_manifest_name])
    manifest = json.loads((root / "current/history_manifest.json").read_text())
    old_manifest = json.loads((root / "backup" / frozen_manifest_name).read_text())
    bundle = json.loads((root / "current/_tbt_bundle_manifest.json").read_text())
    merged = preflight(current, frozen, manifest, old_manifest, bundle)
    paths = []
    for y in sorted(YEARS):
        name = f"history-{y}.parquet"
        if y in PIN:
            old_name = "frozen__history__" + name
            src = get_asset(BACKUP, old_name, root / "backup", back[old_name])
            dst = root / "restore" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        else:
            dst = get_asset(TAG, name, root / "current", live[name])
        paths.append(dst)
    examined = ids_by_partitions(paths)
    fresh = release(TAG)
    if (fresh["updated_at"] != current["updated_at"] or
            {n: (a["digest"], a["id"]) for n, a in assets(fresh).items()} !=
            {n: (a["digest"], a["id"]) for n, a in live.items()}):
        raise RuntimeError("CAS: release changed during preflight")
    manifest_path = root / "restore" / "history_manifest.json"
    manifest_path.write_text(json.dumps(merged, ensure_ascii=False, sort_keys=True, indent=2))
    verify(REPO, Path(".cdb-global-writer-lock.json"))
    store.upload_bundle([*(root / "restore" / f"history-{y}.parquet" for y in PIN), manifest_path])
    result = download_stable(REPO, TAG, root / "remote-readback")
    final = assets(release(TAG))
    for n, item in live.items():
        if n in ("history_manifest.json", "_tbt_bundle_manifest.json"):
            continue
        if n not in final or final[n]["digest"] != item["digest"]:
            raise RuntimeError("Unrelated asset changed: " + n)
    for y, (digest, _) in PIN.items():
        if final[f"history-{y}.parquet"]["digest"] != "sha256:" + digest:
            raise RuntimeError("Restored asset SHA readback mismatch")
    years = json.loads((root / "remote-readback/history_manifest.json").read_text())["years"]
    if len(years) != 78 or set(map(int, years)) != YEARS:
        raise RuntimeError("Not all 78 years present after readback")
    print(json.dumps({
        "status": "RESTORED_AND_REMOTE_READBACK_VERIFIED",
        "years_restored": [2022, 2023], "canonical_rows_examined": examined,
        "unrelated_years_preserved": 76, "DIL_values_written": 0,
        "year_2026_not_repaired": True, "download": result,
    }))

if __name__ == "__main__":
    main()
