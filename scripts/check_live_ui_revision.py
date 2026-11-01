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
import subprocess
import sys
import time
import tempfile
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



def revision_files(web: Path, deployed_sha: str) -> dict[str, bytes]:
    """Resolve expected files from the immutable deployed commit, not HEAD.

    A newer main checkout can be perfectly valid while Azure still serves its
    prior release. Git fetch changes only this disposable CI checkout, never
    production or CDB. A missing historical commit fails closed.
    """
    names = (*FRONTEND_FILES, "index.html")
    root = web.resolve().parent
    if not (root / ".git").exists():
        # Explicit offline fixtures (tests) have no repository metadata.
        return {name: (web / name).read_bytes() for name in names}
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=True, capture_output=True, timeout=10,
        ).stdout.decode().strip()
        if head == deployed_sha:
            return {name: (web / name).read_bytes() for name in names}
        present = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", deployed_sha + "^{commit}"],
            capture_output=True, timeout=10,
        )
        if present.returncode != 0:
            subprocess.run(
                ["git", "-C", str(root), "fetch", "--no-tags", "--depth=1",
                 "origin", deployed_sha],
                check=True, capture_output=True, timeout=60,
            )
        return {
            name: subprocess.run(
                ["git", "-C", str(root), "show", f"{deployed_sha}:web/{name}"],
                check=True, capture_output=True, timeout=20,
            ).stdout
            for name in names
        }
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Cannot verify exact deployed revision from Git history") from exc


def build_optimized_revision(files: dict[str, bytes]) -> dict[str, bytes]:
    """Rebuild the pinned deployment transform from the immutable Git sources.

    Never trust deployment.json checksums alone when checking optimized assets:
    independently reproduce the JS/CSS bytes first.
    """
    # Direct CLI execution has scripts/ (not the repository root) on sys.path.
    # Resolve the sibling optimizer without relying on the runner's CWD.
    try:
        from scripts.optimize_web_assets import ASSETS, build
    except ModuleNotFoundError as exc:
        if exc.name != "scripts":
            raise
        root = str(Path(__file__).resolve().parents[1])
        if root not in sys.path:
            sys.path.insert(0, root)
        from scripts.optimize_web_assets import ASSETS, build

    with tempfile.TemporaryDirectory(prefix="blinq-watchdog-") as tmp:
        web = Path(tmp) / "web"
        out = Path(tmp) / "optimized"
        web.mkdir()
        for name in (*ASSETS, "release.json"):
            (web / name).write_bytes(files[name])
        build(web, out)
        return {**files, **{name: (out / name).read_bytes() for name in ASSETS}}


def verify_once(
    web: Path,
    base_url: str,
    fetch=http_get,
    token: str = "watch",
    source_loader=revision_files,
    optimized_builder=build_optimized_revision,
) -> str:
    base_url = base_url.rstrip("/")
    def get(path: str) -> bytes:
        return fetch(f"{base_url}{path}?__blinq_watchdog={token}")

    deployed = json.loads(get("/deployment.json").decode("utf-8"))
    live_sha = str(deployed.get("git_sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", live_sha):
        raise ValueError("live deployment.json has no valid Git SHA")
    expected_files = source_loader(web, live_sha)
    release = json.loads(expected_files["release.json"].decode("utf-8"))
    if deployed.get("patch") != release.get("patch"):
        raise ValueError("live patch differs from repository release")
    if deployed.get("visual_revision") != release.get("visual_revision"):
        raise ValueError("live visual revision differs from repository release")

    actual_files = {name: get("/" + name) for name in FRONTEND_FILES}
    asset_names = ("app.js", "blinq-app.css")
    mismatch = any(sha256(actual_files[name]) != sha256(expected_files[name])
                   for name in asset_names)
    if mismatch:
        # Only try the explicit, deterministic optimized-release format.
        # Randomly altered JS/CSS must not turn into an accepted variant.
        visual = str(release["visual_revision"])
        patch = str(release["patch"]).replace("736-", "7.3.6-", 1)
        optimized_markers = (
            actual_files["app.js"].startswith(
                f"/* BlinQ visual revision: {visual} */\n".encode("utf-8")
            )
            and actual_files["blinq-app.css"].startswith(
                f"/* BlinQ runtime patch {patch} */\n".encode("utf-8")
            )
        )
        if optimized_markers:
            try:
                expected_files = optimized_builder(expected_files)
            except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
                raise ValueError("Cannot independently rebuild optimized frontend") from exc

    for name in FRONTEND_FILES:
        expected = expected_files[name]
        actual = actual_files[name]
        if sha256(actual) != sha256(expected):
            raise ValueError(f"outdated or modified frontend file: {name}")
        if name in STAMPED_FILES and (deployed.get("files_sha256") or {}).get(name) != sha256(actual):
            raise ValueError(f"invalid deployment stamp checksum: {name}")

    expected_html = expected_files["index.html"].decode("utf-8")
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
