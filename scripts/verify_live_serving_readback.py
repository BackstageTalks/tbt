"""Independently verify exact production API feed bytes through the worker canary.

Zero provider requests or writes; the privileged worker token is sent only as
an HTTPS header and never logged. An HTTP 200 or frontend SHA alone is not
sufficient proof of the packaged serving snapshot.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

COUNTS = (
    "upcoming", "top_daily_picks", "prime_picks", "value_picks",
    "ace_picks", "sg_picks", "doubles_picks", "results",
)


def validate(prepared_bytes: bytes, received: dict) -> dict:
    if not isinstance(received, dict) or received.get("ok") is not True:
        raise ValueError("Serving readback is unavailable")
    expected = json.loads(prepared_bytes)
    if not isinstance(expected, dict) or expected.get("schema") != 1:
        raise ValueError("Invalid prepared candidate schema")
    # The workflow must not publish a genuinely not-ready serving candidate.
    # Empty market categories are allowed; missing whole releases are not.
    if expected.get("ready") is not True or received.get("ready") is not True:
        raise ValueError("Serving candidate not ready")
    digest = sha256(prepared_bytes).hexdigest()
    if received.get("schema") != 1 or received.get("file_sha256") != digest:
        raise ValueError("Production serving file SHA-256 mismatch")
    if received.get("bytes") != len(prepared_bytes):
        raise ValueError("Production serving file length mismatch")
    if received.get("generated_at") != expected.get("generated_at"):
        raise ValueError("Production serving generation timestamp mismatch")

    raw = received.get("raw_counts")
    visible = received.get("visible_counts")
    if not isinstance(raw, dict) or not isinstance(visible, dict):
        raise ValueError("Serving readback count schema missing")
    for key in COUNTS:
        candidate_rows = expected.get(key, [])
        if not isinstance(candidate_rows, list):
            raise ValueError("Prepared serving section has invalid type: " + key)
        if type(raw.get(key)) is not int or raw[key] != len(candidate_rows):
            raise ValueError("Production raw serving count mismatch: " + key)
        if type(visible.get(key)) is not int or not (0 <= visible[key] <= raw[key]):
            raise ValueError("Production public-day count invalid: " + key)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(received.get("betting_day") or "")):
        raise ValueError("Invalid production betting-day key")
    if type(received.get("stale")) is not bool:
        raise ValueError("Missing serving freshness status")
    return {
        "status": "verified",
        "file_sha256": digest,
        "generated_at": expected["generated_at"],
        "betting_day": received["betting_day"],
        "stale": received["stale"],
        "raw_counts": raw,
        "visible_counts": visible,
        "paid_provider_requests": 0,
    }



def preflight_serving(path: Path, *, now=None) -> dict:
    """Refuse an unready or wrong-betting-day artifact *before* Azure upload.

    Reuse the server's existing strict file+Bratislava-day validator; no new
    writer, worker token, Telegram, CDB or provider call is necessary.
    """
    import sys

    root = str(Path(__file__).resolve().parents[1] / "api")
    if root not in sys.path:
        sys.path.insert(0, root)
    from tbt.services.feed import serving_artifact_readback

    evidence = serving_artifact_readback(path, now=now)
    if evidence["ready"] is not True or evidence["stale"] is not False:
        raise ValueError("Pre-deploy serving feed is not ready for the current betting day")
    return {
        "status": "ready",
        "file_sha256": evidence["file_sha256"],
        "betting_day": evidence["betting_day"],
        "raw_counts": evidence["raw_counts"],
        "paid_provider_requests": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-feed", default="api/data/feed.json")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        print("BLINQ_SERVING_PREFLIGHT " + json.dumps(
            preflight_serving(Path(args.prepared_feed)), sort_keys=True), flush=True)
        return
    token = os.getenv("BLINQ_LIVE_WORKER_TOKEN", "").strip()
    base = args.base_url.strip().rstrip("/")
    if not token or not base.startswith("https://") or "/" in base.split("://", 1)[1]:
        raise SystemExit("Verified HTTPS production origin and worker token are required")
    prepared = Path(args.prepared_feed).read_bytes()
    error = None
    for attempt in range(1, 9):
        try:
            request = Request(
                f"{base}/api/v1/internal/serving-readback?probe={attempt}",
                headers={
                    "X-Blinq-Worker-Token": token,
                    "Cache-Control": "no-cache",
                    "Accept": "application/json",
                },
                method="GET",
            )
            with urlopen(request, timeout=20) as response:
                body = json.loads(response.read(100_000))
            summary = validate(prepared, body)
            print("BLINQ_SERVING_READBACK " + json.dumps(summary, sort_keys=True), flush=True)
            if summary["stale"]:
                print("::warning::Exact serving bytes verified, but betting-day feed is stale", flush=True)
            return
        except (HTTPError, URLError, OSError, ValueError, TypeError, KeyError) as exc:
            # A newly deployed Azure edge may serve the prior generation for
            # several seconds after upload completes; retries are read-only.
            error = type(exc).__name__
            if attempt < 8:
                time.sleep(attempt * 2)
    raise SystemExit("Production serving readback failed after eight bounded probes: " + str(error))


if __name__ == "__main__":
    main()
