"""Freeze and independently restore every input before one isolated model candidate fit.

This is deliberately NOT a generic backup of an arbitrary mutable local folder.
Sources are the checksum-verified private canonical/model/prior releases and the
pinned rank-history sources used by the live training pipeline.  Large bytes are
kept in a unique never-clobbered PRIVATE GitHub release.  No Tennis API calls.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from _bootstrap import ROOT
from release_store import ReleaseStore
from rank_feature_inputs import load_rank_feature_inputs
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.models.artifact import load_model
from verify_champion_rollback import verify_complete_bundle, verify_restore

BASE = ROOT / ".cache/tbt"
SUBDIRS = (
    "history", "production", "atp-leaderboards", "wta-season-stats",
    "rank-feature-inputs/source", "rank-feature-inputs/profiles",
    "training-source-metadata", "training-backup/source-code",
)
CERT = BASE / "training-backup/verified-certificate.json"
ASSET_MANIFEST = "frozen_inputs_manifest.json"
REPO = "BackstageTalks/tbt-data"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(*argv):
    p = subprocess.run(argv, capture_output=True, text=True)
    if p.returncode:
        detail = (p.stderr or p.stdout or "no diagnostic output").strip()
        raise RuntimeError(
            f"Command failed (exit {p.returncode}) "
            f"{' '.join(map(str, argv[:3]))}: {detail[:1200]}"
        )
    return p.stdout.strip()


def verify_job_identity():
    if (os.environ.get("GITHUB_REPOSITORY") != "BackstageTalks/tbt"
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or not os.environ.get("GH_TOKEN")
            or not os.environ.get("GITHUB_RUN_ID")
            or not os.environ.get("GITHUB_RUN_ATTEMPT")
            or not re.fullmatch(r"[0-9a-f]{40}", os.environ.get("GITHUB_SHA", ""))):
        raise RuntimeError("Private GitHub Actions run identity/permission required")
    if os.environ.get("TBT_DATA_REPOSITORY", REPO) != REPO:
        raise RuntimeError("Unexpected private CDB repository")
    from cdb_global_writer_lock import verify
    verify(REPO, ROOT / ".cdb-global-writer-lock.json")
    if run("gh", "repo", "view", REPO, "--json", "visibility", "--jq", ".visibility") != "PRIVATE":
        raise RuntimeError("Immutable backups require a PRIVATE data repository")


def download_sources():
    ReleaseStore(REPO, "tbt-data-v1", BASE / "history").download(
        require_bundle_manifest=True)
    original = load_partitions(BASE / "history")
    matches, safety = sanitize_history_identities(original)
    if safety.get("changed") and safety.get("unresolved", 0):
        raise RuntimeError("Unresolved canonical identity audit before training")
    count = len(matches)
    if count < 500000:
        raise RuntimeError("Suspiciously small canonical model source")

    src = BASE / "production"
    champion_release = ReleaseStore(REPO, "tbt-model-production-v1", src)
    champion_release.download(
        extra_names=("model.joblib", "training_report.json", "promotion_history.json"),
        required_names=("model.joblib", "training_report.json", "promotion_history.json"),
        require_bundle_manifest=True)
    complete = verify_complete_bundle(src)
    champion = load_model(str(src / "model.joblib"))
    if not champion.fitted:
        raise RuntimeError("Production champion is not fitted")

    for tag, directory, filename in (
        ("tbt-atp-leaderboards-v1", "atp-leaderboards",
         "atp_leaderboards_1991_2026_52week_career.csv"),
        ("tbt-wta-season-stats-v1", "wta-season-stats",
         "wta_stats_2010_2026_serving_returning.csv"),
    ):
        # If the prior is absent the normal trainer omits it. Still require
        # a provable tag inventory so source discovery cannot fail open.
        names = ReleaseStore(REPO, tag, BASE / directory)._asset_names()
        if filename in names:
            ReleaseStore(REPO, tag, BASE / directory).download(
                extra_names=(filename,), required_names=(filename,),
                require_bundle_manifest=True)

    ranking = load_rank_feature_inputs(
        REPO, BASE / "rank-feature-inputs", matches)
    if ranking.report.get("status") != "verified":
        raise RuntimeError("Rank-history priors are not verified")

    metadata = BASE / "training-source-metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    for path, name in (
        ("research/source-acquisition/latest.json", "rank_source_acquisition.json"),
        ("audit/wta-official-ranking-supplement-2026-10-07.json", "wta_supplement_audit.json"),
    ):
        raw = run("gh", "api", "-H", "Accept: application/vnd.github.raw+json",
                  f"repos/{REPO}/contents/{path}?ref=main")
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise RuntimeError("Invalid frozen source-provenance metadata")
        (metadata / name).write_text(
            json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    code_root = BASE / "training-backup/source-code"
    code_root.mkdir(parents=True, exist_ok=True)
    source_tar = code_root / "blinq-git-source.tar.gz"
    run("git", "archive", "--format=tar.gz", "-o", str(source_tar),
        os.environ["GITHUB_SHA"])
    if source_tar.stat().st_size < 1000:
        raise RuntimeError("Source archive is unexpectedly small")
    return champion.version, count, complete["model.joblib"]["sha256"], ranking.report


def inventory():
    result = []
    used = set()
    for folder in SUBDIRS:
        base = BASE / folder
        if not base.is_dir():
            raise RuntimeError(f"Required input directory absent: {folder}")
        for file in sorted(x for x in base.rglob("*") if x.is_file()):
            rel = file.relative_to(BASE).as_posix()
            asset = "frozen__" + rel.replace("/", "__")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", asset):
                raise RuntimeError("Unsafe training backup asset name")
            if len(asset) > 230 or asset in used:
                raise RuntimeError("Input asset name collision or excessively long name")
            used.add(asset)
            if not file.stat().st_size:
                raise RuntimeError(f"Refusing empty training input: {rel}")
            result.append({"path": rel, "asset": asset,
                           "sha256": sha(file), "bytes": file.stat().st_size})
    parts = [x for x in result if re.fullmatch(r"history/history-\d{4}\.parquet", x["path"])]
    if len(parts) < 50:
        raise RuntimeError("Incomplete canonical training input partitions")
    required = {"history/history_manifest.json", "history/_tbt_bundle_manifest.json",
                "production/model.joblib", "production/_tbt_bundle_manifest.json",
                "rank-feature-inputs/source/sackmann-atp-rankings.tar.gz",
                "rank-feature-inputs/source/sackmann-wta-rankings.tar.gz",
                "rank-feature-inputs/profiles/player_profiles.json",
                "training-backup/source-code/blinq-git-source.tar.gz"}
    missing = required - {row["path"] for row in result}
    if missing:
        raise RuntimeError("Missing mandatory frozen training inputs: " + repr(sorted(missing)))
    return result


def ensure_unchanged(rows):
    for row in rows:
        path = BASE / row["path"]
        if (not path.is_file() or path.stat().st_size != row["bytes"]
                or sha(path) != row["sha256"]):
            raise RuntimeError("Canonical/prior/champion input changed: " + row["path"])



_TRANSIENT_UPLOAD = re.compile(
    r"(?:HTTP\s+(?:408|429|500|502|503|504)\b|connection reset|"
    r"timed?\s*out|timeout|temporary failure|TLS handshake|"
    r"unexpected EOF|EOF|rate limit)",
    re.IGNORECASE,
)


def _remote_backup_assets(tag):
    """Inspect actual release assets; a successful process exit is not proof."""
    payload = json.loads(run("gh", "release", "view", tag, "-R", REPO,
                             "--json", "assets"))
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("Invalid remote training backup inventory")
    found = {}
    for asset in assets:
        if not isinstance(asset, dict):
            raise RuntimeError("Invalid remote training backup asset")
        name, size = asset.get("name"), asset.get("size")
        if (not isinstance(name, str) or not name
                or isinstance(size, bool) or not isinstance(size, int)
                or size <= 0 or name in found):
            raise RuntimeError("Duplicate or invalid remote training backup asset")
        found[name] = size
    return found


def _check_remote_backup_assets(tag, expected, *, complete=False):
    found = _remote_backup_assets(tag)
    unexpected = set(found) - set(expected)
    mismatched = {
        name: (actual, expected[name])
        for name, actual in found.items()
        if name in expected and actual != expected[name]
    }
    if unexpected or mismatched:
        raise RuntimeError(
            "Immutable backup asset mismatch; refusing overwrite: "
            f"unexpected={sorted(unexpected)}, sizes={mismatched}"
        )
    if complete and found != expected:
        raise RuntimeError(
            "Incomplete remote immutable backup; missing assets: "
            + repr(sorted(set(expected) - set(found)))
        )
    return found


def _upload_one_immutable(tag, path, expected):
    """Recover uncertain uploads only after checking the remote asset by name/size.

    Never use --clobber. Equal remote size is provisional: the independent
    download and SHA-256 verification in prepare() is the definitive proof.
    """
    for attempt in range(5):
        if path.name in _check_remote_backup_assets(tag, expected):
            return
        try:
            run("gh", "release", "upload", tag, str(path), "-R", REPO)
            return
        except RuntimeError as exc:
            # The CLI can return nonzero after GitHub already stored the asset.
            if path.name in _check_remote_backup_assets(tag, expected):
                return
            if attempt == 4 or not _TRANSIENT_UPLOAD.search(str(exc)):
                raise
            delay = min(2 ** (attempt + 1), 16)
            print(
                f"Transient immutable backup upload failure "
                f"({path.name}, retry {attempt+2}/5 in {delay}s): {exc}",
                file=sys.stderr, flush=True,
            )
            time.sleep(delay)
    raise RuntimeError("Immutable backup upload attempts exhausted")


def upload_immutable_backup(tag, rows, stage):
    """Upload chunks, reconcile partial success, then commit the manifest last."""
    expected = {row["asset"]: int(row["bytes"]) for row in rows}
    if len(expected) != len(rows) or ASSET_MANIFEST in expected:
        raise RuntimeError("Duplicate/unsafe immutable backup asset names")
    manifest = stage / ASSET_MANIFEST
    if not manifest.is_file() or not manifest.stat().st_size:
        raise RuntimeError("Frozen backup manifest is missing/empty")
    paths = [stage / row["asset"] for row in rows]
    for offset in range(0, len(paths), 8):
        chunk = paths[offset:offset+8]
        remote = _check_remote_backup_assets(tag, expected)
        missing = [path for path in chunk if path.name not in remote]
        if not missing:
            continue
        try:
            run("gh", "release", "upload", tag, *map(str, missing), "-R", REPO)
        except RuntimeError as exc:
            # Multi-asset CLI uploads are not atomic. A subset can succeed even
            # when gh returns exit 1, so never blindly replay the batch.
            print(f"Immutable backup chunk partially failed; reconciling "
                  f"remote inventory: {exc}", file=sys.stderr, flush=True)
            for path in missing:
                _upload_one_immutable(tag, path, expected)
    _check_remote_backup_assets(tag, expected, complete=True)

    # Manifest is published only after all data files are present and sized.
    committed = {**expected, ASSET_MANIFEST: manifest.stat().st_size}
    _upload_one_immutable(tag, manifest, committed)
    _check_remote_backup_assets(tag, committed, complete=True)

def prepare():
    verify_job_identity()
    if CERT.exists():
        raise RuntimeError("Refusing previously generated certificate")
    version, matches, champion_digest, ranking_report = download_sources()
    rows = inventory()
    ensure_unchanged(rows)
    tag = ("blinq-full-training-backup-" + os.environ["GITHUB_RUN_ID"] +
           "-" + os.environ["GITHUB_RUN_ATTEMPT"])
    stage = BASE / "training-backup/staging"
    restore = BASE / "training-backup/independent-readback"
    if stage.exists() or restore.exists():
        raise RuntimeError("Backup staging/readback unexpectedly exists")
    stage.mkdir(parents=True)
    restore.mkdir(parents=True)

    for item in rows:
        shutil.copyfile(BASE / item["path"], stage / item["asset"])
        if sha(stage / item["asset"]) != item["sha256"]:
            raise RuntimeError("Backup staging differs from pinned source")
    manifest = {
        "schema": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "application_sha": os.environ["GITHUB_SHA"], "backup_tag": tag,
        "champion_version": version, "champion_sha256": champion_digest,
        "canonical_matches": matches, "rank_input_report": ranking_report,
        "files": rows,
        "policy": "Non-overwriting complete input source snapshot; no provider requests; no promotion",
    }
    (stage / ASSET_MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8")

    # Strict never-clobber: a retry uses a fresh tag with its run attempt.
    # A partially uploaded release is never accepted as completed.
    probe = subprocess.run(["gh", "release", "view", tag, "-R", REPO],
                           capture_output=True, text=True)
    if probe.returncode == 0 or (
        probe.returncode != 0 and "404" not in probe.stderr and
        "not found" not in probe.stderr.lower()):
        raise RuntimeError("Backup tag already exists or its state cannot be established")
    run("gh", "release", "create", tag, "-R", REPO, "--latest=false",
        "--title", "BlinQ immutable complete per-run training backup",
        "--notes", "Verified independent remote input readback required before any candidate fit.")
    upload_immutable_backup(tag, rows, stage)

    run("gh", "release", "download", tag, "-R", REPO, "-D", str(restore))
    if sha(restore / ASSET_MANIFEST) != sha(stage / ASSET_MANIFEST):
        raise RuntimeError("Independent backup manifest remote readback mismatch")
    for row in rows:
        file = restore / row["asset"]
        if (not file.is_file() or file.stat().st_size != row["bytes"]
                or sha(file) != row["sha256"]):
            raise RuntimeError("Independent remote backup SHA mismatch: " + row["path"])

    restored_champion = BASE / "training-backup/isolated-champion"
    restored_champion.mkdir(parents=True, exist_ok=False)
    for name in ("model.joblib", "training_report.json", "promotion_history.json",
                 "_tbt_bundle_manifest.json"):
        shutil.copyfile(restore / ("frozen__production__" + name), restored_champion / name)
    rollback = verify_restore(BASE / "production", restored_champion, version)
    if rollback.get("status") != "PASS" or rollback.get("max_prediction_difference") != 0:
        raise RuntimeError("Champion isolated restoration/prediction parity failed")
    ensure_unchanged(rows)
    verify_job_identity()

    cert = {"schema": 1, "status": "VERIFIED_FULL_INPUTS_AND_ISOLATED_RESTORE",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "application_sha": os.environ["GITHUB_SHA"], "backup_tag": tag,
            "candidate_tag": "blinq-candidate-frozen-" + os.environ["GITHUB_RUN_ID"] +
                             "-" + os.environ["GITHUB_RUN_ATTEMPT"],
            "champion_version": version, "champion_sha256": champion_digest,
            "remote_manifest_sha256": sha(restore / ASSET_MANIFEST),
            "all_assets_remotely_verified": len(rows) + 1,
            "input_rows": rows, "champion_restore": rollback,
            "canonical_matches": matches, "provider_requests": 0,
            "production_mutated": False, "canonical_mutated": False}
    CERT.parent.mkdir(parents=True, exist_ok=True)
    CERT.write_text(json.dumps(cert, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    validate_certificate()
    print(json.dumps({"status": cert["status"], "backup_tag": tag,
                      "asset_count": len(rows)+1, "canonical_matches": matches,
                      "candidate_tag": cert["candidate_tag"]}), flush=True)
    return cert


def validate_certificate():
    if not CERT.is_file():
        raise RuntimeError("Missing independently verified immutable backup certificate")
    verify_job_identity()
    cert = json.loads(CERT.read_text(encoding="utf-8"))
    if (cert.get("schema") != 1
            or cert.get("status") != "VERIFIED_FULL_INPUTS_AND_ISOLATED_RESTORE"
            or cert.get("run_id") != os.environ["GITHUB_RUN_ID"]
            or cert.get("attempt") != os.environ["GITHUB_RUN_ATTEMPT"]
            or cert.get("application_sha") != os.environ["GITHUB_SHA"]
            or cert.get("provider_requests") != 0
            or cert.get("production_mutated") is not False
            or cert.get("canonical_mutated") is not False):
        raise RuntimeError("Invalid run-bound training backup certificate")
    expected = ("blinq-full-training-backup-" + os.environ["GITHUB_RUN_ID"] +
                "-" + os.environ["GITHUB_RUN_ATTEMPT"])
    candidate_tag = ("blinq-candidate-frozen-" + os.environ["GITHUB_RUN_ID"] +
                     "-" + os.environ["GITHUB_RUN_ATTEMPT"])
    if cert.get("backup_tag") != expected or cert.get("candidate_tag") != candidate_tag:
        raise RuntimeError("Backup and candidate tags are not tied to this run")
    rows = cert.get("input_rows")
    if not isinstance(rows, list) or len(rows) < 65:
        raise RuntimeError("Incomplete full input backup certificate")
    names = [x.get("path") for x in rows if isinstance(x, dict)]
    if len(names) != len(rows) or len(set(names)) != len(names):
        raise RuntimeError("Duplicate or invalid backed up input entries")
    ensure_unchanged(rows)
    if not cert.get("remote_manifest_sha256") or cert.get("all_assets_remotely_verified") != len(rows)+1:
        raise RuntimeError("Independent remote readback is not certified")
    restored = cert.get("champion_restore") or {}
    if (restored.get("status") != "PASS"
            or restored.get("max_prediction_difference") != 0
            or restored.get("expected_champion_version") != cert.get("champion_version")
            or restored.get("bundle_files", {}).get("model.joblib", {}).get("sha256") != cert.get("champion_sha256")):
        raise RuntimeError("No independently restored exact serving champion")
    if (BASE / "production/model.joblib").is_file() and sha(BASE / "production/model.joblib") != cert["champion_sha256"]:
        raise RuntimeError("Production model drift since backup")
    return cert


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("prepare", "verify"))
    args = ap.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        cert = validate_certificate()
        print(json.dumps({"status": "VERIFIED", "backup_tag": cert["backup_tag"],
                          "candidate_tag": cert["candidate_tag"]}))


if __name__ == "__main__":
    main()
