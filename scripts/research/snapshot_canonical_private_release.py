#!/usr/bin/env python3
"""Backup the exact canonical history release assets to a separate immutable-named release.
No writes to tbt-data-v1. Fail closed on source changes and checksum mismatch.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
from datetime import datetime, timezone

REPO = "BackstageTalks/tbt-data"
SOURCE = "tbt-data-v1"
BACKUP = "blinq-canonical-snapshot-20261009-" + os.environ["GITHUB_RUN_ID"]
ROOT = Path("work/canonical_snapshot")
DATA = ROOT / "history"
ROOT.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True, exist_ok=True)

def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)

def current_assets():
    info = json.loads(gh("api", "repos/" + REPO + "/releases/tags/" + SOURCE))
    target = {x["name"]: x for x in info["assets"] if
              (x["name"].startswith("history-") and x["name"].endswith(".parquet"))
              or x["name"] == "history_manifest.json"}
    return info, target

def identity(assets):
    return {name: (asset["id"], asset["size"], asset.get("digest"))
            for name, asset in sorted(assets.items())}

def sha(path):
    obj = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            obj.update(block)
    return obj.hexdigest()

if not os.environ.get("GH_TOKEN"):\n    raise SystemExit("Missing private data GitHub access token")\nprivacy = json.loads(gh("api", "repos/" + REPO))\nif privacy.get("private") is not True:\n    raise SystemExit("Refusing non-private backup destination")\nbefore, sources = current_assets()
history = sorted(n for n in sources if n.startswith("history-") and n.endswith(".parquet"))
if len(history) < 70 or "history_manifest.json" not in sources:
    raise SystemExit("Source incomplete: fail closed")
if any(not sources[name].get("digest", "").startswith("sha256:") for name in sources):
    raise SystemExit("Missing source SHA256: fail closed")
if list(DATA.iterdir()):
    raise SystemExit("Output directory not empty: fail closed")

gh("release", "download", SOURCE, "--repo", REPO, "--dir", str(DATA),
   "--pattern", "history-*.parquet", "--pattern", "history_manifest.json")
files = sorted(sources)
if sorted(p.name for p in DATA.iterdir()) != files:
    raise SystemExit("Downloaded source file set differs from release")
checks = {}
for name in files:
    p = DATA / name
    actual = sha(p)
    expected = sources[name]["digest"].split(":", 1)[1]
    if p.stat().st_size != sources[name]["size"] or actual != expected:
        raise SystemExit("Source checksum mismatch: " + name)
    checks[name] = {"sha256": actual, "bytes": p.stat().st_size,
                    "source_asset_id": sources[name]["id"]}

after, new_sources = current_assets()
if identity(sources) != identity(new_sources):
    raise SystemExit("Source release changed during download; fail closed")

import pyarrow.parquet as pq
rows = {}
schemas = {}
for name in history:
    meta = pq.ParquetFile(DATA / name).metadata
    rows[name] = meta.num_rows
    schemas[name] = meta.num_columns
    if meta.num_rows < 1 or meta.num_columns < 1:
        raise SystemExit("Empty parquet partition: " + name)
loaded_manifest = json.loads((DATA / "history_manifest.json").read_text())
if not isinstance(loaded_manifest, dict):
    raise SystemExit("Unexpected canonical manifest format")
report = {
    "schema": 1,
    "status": "source_verified_pre_publish",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "repository": REPO,
    "source_release": SOURCE,
    "source_release_id": before["id"],
    "source_release_updated_at": before["updated_at"],\n    "private_backup_release": BACKUP,
    "source_asset_count": len(files),
    "history_partitions": len(history),
    "history_rows": sum(rows.values()),
    "year_rows": rows,
    "year_columns": schemas,
    "api_requests": 0,
    "original_data_unchanged": True,
    "assets": checks,
}
tarpath = ROOT / "canonical-history-20261009.tar"
with tarfile.open(tarpath, "w") as t:
    for name in files:
        t.add(DATA / name, arcname="history/" + name, recursive=False)
report["archive"] = {"name": tarpath.name, "bytes": tarpath.stat().st_size,
                     "sha256": sha(tarpath)}
proofpath = ROOT / "snapshot-proof.json"
proofpath.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
# Create only a NEW distinct backup release. Never use --clobber.
subprocess.check_call(["gh", "release", "create", BACKUP, str(tarpath),
    str(proofpath), "--repo", REPO, "--title", "BlinQ canonical backup 2026-10-08 22:36",
    "--target", json.loads(gh("api", "repos/" + REPO + "/branches/main"))["commit"]["sha"],
    "--notes", "Read-only exact copy of tbt-data-v1 history assets with SHA256, row counts and provenance. Canonical release unchanged."])
verdir = ROOT / "remote_readback"
verdir.mkdir()
gh("release", "download", BACKUP, "--repo", REPO, "--dir", str(verdir))
if sha(verdir / tarpath.name) != report["archive"]["sha256"]:
    raise SystemExit("Remote backup tar checksum mismatch")
if (verdir / proofpath.name).read_bytes() != proofpath.read_bytes():
    raise SystemExit("Remote proof differs")
with tarfile.open(verdir / tarpath.name) as t:
    members = {m.name: m for m in t.getmembers()}
    if sorted(members) != sorted("history/" + n for n in files):
        raise SystemExit("Remote archive member list mismatch")
    for name in files:
        stream = t.extractfile(members["history/" + name])
        if stream is None:
            raise SystemExit("Missing archived file: " + name)
        h = hashlib.sha256()
        for b in iter(lambda: stream.read(1024*1024), b""):
            h.update(b)
        if h.hexdigest() != checks[name]["sha256"]:
            raise SystemExit("Archived file mismatch: " + name)
readback = {"status": "PASS", "backup_release": BACKUP, "files": len(files),
            "history_rows": sum(rows.values()), "archive_sha256": report["archive"]["sha256"]}
(ROOT / "remote-readback.json").write_text(json.dumps(readback, indent=2) + "\n")
print(json.dumps({"result": "VERIFIED_PRIVATE_BACKUP", "backup_release_tag": BACKUP, "asset_count": len(files), "history_rows": sum(rows.values()), "readback": "PASS"}, indent=2))
