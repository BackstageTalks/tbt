from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import joblib

BUCKET = "tbt-models"
LEGACY_PRODUCTION_OBJECT = "production/model.joblib"
REPORT_PATH = Path("reports/champion_artifact_repair.json")


def _settings() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    return url, key


def _headers(key: str, content_type: str | None = None) -> dict[str, str]:
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _is_missing(response: httpx.Response) -> bool:
    if response.status_code == 404:
        return True
    if response.status_code != 400:
        return False
    body = (response.text or "").lower()
    return any(token in body for token in ("nosuchkey", "not_found", "object not found", '"statuscode":"404"'))


def _champion(client: httpx.Client, url: str, key: str) -> dict:
    response = client.get(
        f"{url}/rest/v1/model_versions",
        headers=_headers(key),
        params={
            "select": "model_version,lifecycle_status,promoted_at,created_at",
            "lifecycle_status": "eq.champion",
            "order": "promoted_at.desc.nullslast,created_at.desc",
            "limit": "1",
        },
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("No champion model is registered in model_versions")
    version = str(rows[0].get("model_version") or "").strip()
    if not version:
        raise RuntimeError("Champion row has no model_version")
    return rows[0]


def _object_url(base: str, object_path: str) -> str:
    encoded = quote(object_path, safe="/")
    return f"{base}/storage/v1/object/{BUCKET}/{encoded}"


def _download(client: httpx.Client, base: str, key: str, object_path: str) -> bytes | None:
    response = client.get(_object_url(base, object_path), headers=_headers(key))
    if _is_missing(response):
        return None
    if response.is_error:
        raise RuntimeError(
            f"Unable to download {BUCKET}/{object_path}: HTTP {response.status_code}: {response.text[:500]}"
        )
    return response.content


def _upload(client: httpx.Client, base: str, key: str, object_path: str, payload: bytes) -> None:
    response = client.post(
        _object_url(base, object_path),
        headers={**_headers(key, "application/octet-stream"), "x-upsert": "false"},
        content=payload,
    )
    if response.status_code in {200, 201}:
        return
    # A concurrent repair may have won the race. Caller verifies after upload.
    body = (response.text or "").lower()
    if response.status_code in {400, 409} and any(x in body for x in ("already exists", "duplicate", "resourcealreadyexists")):
        return
    raise RuntimeError(
        f"Unable to upload repaired artifact to {BUCKET}/{object_path}: HTTP {response.status_code}: {response.text[:500]}"
    )


def _artifact_version(payload: bytes) -> str:
    if not payload:
        raise RuntimeError("Artifact is empty")
    with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as handle:
        tmp = Path(handle.name)
        handle.write(payload)
    try:
        obj = joblib.load(tmp)
    finally:
        tmp.unlink(missing_ok=True)

    model = obj.get("model") if isinstance(obj, dict) else obj
    candidates = [
        getattr(model, "version", None),
        getattr(model, "model_version", None),
    ]
    if isinstance(obj, dict):
        metadata = obj.get("metadata")
        if isinstance(metadata, dict):
            candidates.extend([metadata.get("model_version"), metadata.get("version")])
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    raise RuntimeError("Unable to read model version from artifact")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_report(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def repair(*, dry_run: bool = False) -> dict:
    base, key = _settings()
    now = datetime.now(timezone.utc).isoformat()
    report: dict = {"generated_at": now, "bucket": BUCKET, "dry_run": dry_run}

    with httpx.Client(timeout=120.0) as client:
        champion = _champion(client, base, key)
        champion_version = str(champion["model_version"])
        versioned_object = f"versions/{champion_version}/model.joblib"
        report.update({
            "champion_version": champion_version,
            "versioned_object": versioned_object,
            "legacy_object": LEGACY_PRODUCTION_OBJECT,
        })

        current = _download(client, base, key, versioned_object)
        if current is not None:
            embedded = _artifact_version(current)
            if embedded != champion_version:
                raise RuntimeError(
                    f"Existing versioned artifact mismatch: embedded={embedded}, champion={champion_version}"
                )
            report.update({
                "status": "HEALTHY",
                "action": "none",
                "embedded_version": embedded,
                "sha256": _sha256(current),
                "bytes": len(current),
            })
            _write_report(report)
            print(json.dumps(report, indent=2))
            return report

        legacy = _download(client, base, key, LEGACY_PRODUCTION_OBJECT)
        if legacy is None:
            raise RuntimeError(
                f"Champion artifact is missing at {versioned_object}, and fallback {LEGACY_PRODUCTION_OBJECT} is also missing"
            )

        embedded = _artifact_version(legacy)
        report["fallback_embedded_version"] = embedded
        report["fallback_sha256"] = _sha256(legacy)
        report["fallback_bytes"] = len(legacy)

        if embedded != champion_version:
            report.update({"status": "REFUSED", "action": "none", "reason": "fallback_version_mismatch"})
            _write_report(report)
            raise RuntimeError(
                "Refusing champion repair because legacy production artifact does not match database champion: "
                f"embedded={embedded}, champion={champion_version}"
            )

        if dry_run:
            report.update({"status": "DRY_RUN_OK", "action": "would_restore_versioned_artifact"})
            _write_report(report)
            print(json.dumps(report, indent=2))
            return report

        _upload(client, base, key, versioned_object, legacy)
        repaired = _download(client, base, key, versioned_object)
        if repaired is None:
            raise RuntimeError("Repair upload completed but versioned artifact is still missing")
        repaired_version = _artifact_version(repaired)
        repaired_sha = _sha256(repaired)
        if repaired_version != champion_version:
            raise RuntimeError(
                f"Repaired artifact version mismatch: embedded={repaired_version}, champion={champion_version}"
            )
        if repaired_sha != _sha256(legacy):
            raise RuntimeError("Repaired artifact SHA-256 does not match source bytes")

        report.update({
            "status": "REPAIRED",
            "action": "restored_versioned_artifact_from_verified_legacy_pointer",
            "embedded_version": repaired_version,
            "sha256": repaired_sha,
            "bytes": len(repaired),
            "database_champion_changed": False,
        })
        _write_report(report)
        print(json.dumps(report, indent=2))
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely restore a missing versioned champion model artifact")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repair(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
