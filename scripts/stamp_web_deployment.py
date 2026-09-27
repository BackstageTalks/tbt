#!/usr/bin/env python3
"""Mark each Azure web deployment with its exact Git commit and unique asset URLs.

Keep committed frontend releases stable; only the deployment artifact is stamped.
Both the regular CI deployment and data-driven redeploy must use this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ASSETS = ("blinq-app.css", "app.js", "auth.js", "responsive.js")


def stamp(web: Path, sha: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected full Git commit SHA")
    index = web / "index.html"
    html = index.read_text(encoding="utf-8")
    # Do not permit twice-stamped checkouts or silently missing dependencies.
    html = re.sub(r'\s*<meta name="blinq-deployment-sha" content="[0-9a-f]+"\s*/>', "", html)
    html = html.replace(
        '  <title>BlinQ · Tennis Intelligence</title>',
        f'  <meta name="blinq-deployment-sha" content="{sha}" />\n'
        '  <title>BlinQ · Tennis Intelligence</title>',
        1,
    )
    if html.count('name="blinq-deployment-sha"') != 1:
        raise ValueError("Missing or duplicated deployment marker")
    hashes = {}
    for name in ASSETS:
        path = web / name
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        pattern = re.compile(r"(/" + re.escape(name) + r'\?[^"]+)(?=")')
        found = pattern.findall(html)
        if len(found) != 1:
            raise ValueError(f"Expected exactly one {name} HTML reference; found {len(found)}")
        html = pattern.sub(
            lambda match: re.sub(r"&deploy=[0-9a-f]+", "", match.group(1))
            + f"&deploy={sha[:12]}",
            html,
        )
    release = json.loads((web / "release.json").read_text(encoding="utf-8"))
    marker = {
        "git_sha": sha,
        "patch": release["patch"],
        "visual_revision": release["visual_revision"],
        "files_sha256": hashes,
    }
    # Generate these files only after the checkout has been verified as latest main.
    index.write_text(html, encoding="utf-8")
    (web / "deployment.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return marker


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", type=Path, default=Path("web"))
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    print(json.dumps(stamp(args.web, args.sha), indent=2))


if __name__ == "__main__":
    main()
