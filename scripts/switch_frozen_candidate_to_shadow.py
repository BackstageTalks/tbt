"""One-time, auditable copy of the immutable 7.1.1 candidate into shadow ONLY.

No training, no canonical writes, no production promotion, no paid API calls.
Requires the shared CDB lock to avoid concurrent production refresh updates.
The complete prior shadow ledger and prior candidate are privately backed up
and SHA-read-back verified before touching the live candidate release.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from _bootstrap import ROOT  # noqa: F401
from cdb_global_writer_lock import verify as verify_global_lock
from release_store import ReleaseStore
from tbt.models.artifact import load_model
from tbt.services.shadow_evaluation import build_shadow_report

REPOSITORY = "BackstageTalks/tbt-data"
FROZEN_TAG = "blinq-candidate-frozen-38608660910-1"
PRODUCTION_TAG = "tbt-model-production-v1"
CANDIDATE_TAG = "tbt-model-candidate-v1"
SHADOW_TAG = "tbt-model-shadow-v1"
AUDIT_PATH = "audit/model-frozen-candidate-latest.json"
NEW_VERSION = "v201-20261014T183415325901Z"
OLD_VERSION = "v201-20261005T201258172391Z"
CHAMPION_VERSION = "v201-20260925T204608601094Z"
MODEL_SHA = "7ac60b0b671091a7f620cca80a7c558b417e20c9448f577878625447e565c141"
CHAMPION_SHA = "a96e61f1942a3ee9cd35f1e754b4981e420f26ba08049a66d65c00ae4f09c4a7"
CANDIDATE_FILES = ("model.joblib", "training_report.json", "promotion_history.json")
SHADOW_FILES = ("shadow_ledger.json", "shadow_report.json")
MANIFEST = "_tbt_bundle_manifest.json"


def call(*args: str) -> str:
    process = subprocess.run(args, capture_output=True, text=True, timeout=300)
    if process.returncode:
        raise RuntimeError("Command failed: " + " ".join(args[:4]) + " : " + process.stderr[:400])
    return process.stdout.strip()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def release(tag: str) -> dict:
    result = json.loads(call("gh", "api", f"repos/{REPOSITORY}/releases/tags/{tag}"))
    if result.get("draft") or not result.get("assets"):
        raise RuntimeError(f"Private release missing or empty: {tag}")
    return result


def inventory(tag: str) -> dict:
    return {
        asset["name"]: (int(asset["id"]), int(asset["size"]), str(asset.get("digest") or ""))
        for asset in release(tag)["assets"]
    }


def require_unchanged(tag: str, expected: dict) -> None:
    observed = inventory(tag)
    if observed != expected:
        raise RuntimeError(f"Concurrent release modification; no safe write to {tag}")


def checked_model(path: Path, version: str, expected_sha: str) -> None:
    if digest(path) != expected_sha:
        raise RuntimeError(f"Binary SHA mismatch for {version}")
    model = load_model(str(path))
    if not bool(model.fitted) or model.version != version:
        raise RuntimeError(f"Incorrect or unfitted candidate: {version}")


def backup_before_switch(folder: Path, candidate: Path, shadow: Path, tag: str) -> dict:
    """Snapshot every mutable source byte to never-clobbered private release."""
    current = folder / "backup-upload"
    current.mkdir()
    assets = {}
    for prefix, src, names in (
        ("old_candidate", candidate, (*CANDIDATE_FILES, MANIFEST)),
        ("old_shadow", shadow, (*SHADOW_FILES, MANIFEST)),
    ):
        for name in names:
            dst = current / f"{prefix}__{name}"
            shutil.copyfile(src / name, dst)
            assets[dst.name] = {"sha256": digest(dst), "bytes": dst.stat().st_size}
    proof = {
        "schema": 1,
        "source_tags": [CANDIDATE_TAG, SHADOW_TAG],
        "backup_tag": tag,
        "previous_shadow_version": OLD_VERSION,
        "new_shadow_version": NEW_VERSION,
        "files": assets,
    }
    (current / "SHA256_MANIFEST.json").write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n")
    call("gh", "release", "create", tag, "-R", REPOSITORY,
         "--latest=false", "--title", f"BlinQ verified prior shadow {tag}",
         "--notes", "Immutable rollback of previous shadow candidate and complete ledger. Never clobber.")
    call("gh", "release", "upload", tag, *[str(p) for p in current.iterdir()], "-R", REPOSITORY)
    copied = folder / "backup-readback"
    copied.mkdir()
    call("gh", "release", "download", tag, "-R", REPOSITORY, "-D", str(copied))
    if json.loads((copied / "SHA256_MANIFEST.json").read_text()) != proof:
        raise RuntimeError("Private rollback manifest readback mismatch")
    for name, meta in assets.items():
        f = copied / name
        if not f.exists() or f.stat().st_size != meta["bytes"] or digest(f) != meta["sha256"]:
            raise RuntimeError(f"Private rollback checksum readback failed: {name}")
    print(json.dumps({"rollback_backup": tag, "remote_files_verified": len(assets) + 1}), flush=True)
    return proof


def main() -> None:
    if (os.getenv("GITHUB_REPOSITORY") != "BackstageTalks/tbt"
            or os.getenv("GITHUB_REF") != "refs/heads/ops/blinq-shadow-711-switch-20261014"
            or not os.getenv("GH_TOKEN")
            or not os.getenv("GITHUB_RUN_ID")
            or not os.getenv("GITHUB_RUN_ATTEMPT")):
        raise RuntimeError("Only the approved one-time protected Actions run may switch shadow")
    if json.loads(call("gh", "repo", "view", REPOSITORY, "--json", "visibility"))["visibility"] != "PRIVATE":
        raise RuntimeError("Shadow artifacts must remain PRIVATE")
    verify_global_lock(REPOSITORY, Path(".cdb-global-writer-lock.json"))
    audit_payload = json.loads(call("gh", "api", f"repos/{REPOSITORY}/contents/{AUDIT_PATH}"))
    import base64
    evidence = json.loads(base64.b64decode(audit_payload["content"]))
    if (evidence.get("run_id") != "38608660910"
            or evidence.get("candidate_version") != NEW_VERSION
            or evidence.get("candidate_sha256") != MODEL_SHA
            or evidence.get("candidate_release_tag") != FROZEN_TAG
            or evidence.get("champion_version") != CHAMPION_VERSION
            or evidence.get("champion_sha256") != CHAMPION_SHA
            or evidence.get("model_promoted") is not False
            or evidence.get("backup_readback_verified") is not True
            or evidence.get("candidate_remote_readback_verified") is not True):
        raise RuntimeError("Frozen 7.1.1 audit does not match approved target")

    with TemporaryDirectory(prefix="blinq-shadow-switch-") as directory:
        folder = Path(directory)
        locations = {key: folder / key for key in ("production", "frozen", "candidate", "shadow")}
        tags = {"production": PRODUCTION_TAG, "frozen": FROZEN_TAG,
                "candidate": CANDIDATE_TAG, "shadow": SHADOW_TAG}
        for key, tag in tags.items():
            source = ReleaseStore(REPOSITORY, tag, locations[key])
            required = (("model.joblib",) if key == "production"
                        else CANDIDATE_FILES if key in ("frozen", "candidate")
                        else SHADOW_FILES)
            source.download(extra_names=required, required_names=required, require_bundle_manifest=True)
        checked_model(locations["production"] / "model.joblib", CHAMPION_VERSION, CHAMPION_SHA)
        checked_model(locations["frozen"] / "model.joblib", NEW_VERSION, MODEL_SHA)
        observed = inventory(CANDIDATE_TAG)
        shadow_inventory = inventory(SHADOW_TAG)
        existing = load_model(str(locations["candidate"] / "model.joblib"))
        previous = json.loads((locations["shadow"] / "shadow_report.json").read_text())
        ledger_bytes = (locations["shadow"] / "shadow_ledger.json").read_bytes()
        ledger = json.loads(ledger_bytes)
        if not isinstance(ledger, list):
            raise RuntimeError("Old shadow evidence is invalid")
        if previous.get("production_model_version") != CHAMPION_VERSION:
            raise RuntimeError("Unexpected active champion in shadow report")
        if existing.version == NEW_VERSION:
            if previous.get("challenger_model_version") != NEW_VERSION:
                raise RuntimeError("Partial previous switch: model updated but shadow report not updated")
            print(json.dumps({"status": "ALREADY_SWITCHED", "candidate": NEW_VERSION}), flush=True)
            return
        if (existing.version != OLD_VERSION
                or previous.get("challenger_model_version") != OLD_VERSION):
            raise RuntimeError("Shadow changed from approved prior version; refuse replacement")
        if inventory(PRODUCTION_TAG)["model.joblib"][2] not in ("", "sha256:" + CHAMPION_SHA):
            raise RuntimeError("Champion remote digest changed")
        new_report = build_shadow_report(ledger,
                                         production_model_version=CHAMPION_VERSION,
                                         challenger_model_version=NEW_VERSION)
        new_report.update({
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "initialized_waiting_for_first_pre_match_snapshot",
        })
        if new_report["cohort"]["captured"] != 0:
            raise RuntimeError("Unexpected pre-existing snapshots for supposedly new pair")

        backup_tag = "blinq-shadow-switch-backup-" + os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]
        backup_before_switch(folder, locations["candidate"], locations["shadow"], backup_tag)
        require_unchanged(CANDIDATE_TAG, observed)
        require_unchanged(SHADOW_TAG, shadow_inventory)
        verify_global_lock(REPOSITORY, Path(".cdb-global-writer-lock.json"))

        # A frozen candidate is not activated as production. Only the private
        # shadow release is switched; the old ledger remains byte-for-byte.
        ReleaseStore(REPOSITORY, CANDIDATE_TAG, locations["candidate"]).upload_bundle(
            [locations["frozen"] / name for name in CANDIDATE_FILES],
            before_upload=lambda: require_unchanged(CANDIDATE_TAG, observed),
        )
        next_report = locations["shadow"] / "shadow_report.json"
        next_report.write_text(json.dumps(new_report, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        ReleaseStore(REPOSITORY, SHADOW_TAG, locations["shadow"]).upload_bundle(
            [next_report], before_upload=lambda: require_unchanged(SHADOW_TAG, shadow_inventory),
        )

        # Independent remote readback; no cached upload files count as success.
        candidate_readback = folder / "candidate-readback"
        shadow_readback = folder / "shadow-readback"
        ReleaseStore(REPOSITORY, CANDIDATE_TAG, candidate_readback).download(
            extra_names=CANDIDATE_FILES, required_names=CANDIDATE_FILES, require_bundle_manifest=True)
        ReleaseStore(REPOSITORY, SHADOW_TAG, shadow_readback).download(
            extra_names=SHADOW_FILES, required_names=SHADOW_FILES, require_bundle_manifest=True)
        checked_model(candidate_readback / "model.joblib", NEW_VERSION, MODEL_SHA)
        if (shadow_readback / "shadow_ledger.json").read_bytes() != ledger_bytes:
            raise RuntimeError("Historical shadow ledger unexpectedly mutated")
        saved_report = json.loads((shadow_readback / "shadow_report.json").read_text())
        if (saved_report.get("production_model_version") != CHAMPION_VERSION
                or saved_report.get("challenger_model_version") != NEW_VERSION
                or saved_report.get("cohort", {}).get("captured") != 0):
            raise RuntimeError("Remote shadow report did not switch pair")
        checked_model(locations["production"] / "model.joblib", CHAMPION_VERSION, CHAMPION_SHA)
        if digest(locations["frozen"] / "model.joblib") != digest(candidate_readback / "model.joblib"):
            raise RuntimeError("Active shadow binary != immutable frozen candidate")
        if json.loads(base64.b64decode(json.loads(call(
                "gh", "api", f"repos/{REPOSITORY}/contents/{AUDIT_PATH}"))["content"])) != evidence:
            raise RuntimeError("Offline candidate evidence changed unexpectedly")
        print(json.dumps({
            "status": "SHADOW_SWITCH_VERIFIED",
            "candidate": NEW_VERSION, "champion": CHAMPION_VERSION,
            "candidate_sha256": MODEL_SHA,
            "old_candidate": OLD_VERSION,
            "historical_shadow_rows_preserved": len(ledger),
            "new_shadow_captured": 0,
            "offline_evidence_preserved": True,
            "backup_tag": backup_tag,
            "canonical_mutated": False, "production_mutated": False, "provider_requests": 0,
        }), flush=True)


if __name__ == "__main__":
    main()
