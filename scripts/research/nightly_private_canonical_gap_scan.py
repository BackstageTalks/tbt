#!/usr/bin/env python3
"""Scan all private tbt-data source manifests, and test unmerged candidate facts
against the CURRENT canonical in a read-only importer. Publish only PRIVATE audit.
This job has zero provider calls and cannot publish history partitions or models.
"""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone

REPO = "BackstageTalks/tbt-data"
BACKUP_TAG = "blinq-canonical-backup-37864914634"
PREFIX = "research/offline-sources/blinq-import-2026-10-07/chunks/"
WORK = Path(".cache/tbt/autonomous-data-gap")
WORK.mkdir(parents=True, exist_ok=True)
SOURCE = WORK / "sources"
SOURCE.mkdir(parents=True, exist_ok=True)

def cmd(*parts, binary=False):
    args = list(map(str, parts))
    if binary:
        return subprocess.check_output(args)
    return subprocess.check_output(args, text=True).strip()

def js(*args):
    return json.loads(cmd("gh", "api", *args))

def sha(data):
    return hashlib.sha256(data).hexdigest()

def raw(path):
    endpoint = f"repos/{REPO}/contents/{path}?ref=main"
    value = cmd("gh", "api", "-H", "Accept: application/vnd.github.raw", endpoint, binary=True)
    if value[:1] == b"{" and b'"encoding"' in value[:300]:
        try:
            payload = json.loads(value)
            if payload.get("encoding") == "base64":
                return base64.b64decode(payload["content"])
        except (ValueError, KeyError):
            pass
    return value

def release_history():
    info = js(f"repos/{REPO}/releases/tags/tbt-data-v1")
    return {x["name"]: (x["id"], x["size"], x.get("digest")) for x in info["assets"]
            if (x["name"].startswith("history-") and x["name"].endswith(".parquet"))
            or x["name"] == "history_manifest.json"}

def verify_backup():
    data = WORK / "backup"
    data.mkdir(exist_ok=True)
    subprocess.run(["gh", "release", "download", BACKUP_TAG, "--repo", REPO,
                    "--pattern", "proof.json", "--dir", str(data)], check=True)
    proof = json.loads((data / "proof.json").read_text())
    if proof.get("status") != "source_verified" or not proof.get("private"):
        raise SystemExit("No verified private snapshot available")
    identity = release_history()
    expected = {name: (v["source_id"], v["bytes"], "sha256:" + v["sha256"])
                for name, v in proof["sha256"].items()}
    if identity != expected:
        raise SystemExit("Production history changed after backup: new backup required before import")
    return proof

def inventory():
    tree = js(f"repos/{REPO}/git/trees/main?recursive=1")
    blobs = [x for x in tree.get("tree", []) if x.get("type") == "blob"]
    categories = Counter()
    candidate = []
    known_ext = (".csv", ".csv.gz", ".jsonl", ".jsonl.gz", ".parquet",
                 ".zip", ".xlsx", ".tar.gz", ".xz", ".b64", ".txt")
    for f in blobs:
        path = f["path"]
        low = path.lower()
        if low.startswith("audit/") or low.startswith("backup/"):
            categories["audit_backup_files"] += 1
            continue
        if low.endswith(known_ext) or ".b64.part" in low:
            if "pointbypoint" in low or "pbp" in low or "serve" in low:
                kind = "ptp_or_match_stats"
            elif any(k in low for k in ("odds", "market", "clv", "valuebet")):
                kind = "market_timing_unverified"
            elif "rank" in low or "elo" in low:
                kind = "rank_or_rating_history"
            elif any(k in low for k in ("charting", "wimbledon", "livetennis")):
                kind = "charting_or_points"
            elif "offline-sources" in low:
                kind = "offline_source_candidate"
            elif "player" in low:
                kind = "player_crosswalk"
            else:
                kind = "research_other"
            categories[kind] += 1
            candidate.append({"path": path, "bytes": f.get("size", 0),
                              "git_blob_sha": f.get("sha"), "category": kind})
    if tree.get("truncated"):
        raise SystemExit("Git tree inventory truncated; cannot claim full repository coverage")
    return {"tree_blob_count": len(blobs), "categories": dict(categories),
            "candidate_count": len(candidate), "candidates": candidate}

def reconstruct_sources():
    manifest = json.loads(raw(PREFIX + "manifest.json"))
    results = {}
    for name, entry in sorted(manifest["files"].items()):
        parts = entry["parts"]
        joined = b"".join(raw(PREFIX + name_part).strip() for name_part in parts)
        uncompressed = gzip.decompress(base64.b64decode(joined))
        if len(uncompressed) != entry["bytes"] or sha(uncompressed) != entry["sha256"]:
            raise SystemExit("Source checksum mismatch " + name)
        target = SOURCE / name
        target.write_bytes(uncompressed)
        with target.open("rb") as f:
            rows = sum(chunk.count(b"\n") for chunk in iter(lambda: f.read(1048576), b"")) - 1
        results[name] = {"rows": rows, "sha256": sha(uncompressed),
                         "bytes": len(uncompressed), "verified": True}
    return results

def save_private(path, report):
    payload = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True).encode()
    body = {"message": "audit: autonomous canonical gap comparison of repo sources",
            "content": base64.b64encode(payload).decode()}
    existing = subprocess.run(["gh", "api", f"repos/{REPO}/contents/{path}"],
                              capture_output=True, text=True)
    if existing.returncode == 0:
        body["sha"] = json.loads(existing.stdout)["sha"]
    elif "404" not in existing.stderr:
        raise RuntimeError("Cannot safely determine audit target state")
    request = WORK / "private_audit_put.json"
    request.write_text(json.dumps(body))
    cmd("gh", "api", "--method", "PUT", f"repos/{REPO}/contents/{path}",
        "--input", str(request))

def main():
    if not os.environ.get("GH_TOKEN") or not js(f"repos/{REPO}").get("private"):
        raise SystemExit("Private source permissions required")
    result = {"schema": 1, "status": "running", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "private_destination": REPO, "provider_requests": 0,
              "canonical_mutated": False, "model_promoted": False,
              "backup_tag": BACKUP_TAG, "run_id": os.environ.get("GITHUB_RUN_ID")}
    target = f"audit/autonomous-canonical-gap-{os.environ['GITHUB_RUN_ID']}.json"
    try:
        proof = verify_backup()
        result["canonical_backup"] = {"status": "verified", "rows": proof["row_count"],
                                       "history_partitions": proof["partition_count"],
                                       "asset_count": proof["asset_count"]}
        result["inventory"] = inventory()
        result["source_manifests"] = reconstruct_sources()
        directory = WORK / "canonical"
        from release_store import ReleaseStore
        store = ReleaseStore(REPO, "tbt-data-v1", directory)
        store.download(require_bundle_manifest=True)
        from tbt.data.history_snapshot import load_partitions
        from tbt.data.history_safety import sanitize_history_identities
        matches, safety = sanitize_history_identities(load_partitions(directory))
        if safety.get("quarantined_rows"):
            raise SystemExit("Current canonical has identity quarantine")
        count = len(matches)
        result["current_canonical_rows"] = count
        del matches
        from subprocess import run
        cli = [sys.executable, "scripts/import_blinq_offline_bundle.py",
               "--history-dir", str(directory),
               "--futures-csv", str(SOURCE / "blinq_atp_futures_quali_2018_2026.csv"),
               "--charting-csv", str(SOURCE / "blinq_charting_atp_core_features.csv"),
               "--charting-csv", str(SOURCE / "blinq_charting_wta_core_features.csv"),
               "--out-dir", str(WORK / "reconciliation")]
        child = run(cli, capture_output=True, text=True)
        if child.returncode:
            raise RuntimeError("Conservative importer dry-run failed: " + child.stderr[-1600:])
        report = json.loads((WORK / "reconciliation" / "report.json").read_text())
        result["canonical_candidate_dry_run"] = report
        result["candidate_interpretation"] = (
            "Projections not production writes. New source matches require "
            "current-release duplicate crosswalk and identity/level/licensing review; "
            "only unique missing factual fields can be promoted.")
        result["status"] = "inventory_and_current_canonical_dry_run_complete"
    except Exception as exc:
        result["status"] = "failed_or_safety_blocked"
        result["error"] = str(exc)[:2000]
        raise
    finally:
        result["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        save_private(target, result)
        print(json.dumps({"status": result["status"], "private_report": target,
                          "canonical_rows": result.get("current_canonical_rows"),
                          "source_files": len(result.get("source_manifests", {})),
                          "provider_requests": 0, "canonical_changed": False}))

if __name__ == "__main__":
    main()
