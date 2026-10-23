#!/usr/bin/env python3
"""Check that Azure serves the current BlinQ frontend, not an obsolete snapshot.

Read-only: never rebuild, deploy, authenticate, modify CDB or call tennis APIs.
The last deployment's SHA can be older than main when main has backend-only
commits; actual frontend bytes and the Azure deployment stamp must agree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

FRONTEND_FILES = (
    "app.js",
    "auth.js",
    "responsive.js",
    "blinq-mobile.js",
    "blinq-app.css",
    "blinq-mobile.css",
    "blinq-detail.css",
    "release.json",
)
STAMPED_FILES = ("app.js", "auth.js", "responsive.js", "blinq-app.css")
DEFAULT_URL = "https://agreeable-sky-011a7fe10.7.azurestaticapps.net"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def original_index(html: str) -> str:
    """Undo only the two transformations made by stamp_web_deployment.py."""
    html = re.sub(
        r'^[ \t]*<meta name="blinq-deployment-sha" content="[0-9a-f]{40}"[ \t]*/>[ \t]*\r?\n',
        "",
        html,
        flags=re.MULTILINE,
    )
    return re.sub(r"&deploy=[0-9a-f]{12}(?=[&\"])", "", html)


def http_get(url: str, timeout: int = 15) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache", "User-Agent": "BlinQ-UI-Watchdog/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return response.read()


def verify_once(
    web: Path,
    base_url: str,
    fetch=http_get,
    token: str = "watch",
) -> str:
    base_url = base_url.rstrip("/")
    def get(path: str) -> bytes:
        return fetch(f"{base_url}{path}?__blinq_watchdog={token}")

    release = json.loads((web / "release.json").read_text(encoding="utf-8"))
    deployed = json.loads(get("/deployment.json").decode("utf-8"))
    live_sha = str(deployed.get("git_sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", live_sha):
        raise ValueError("live deployment.json has no valid Git SHA")
    if deployed.get("patch") != release.get("patch"):
        raise ValueError("live patch differs from repository release")
    if deployed.get("visual_revision") != release.get("visual_revision"):
        raise ValueError("live visual revision differs from repository release")

    for name in FRONTEND_FILES:
        expected = (web / name).read_bytes()
        actual = get("/" + name)
        if sha256(actual) != sha256(expected):
            raise ValueError(f"outdated or modified frontend file: {name}")
        if name in STAMPED_FILES and (deployed.get("files_sha256") or {}).get(name) != sha256(actual):
            raise ValueError(f"invalid deployment stamp checksum: {name}")

    expected_html = (web / "index.html").read_text(encoding="utf-8")
    for route in ("/", "/follow-the-data/"):
        actual_html = get(route).decode("utf-8")
        if f'name="blinq-deployment-sha" content="{live_sha}"' not in actual_html:
            raise ValueError(f"missing deployment SHA marker on {route}")
        if original_index(actual_html) != expected_html:
            raise ValueError(f"outdated or modified HTML on {route}")
    return live_sha


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", type=Path, default=Path("web"))
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--delay", type=float, default=10.0)
    parser.add_argument("--token", default="production")
    args = parser.parse_args()

    if args.retries < 1:
        parser.error("--retries must be >= 1")
    for attempt in range(1, args.retries + 1):
        try:
            live_sha = verify_once(args.web, args.url, token=f"{args.token}-{attempt}")
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError, UnicodeError) as exc:
            print(f"UI revision attempt {attempt}/{args.retries}: FAIL: {type(exc).__name__}: {exc}", flush=True)
            if attempt < args.retries:
                time.sleep(args.delay)
        else:
            print(f"PASS: live BlinQ frontend matches repository assets and HTML; deployed SHA={live_sha}", flush=True)
            return 0
    print("FAIL: live frontend drift confirmed across all checks", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
