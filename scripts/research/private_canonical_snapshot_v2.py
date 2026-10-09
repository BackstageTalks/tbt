#!/usr/bin/env python3
"""Fail-closed, read-only canonical release backup. All artifacts remain in a private repo."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
from datetime import datetime, timezone

REPO = "BackstageTalks/tbt-data"
SOURCE = "tbt-data-v1"
BACKUP = "blinq-canonical-backup-" + os.environ["GITHUB_RUN_ID"]
ROOT = Path("work/private_canonical_backup")
DATA = ROOT / "parts"

def cmd(*args):
    return subprocess.check_output(list(args), text=True).strip()

def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

def release_state():
    data = json.loads(cmd("gh", "api", f"repos/{REPO}/releases/tags/{SOURCE}"))
    names = {x["name"]: x for x in data["assets"]
             if x["name"] == "history_manifest.json" or
             (x["name"].startswith("history-") and x["name"].endswith(".parquet"))}
    return data, names

def identity(assets):
    return {n: (a["id"], a["size"], a.get("digest")) for n, a in assets.items()}

if not os.environ.get("GH_TOKEN"):
    raise SystemExit("Missing private repository credential")
if not json.loads(cmd("gh", "api", f"repos/{REPO}"))["private"]:
    raise SystemExit("Destination not private")
old_release, old_assets = release_state()
parts = sorted(n for n in old_assets if n.endswith(".parquet"))
if len(parts) < 70 or "history_manifest.json" not in old_assets:
    raise SystemExit("Incomplete release history assets")
if any(not a.get("digest", "").startswith("sha256:") for a in old_assets.values()):
    raise SystemExit("Unverified source checksum metadata")
ROOT.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True, exist_ok=False)
subprocess.run(["gh", "release", "download", SOURCE, "--repo", REPO, "--dir",
                str(DATA), "--pattern", "history-*.parquet", "--pattern",
                "history_manifest.json"], check=True)
if {p.name for p in DATA.iterdir()} != set(old_assets):
    raise SystemExit("Downloaded set inconsistent with source release")
checks = {}
rows = {}
import pyarrow.parquet as pq
for name, a in sorted(old_assets.items()):
    path = DATA / name
    h = digest(path)
    if path.stat().st_size != a["size"] or h != a["digest"].split(":", 1)[1]:
        raise SystemExit("Asset failed identity verification: " + name)
    checks[name] = {"sha256": h, "bytes": path.stat().st_size, "source_id": a["id"]}
    if name.endswith(".parquet"):
        metadata = pq.ParquetFile(path).metadata
        if not metadata.num_rows or not metadata.num_columns:
            raise SystemExit("Missing historical content: " + name)
        rows[name] = metadata.num_rows
json.loads((DATA / "history_manifest.json").read_text())
new_release, new_assets = release_state()
if identity(old_assets) != identity(new_assets) or old_release["id"] != new_release["id"]:
    raise SystemExit("Source changed during verification")
archive = ROOT / "canonical-history.tar"
with tarfile.open(archive, "w") as tar:
    for name in sorted(old_assets):
        tar.add(DATA / name, arcname="history/" + name, recursive=False)
proof = {
    "status": "source_verified",
    "source_release": SOURCE,
    "source_release_id": old_release["id"],
    "created_at": datetime.now(timezone.utc).isoformat(),
    "partition_count": len(parts),
    "row_count": sum(rows.values()),
    "asset_count": len(old_assets),
    "per_year_rows": rows,
    "sha256": checks,
    "archive_sha256": digest(archive),
    "archive_bytes": archive.stat().st_size,
    "private": True,
    "production_changed": False,
}
evidence = ROOT / "proof.json"
evidence.write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n")
target = json.loads(cmd("gh", "api", f"repos/{REPO}/branches/main"))["commit"]["sha"]
subprocess.run(["gh", "release", "create", BACKUP, str(archive), str(evidence),
                "--repo", REPO, "--target", target,
                "--title", "BlinQ immutable canonical snapshot " + BACKUP,
                "--notes", "Private read-only snapshot; evidence includes SHA256 and source IDs. Do not alter canonical."],
               check=True)
remote = ROOT / "readback"
remote.mkdir()
subprocess.run(["gh", "release", "download", BACKUP, "--repo", REPO,
                "--dir", str(remote)], check=True)
if digest(remote / archive.name) != proof["archive_sha256"]:
    raise SystemExit("Remote backup digest mismatch")
if (remote / evidence.name).read_bytes() != evidence.read_bytes():
    raise SystemExit("Remote evidence mismatch")
with tarfile.open(remote / archive.name) as tar:
    names = sorted(tar.getnames())
    if names != sorted("history/" + n for n in checks):
        raise SystemExit("Remote archive member mismatch")
    for name in sorted(checks):
        member = tar.extractfile("history/" + name)
        if member is None:
            raise SystemExit("Missing archived member " + name)
        h = hashlib.sha256()
        for block in iter(lambda: member.read(1 << 20), b""):
            h.update(block)
        if h.hexdigest() != checks[name]["sha256"]:
            raise SystemExit("Remote archived digest mismatch " + name)
print(json.dumps({"status": "VERIFIED", "source": SOURCE, "backup_tag": BACKUP,
                  "partitions": len(parts), "rows": sum(rows.values()),
                  "persisted_readback": "PASS"}))
