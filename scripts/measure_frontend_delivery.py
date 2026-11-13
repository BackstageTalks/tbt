#!/usr/bin/env python3
"""Read-only production HTTP transport audit; no provider APIs or user sessions."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ASSETS = ("/", "/app.js", "/auth.js", "/responsive.js", "/blinq-app.css", "/deployment.json")
ENCODINGS = ("identity", "gzip", "br")
MAX_BODY_BYTES = 8 * 1024 * 1024
OBSERVED_HEADERS = ("cache-control", "content-type", "content-length", "content-encoding",
                    "etag", "last-modified", "age", "vary", "expires", "cdn-cache-control")
PUBLIC_API_PROBES = ("/api/v1/auth/config", "/api/v1/ui-config", "/deployment.json")
MAX_API_PROBE_BODY_BYTES = 1024 * 1024


def public_origin(value: str) -> str:
    """Disallow credentials, query/fragment and plain HTTP for live measurement."""
    parsed = urlsplit(str(value or "").strip())
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("Expected a public https://host origin without path/query/credentials")
    return f"https://{parsed.netloc}".rstrip("/")


def fetch(origin: str, path: str, encoding: str, conditional: dict | None = None):
    headers = {
        "User-Agent": "BlinQ-ReadOnly-Transport-Audit/1",
        "Accept-Encoding": encoding,
        "Cache-Control": "no-cache" if conditional else "max-age=0",
    }
    if conditional:
        headers.update(conditional)
    request = Request(origin.rstrip("/") + path, headers=headers)
    start = time.monotonic()
    try:
        response = urlopen(request, timeout=25)
    except HTTPError as error:
        if error.code != 304:
            raise
        response = error
    with response:
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError(f"Response too large for read-only audit: {path}")
        metadata = {
            "status": response.status,
            "response_body_bytes": len(body),
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "headers": {
                name: value for name in OBSERVED_HEADERS
                if (value := response.headers.get(name)) is not None
            },
        }
    return metadata, body


def measure(origin: str, *, require_https: bool = True) -> dict:
    origin = public_origin(origin) if require_https else origin.rstrip("/")
    report = {
        "schema": 1,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "method": "GET, raw response body length, Accept-Encoding identity/gzip/br; "
                  "conditional GET when validators exist. Not a browser-cache or TLS-byte test.",
        "assets": {},
    }
    raw_identity = {}
    for path in ASSETS:
        encodings = {}
        for encoding in ENCODINGS:
            metadata, body = fetch(origin, path, encoding)
            encodings[encoding] = metadata
            if encoding == "identity":
                raw_identity[path] = body
                metadata["sha256"] = hashlib.sha256(body).hexdigest()
        validator_headers = encodings["identity"]["headers"]
        validator = {}
        if validator_headers.get("etag"):
            validator["If-None-Match"] = validator_headers["etag"]
        elif validator_headers.get("last-modified"):
            validator["If-Modified-Since"] = validator_headers["last-modified"]
        if validator:
            encodings["conditional_identity"], _ = fetch(origin, path, "identity", validator)
        report["assets"][path] = encodings

    report["totals"] = {
        encoding: sum(report["assets"][path][encoding]["response_body_bytes"]
                      for path in ASSETS if path != "/deployment.json")
        for encoding in ENCODINGS
    }
    try:
        deployment = json.loads(raw_identity["/deployment.json"])
        expected = deployment.get("files_sha256") or {}
        report["deployed_git_sha"] = deployment.get("git_sha")
        report["deployment_hash_check"] = {
            path: (hashlib.sha256(raw_identity[path]).hexdigest() == expected[path.lstrip("/")])
            for path in ("/app.js", "/auth.js", "/responsive.js", "/blinq-app.css")
            if path.lstrip("/") in expected
            and not report["assets"][path]["identity"]["headers"].get("content-encoding")
        }
    except (ValueError, TypeError, AttributeError):
        report["deployment_hash_check"] = {}
        report["deployment_manifest_parseable"] = False
    return report



def probe_public_api_latency(origin: str, *, rounds: int = 3,
                             require_https: bool = True) -> dict:
    """Compare public API latency to the static CDN control, without credentials.

    This does not measure the protected member feed. First-header timing
    includes DNS, TLS, gateway and server time; it is not server execution
    time or exact first-body-byte timing. No response content is retained.
    """
    origin = public_origin(origin) if require_https else origin.rstrip("/")
    if not 1 <= rounds <= 5:
        raise ValueError("Public API probe rounds must be between 1 and 5")
    result = {
        "method": "Sequential unauthenticated GET; no-store request; "
                  "headers_ms includes DNS/TLS/gateway/server; no response payload retained.",
        "rounds": rounds,
        "samples": {path: [] for path in PUBLIC_API_PROBES},
    }
    for _round in range(rounds):
        for path in PUBLIC_API_PROBES:
            request = Request(
                origin + path,
                headers={
                    "User-Agent": "BlinQ-Public-Azure-Latency-Audit/1",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Cache-Control": "no-cache",
                },
            )
            start = time.monotonic()
            try:
                try:
                    response = urlopen(request, timeout=20)
                except HTTPError as error:
                    response = error
                with response:
                    headers_ms = round((time.monotonic() - start) * 1000)
                    body = response.read(MAX_API_PROBE_BODY_BYTES + 1)
                    if len(body) > MAX_API_PROBE_BODY_BYTES:
                        raise ValueError("Public response exceeds audit bound: " + path)
                    total_ms = round((time.monotonic() - start) * 1000)
                    result["samples"][path].append({
                        "status": int(response.status),
                        "headers_ms": headers_ms,
                        "body_ms": max(0, total_ms - headers_ms),
                        "total_ms": total_ms,
                        "body_bytes": len(body),
                        "cache_control": response.headers.get("Cache-Control", ""),
                    })
            except (OSError, TimeoutError) as error:
                result["samples"][path].append({
                    "status": 0,
                    "total_ms": round((time.monotonic() - start) * 1000),
                    "error_type": type(error).__name__,
                })
    result["summary"] = {
        path: {
            "median_total_ms": round(statistics.median(item["total_ms"] for item in samples)),
            "median_headers_ms": round(statistics.median(
                item["headers_ms"] for item in samples if "headers_ms" in item,
            )) if any("headers_ms" in item for item in samples) else None,
            "failed_or_non_2xx": sum(not 200 <= item["status"] < 300 for item in samples),
        }
        for path, samples in result["samples"].items()
    }
    return result

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=os.environ.get("BLINQ_PUBLIC_URL", ""))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = measure(args.origin)
    report["public_api_latency"] = probe_public_api_latency(report["origin"])
    summary = {
        "origin": report["origin"],
        "deployed_git_sha": report.get("deployed_git_sha"),
        "totals_response_body_bytes": report["totals"],
        "deployment_hash_check": report["deployment_hash_check"],
        "public_api_latency": report["public_api_latency"],
        "assets": {
            path: {
                encoding: {
                    "bytes": sample["response_body_bytes"],
                    "status": sample["status"],
                    "elapsed_ms": sample["elapsed_ms"],
                    "cache_control": sample["headers"].get("cache-control"),
                    "content_encoding": sample["headers"].get("content-encoding"),
                    "age": sample["headers"].get("age"),
                }
                for encoding, sample in variants.items()
            }
            for path, variants in report["assets"].items()
        },
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
