#!/usr/bin/env python3
"""Guarded publication of SOURCE-NATIVE Charting observations into tbt-data-v1.

This is NOT a writer for whole-match statistics. Must run inside an authorized
GitHub Actions writer job holding the existing global annotated-tag CDB lock.
Never changes history-* partitions or their original bundle manifest entries.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

DATA_REPO = "BackstageTalks/tbt-data"
TAG = "tbt-data-v1"
MANIFEST = "charting-observations-manifest-v1.json"
EXPECTED_SOURCE = {
    "atp": ("92d6975a09ebc0f5bf42d68a34e57087152e9219d8430d7794faa68b0c5630f8", 15129),
    "wta": ("cf1ec57c55cda20cd43a2848e30369b4c829486f618605c9a369a22fa3fdd315", 8506),
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stage_check(directory: Path) -> tuple[dict, list[Path]]:
    directory = directory.resolve()
    p = directory / MANIFEST
    if p.is_symlink() or not p.is_file():
        raise ValueError("Stage manifest missing or symlinked")
    m = json.loads(p.read_text(encoding="utf-8"))
    if not (m.get("namespace") == "charting_observations/v1"
            and m.get("source_total_matches") == 11822
            and m.get("total_source_rows") == 23635
            and m.get("total_source_native_rows") == 23618
            and m.get("total_quarantined_rows") == 17
            and m.get("fields_preserved_nonempty") == 7315237
            and m.get("canonical_event_join_approved") is False
            and m.get("canonical_statistics_changed") is False
            and m.get("canonical_history_partitions_modified") is False
            and m.get("training_model_eligible") is False
            and m.get("provider_api_requests") == 0
            and set(m.get("assets", {})) == set(EXPECTED_SOURCE)):
        raise ValueError("Untrusted or changed source-native Charting stage")
    paths = [p]
    for tour, (source_hash, count) in EXPECTED_SOURCE.items():
        entry = m["assets"][tour]
        filename = f"charting-observations-{tour}-v1.jsonl.gz"
        path = directory / filename
        if entry.get("name") != filename or not path.is_file() or path.is_symlink():
            raise ValueError("Unexpected source observation asset")
        if entry.get("source_csv_sha256") != source_hash or entry.get("rows") != count:
            raise ValueError("Source input version drift")
        if path.stat().st_size != entry.get("bytes") or sha(path) != entry.get("sha256"):
            raise ValueError("Source sidecar byte/hash mismatch")
        observed = 0
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                observed += 1
                if not (row.get("tour") == tour
                        and row.get("source_csv_sha256") == source_hash
                        and row.get("canonical_match_id") is None
                        and row.get("canonical_player_id") is None
                        and row.get("independent_provider_event_identity") is False
                        and row.get("canonical_write_allowed") is False
                        and row.get("whole_match_stats_eligible") is False
                        and row.get("prediction_training_allowed") is False
                        and row.get("available_at") is None
                        and row.get("observation_scope") == "charted_point_sample_unknown_completeness"):
                    raise ValueError("Source observation crosses canonical/training boundary")
        if observed != count:
            raise ValueError("Source observation row count drift")
        paths.append(path)
    return m, paths


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True)


def release() -> dict:
    return json.loads(gh("api", f"repos/{DATA_REPO}/releases/tags/{TAG}"))


def assets_of(r: dict) -> dict:
    return {x["name"]: (x["id"], x["digest"], x["size"]) for x in r["assets"]}


def download(name: str, directory: Path) -> Path:
    gh("release", "download", TAG, "-R", DATA_REPO, "-p", name, "-D", str(directory))
    return directory / name


def perform(directory: Path, backup: Path, readback: Path, *, write: bool) -> dict:
    m, paths = stage_check(directory)
    if not write:
        return {"status": "VERIFIED_STAGE_ONLY", "rows": m["total_source_rows"], "canonical_writes": 0}
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("GITHUB_REPOSITORY") != "BackstageTalks/tbt":
        raise ValueError("Production publication requires approved BackstageTalks/tbt GitHub Actions runner")
    if not os.getenv("GH_TOKEN"):
        raise ValueError("Missing authorized private data repository token")
    from cdb_global_writer_lock import verify
    from release_store import ReleaseStore
    verify(DATA_REPO, Path(".cdb-global-writer-lock.json"))
    backup.mkdir(parents=True, exist_ok=True)
    readback.mkdir(parents=True, exist_ok=True)
    old = release()
    original_assets = assets_of(old)
    original_hist = {k: v for k, v in original_assets.items()
                     if k.startswith("history-") and k.endswith(".parquet")}
    if len(original_hist) < 65:
        raise ValueError("Missing historical partitions in canonical release")
    existing = [p.name for p in paths if p.name in original_assets]
    if existing:
        raise ValueError("Refuse clobbering or silently reusing existing Charting CDB sidecars")
    before_manifest = download("_tbt_bundle_manifest.json", backup)
    before_history = download("history_manifest.json", backup)
    if sha(before_manifest) != original_assets[before_manifest.name][1].removeprefix("sha256:"):
        raise ValueError("Prewrite bundle manifest SHA mismatch")
    original_bundle = json.loads(before_manifest.read_text(encoding="utf-8"))
    if original_bundle["files"]["history_manifest.json"]["sha256"] != sha(before_history):
        raise ValueError("Prewrite history manifest SHA mismatch")
    (backup / "original-release-assets.json").write_text(
        json.dumps({k: list(v) for k, v in original_assets.items()}, sort_keys=True, indent=2))
    # Immutable, independently downloadable prewrite receipt is mandatory.
    audit_tag = f"blinq-charting-prewrite-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
    sha_file = backup / "SHA256SUMS"
    sha_file.write_text("".join(f"{sha(f)}  {f.name}\n" for f in
                                (before_manifest, before_history, backup / "original-release-assets.json")))
    gh("release", "create", audit_tag, str(before_manifest), str(before_history),
       str(backup / "original-release-assets.json"), str(sha_file), "-R", DATA_REPO,
       "--title", "BlinQ Charting CDB prewrite manifest and history digests",
       "--notes", "Immutable prewrite checkpoint for source-native add-only publication.")
    # Independently read back immutable prewrite backup before any CDB publication.
    backup_readback = backup / "immutable-readback"
    backup_readback.mkdir(exist_ok=True)
    gh("release", "download", audit_tag, "-R", DATA_REPO, "-D", str(backup_readback))
    for line in sha_file.read_text(encoding="utf-8").splitlines():
        expected_hash, name = line.split("  ", 1)
        restored = backup_readback / name
        if not restored.is_file() or sha(restored) != expected_hash:
            raise ValueError("Prewrite backup SHA-256 readback mismatch: " + name)
    # Fail closed if any asset has changed, including a non-history sidecar.
    def cas():
        verify(DATA_REPO, Path(".cdb-global-writer-lock.json"))
        if assets_of(release()) != original_assets:
            raise ValueError("CDB release drift detected before upload")
    # Preserve a separate copy of the old bundle manifest; upload_bundle edits its own local copy.
    writer_dir = backup / "writer"
    writer_dir.mkdir(exist_ok=True)
    ReleaseStore(DATA_REPO, TAG, writer_dir).upload_bundle(paths, before_upload=cas)
    current = release()
    current_assets = assets_of(current)
    if any(current_assets.get(k) != v for k, v in original_assets.items() if k != "_tbt_bundle_manifest.json"):
        raise ValueError("Canonical or existing release asset changed during Charting sidecar append")
    post_bundle = download("_tbt_bundle_manifest.json", readback)
    new_bundle = json.loads(post_bundle.read_text(encoding="utf-8"))
    for key, value in original_bundle["files"].items():
        if new_bundle["files"].get(key) != value:
            raise ValueError("Existing CDB bundle inventory mutated")
    for local in paths:
        remote = download(local.name, readback)
        if sha(remote) != sha(local) or current_assets[local.name][1] != "sha256:" + sha(local):
            raise ValueError("Independent CDB remote sidecar SHA readback failed")
        if new_bundle["files"][local.name]["sha256"] != sha(local):
            raise ValueError("CDB bundle manifest omitted or altered new source sidecar")
    if sha(download("history_manifest.json", readback)) != sha(before_history):
        raise ValueError("Canonical history manifest changed")
    return {"status": "VERIFIED_CDB_SOURCE_NATIVE_SIDECARS",
            "source_rows": m["total_source_rows"], "usable_native_rows": m["total_source_native_rows"],
            "quarantine_rows": m["total_quarantined_rows"], "original_nonempty_fields": m["fields_preserved_nonempty"],
            "year_assets_untouched": len(original_hist), "new_release_sidecar_assets": len(paths),
            "canonical_writes": 0, "model_promoted": False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage-dir", type=Path, required=True)
    p.add_argument("--backup-dir", type=Path, required=True)
    p.add_argument("--readback-dir", type=Path, required=True)
    p.add_argument("--mode", choices=["verify", "publish"], default="verify")
    a = p.parse_args()
    report = perform(a.stage_dir, a.backup_dir, a.readback_dir, write=a.mode == "publish")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
