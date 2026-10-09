#!/usr/bin/env python3
"""Read-only private GitHub model evidence -> signed Azure Admin status.

No Tennis provider calls, no model training, no release writes and no promotion.
This can run on a schedule; a new exact model pair resets the active shadow
cohort automatically, while earlier promotion decisions remain historical.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _run(*args: str) -> str:
    done = subprocess.run(args, check=True, text=True, capture_output=True, timeout=80)
    return done.stdout


def _json_content(repository: str, path: str, *, required: bool = True) -> dict:
    try:
        payload = json.loads(_run("gh", "api", f"repos/{repository}/contents/{path}"))
        import base64
        result = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
    except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
        if required:
            raise RuntimeError(f"Private GitHub evidence unavailable: {path}") from exc
        return {}
    if not isinstance(result, dict):
        raise RuntimeError(f"Invalid private GitHub evidence object: {path}")
    return result


def _release_json(repository: str, tag: str, asset: str, folder: Path) -> dict:
    target = folder / asset
    _run(
        "gh", "release", "download", tag, "-R", repository,
        "-p", asset, "-D", str(folder), "--clobber"
    )
    report = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise RuntimeError(f"Invalid private {asset} asset")
    return report


def build_snapshot(shadow: dict, readiness: dict, promotion: dict, *, timestamp: str) -> dict:
    champion = str(shadow.get("production_model_version") or "").strip()
    candidate = str(shadow.get("challenger_model_version") or "").strip()
    if not champion:
        raise ValueError("No active production model in shadow report")
    decision = promotion.get("decision")
    decision = decision if isinstance(decision, dict) else {}
    return {
        "schema": 1,
        "source_generated_at": timestamp,
        "production_version": champion,
        "candidate_version": candidate,
        "shadow": shadow,
        "readiness": readiness,
        "last_decision": {
            "status": str(promotion.get("status") or ""),
            "candidate_version": str(
                decision.get("candidate_version") or promotion.get("candidate_version") or ""
            ),
            "production_version": str(
                decision.get("production_version") or promotion.get("previous_production_version") or ""
            ),
            "decided_at": str(decision.get("decided_at") or ""),
            "reason_codes": list(decision.get("reasons") or [])[:12],
        },
    }


def publish(payload: dict, base_url: str, worker_token: str) -> dict:
    if not worker_token:
        raise RuntimeError("BLINQ_LIVE_WORKER_TOKEN is missing")
    base = base_url.strip().rstrip("/")
    if not base.startswith("https://") or not base.endswith(".azurestaticapps.net") and not base.endswith(".blinq.sk"):
        raise RuntimeError("Calibration target URL must be the configured HTTPS BlinQ deployment")
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > 32_000:
        raise RuntimeError("Calibration snapshot payload exceeds size limit")
    request = Request(
        base + "/api/v1/internal/model-calibration-snapshot",
        data=raw, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Blinq-Worker-Token": worker_token,
        },
    )
    try:
        with urlopen(request, timeout=35) as response:
            result = json.loads(response.read(32_000).decode("utf-8"))
    except (HTTPError, URLError) as exc:
        raise RuntimeError("Signed calibration status sync failed") from exc
    if not isinstance(result, dict) or result.get("stored") is not True:
        raise RuntimeError("Admin backend did not confirm persisted calibration status")
    if result.get("production_version") != payload["production_version"]:
        raise RuntimeError("Persisted production version differs from source")
    if result.get("candidate_version") != (payload["candidate_version"] or None):
        raise RuntimeError("Persisted candidate version differs from source")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-repository", default=os.getenv(
        "TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"
    ))
    parser.add_argument("--base-url", default=os.getenv(
        "BLINQ_BASE_URL", "https://agreeable-sky-011a7fe10.7.azurestaticapps.net"
    ))
    parser.add_argument("--output", default="")
    parser.add_argument("--readiness-file", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not os.getenv("GH_TOKEN"):
        raise RuntimeError("Private GH_TOKEN missing")
    with TemporaryDirectory(prefix="blinq-calibration-") as directory:
        shadow = _release_json(
            args.data_repository, "tbt-model-shadow-v1",
            "shadow_report.json", Path(directory)
        )
    readiness = (
        json.loads(Path(args.readiness_file).read_text(encoding="utf-8"))
        if args.readiness_file else _json_content(
            args.data_repository, "audit/model-promotion-readiness-latest.json",
            required=False,
        )
    )
    decision = _json_content(
        args.data_repository, "audit/model-shadow-promotion-latest.json",
        required=False,
    )
    snapshot = build_snapshot(
        shadow, readiness, decision,
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    # Reuse the *same* strict, private API schema before a network write.
    from tbt.services.model_calibration_status import normalize_model_calibration_snapshot
    safe = normalize_model_calibration_snapshot(snapshot)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(safe, ensure_ascii=False, indent=2))
    if args.dry_run:
        print(json.dumps({
            "dry_run": True, "production_version": safe["production_version"],
            "candidate_version": safe["candidate_version"],
            "shadow_settled": safe["shadow"]["settled"],
            "new_unseen_rows": safe["unseen"]["eligible_rows"],
            "provider_requests": 0, "production_mutated": False,
        }))
        return 0
    receipt = publish(
        snapshot, args.base_url,
        os.getenv("BLINQ_LIVE_WORKER_TOKEN", ""),
    )
    print(json.dumps({
        "stored": bool(receipt["stored"]),
        "production_version": receipt["production_version"],
        "candidate_version": receipt["candidate_version"],
        "shadow_settled": safe["shadow"]["settled"],
        "new_unseen_rows": safe["unseen"]["eligible_rows"],
        "provider_requests": 0, "model_promoted": False,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
