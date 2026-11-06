"""Verify actual Azure serving bytes and Bratislava-day offer after deployment.

No Firebase account impersonation, database mutation, odds changes or provider
requests. The live endpoint requires the existing internal worker credential
and returns only a SHA-256 digest and aggregate market counts.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from _bootstrap import ROOT  # noqa: F401 (ensures tbt imports)
from tbt.services.serving_feed_readback import serving_feed_readback


def verify_readback(local_feed: Path, actual: dict, *, now: datetime | None = None) -> dict:
    if not isinstance(actual, dict) or actual.get("schema") != 1:
        raise ValueError("Invalid protected serving readback schema")
    stamp = actual.get("observed_at_utc")
    if not isinstance(stamp, str):
        raise ValueError("Missing protected serving timestamp")
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid protected serving timestamp") from exc
    if observed.tzinfo is None:
        raise ValueError("Naive protected serving timestamp")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or abs((now - observed).total_seconds()) > 120:
        raise RuntimeError("Production readback clock differs from verification runner")
    expected = serving_feed_readback(local_feed, now=observed)
    if not expected["ok"]:
        raise RuntimeError("Local candidate is not a current ready serving feed")
    for key in ("ok", "ready", "stale", "feed_sha256", "generated_at",
                "betting_day", "source_counts", "visible_counts"):
        if actual.get(key) != expected[key]:
            raise RuntimeError("Production serving readback mismatch: " + key)
    if actual.get("ok") is not True or actual.get("ready") is not True or actual.get("stale") is not False:
        raise RuntimeError("Production serving readback is not ready")
    return {
        "status": "verified",
        "feed_sha256": actual["feed_sha256"],
        "betting_day": actual["betting_day"],
        "generated_at": actual["generated_at"],
        "source_counts": actual["source_counts"],
        "visible_counts": actual["visible_counts"],
        "provider_requests": 0,
        "member_data_returned": False,
    }


def read_protected(base: str, token: str, digest: str) -> dict:
    if not base.startswith("https://") or not token:
        raise ValueError("Signed HTTPS serving-readback endpoint required")
    url = base.rstrip("/") + "/api/v1/internal/serving-feed-readback?" + urlencode({"verify": digest[:16]})
    request = urllib.request.Request(url, headers={
        "X-Blinq-Worker-Token": token,
        "Cache-Control": "no-cache",
        "Accept": "application/json",
    }, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError("Protected serving readback returned non-200")
            return json.loads(response.read(16_384))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        # Error contents and headers may reveal credentials; report only class.
        raise RuntimeError("Protected serving readback unavailable: " + type(exc).__name__) from None


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--feed", type=Path, default=Path("api/data/feed.json"))
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.attempts <= 8:
        raise ValueError("Expected between 1 and 8 read-only verification attempts")
    expected = serving_feed_readback(args.feed)
    if not expected["ok"]:
        raise RuntimeError("Refusing deployment of an unready or stale local feed")
    # Fail *before* Azure upload, not just after a bad generation was served.
    # Bootstrap exemption remains controlled exclusively by prepare_feed.py.
    if args.preflight_only:
        print("BLINQ_SERVING_PREFLIGHT " + json.dumps({
            "status": "ready", "feed_sha256": expected["feed_sha256"],
            "betting_day": expected["betting_day"], "provider_requests": 0,
        }, sort_keys=True), flush=True)
        return
    token = os.getenv("BLINQ_LIVE_WORKER_TOKEN") or ""
    if not token:
        raise RuntimeError("Missing protected serving-readback worker credential")
    failure = "not yet available"
    for attempt in range(1, args.attempts + 1):
        try:
            live = read_protected(args.base_url, token, expected["feed_sha256"])
            evidence = verify_readback(args.feed, live)
            print("BLINQ_SERVING_READBACK " + json.dumps(evidence, sort_keys=True), flush=True)
            return
        except (ValueError, RuntimeError, OSError) as exc:
            failure = str(exc)
            print(f"Protected serving-readback attempt {attempt}/{args.attempts}: {failure}", flush=True)
            if attempt < args.attempts:
                time.sleep(attempt * 2)
    raise RuntimeError("Protected production serving-readback failed: " + failure)


if __name__ == "__main__":
    main()
