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
import re
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

def verify_current_production_digest(repository: str, readiness: dict) -> None:
    """Fail closed if the model changed between readiness and Admin publishing."""
    sha = str(readiness.get("production_model_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("Readiness has no SHA-pinned production model")
    version = str(readiness.get("production_version") or "").strip()
    if not version:
        raise ValueError("Readiness has no production model version")
    stamp = datetime.fromisoformat(str(readiness["generated_at_utc"]).replace("Z", "+00:00"))
    if stamp.tzinfo is None or abs((datetime.now(timezone.utc) - stamp).total_seconds()) > 3600:
        raise ValueError("Readiness evidence is not current")
    release = json.loads(_run("gh", "api", f"repos/{repository}/releases/tags/tbt-model-production-v1"))
    assets = [a for a in release.get("assets", []) if a.get("name") == "model.joblib"]
    if len(assets) != 1 or assets[0].get("digest") != "sha256:" + sha:
        raise ValueError("Production release changed after readiness read-back")


def _current_shadow_pair(shadow: dict, production_version: str) -> tuple[dict, str, dict | None]:
    """A shadow report for the former champion is historical, not a live cohort."""
    old = str(shadow.get("production_model_version") or "").strip()
    if not old:
        raise ValueError("Missing shadow source champion")
    if old == production_version:
        return shadow, "current", None
    history = {
        "production_version": old,
        "candidate_version": str(shadow.get("challenger_model_version") or "").strip(),
    }
    # No new pair has been evaluated. Never transfer 441 old observations,
    # the stale challenger identity or its gates to the promoted champion.
    reset = {
        "production_model_version": production_version,
        "challenger_model_version": "",
        "cohort": {
            "captured": 0, "settled": 0, "pending": 0,
            "settled_utc_days": 0, "minimum_for_review": 200,
        },
        "gate": {}, "production": {}, "challenger": {},
    }
    return reset, "awaiting_new_pair", history


def build_snapshot(shadow: dict, readiness: dict, promotion: dict, *, timestamp: str, offline_candidate: dict | None = None) -> dict:
    # Authoritative: readiness just loaded model.joblib from production,
    # not the historical shadow release (which can remain on the old pair).
    champion = str(readiness.get("production_version") or "").strip()
    if not champion:
        raise ValueError("No verified production model in readiness")
    shadow, pair_state, historical_pair = _current_shadow_pair(shadow, champion)
    candidate = str(shadow.get("challenger_model_version") or "").strip()
    decision = promotion.get("decision")
    decision = decision if isinstance(decision, dict) else {}
    return {
        "schema": 1,
        "source_generated_at": timestamp,
        "production_version": champion,
        "candidate_version": candidate,
        "shadow": shadow,
        "shadow_pair_state": pair_state,
        "historical_shadow_pair": historical_pair,
        "offline_candidate": offline_candidate,
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
    expected_offline = ((payload.get("offline_candidate") or {})
                        .get("candidate_version"))
    if result.get("offline_candidate_version") != expected_offline:
        raise RuntimeError("Admin backend did not independently confirm offline candidate")
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
    # Validate the live release a second time after the readiness scanner's
    # independent binary read-back; never publish a snapshot from a race.
    verify_current_production_digest(args.data_repository, readiness)
    # Independently evaluated offline candidate does not replace the active
    # shadow challenger; it occupies a separate admin comparison section.
    offline_candidate = _json_content(
        args.data_repository, "audit/model-frozen-candidate-latest.json",
        required=False,
    )
    snapshot = build_snapshot(
        shadow, readiness, decision,
        timestamp=datetime.now(timezone.utc).isoformat(),
        offline_candidate=offline_candidate or None,
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
