from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BUNDLE_MANIFEST = "_tbt_bundle_manifest.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _gh_json(*args: str) -> dict:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:500])
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("GitHub release payload must be an object")
    return value


def _sha256_from_digest(value: object) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.split(":", 1)[1]
    if not SHA256_RE.fullmatch(text):
        raise ValueError("Release asset is missing a valid GitHub SHA-256 digest")
    return text


def build_manifest(release: dict, *, required_assets: tuple[str, ...] = ()) -> dict:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Release payload has no asset list")

    files: dict[str, dict[str, object]] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        if not name or name == BUNDLE_MANIFEST:
            continue
        if str(asset.get("state") or "") != "uploaded":
            continue
        size = int(asset.get("size") or 0)
        if size <= 0:
            raise ValueError(f"Release asset {name} is empty")
        files[name] = {
            "sha256": _sha256_from_digest(asset.get("digest")),
            "bytes": size,
        }

    missing = sorted(set(required_assets) - set(files))
    if missing:
        raise FileNotFoundError(
            "Required release assets are missing from manifest source: "
            + ", ".join(missing)
        )
    if not files:
        raise ValueError("Release has no checksum-capable uploaded assets")

    return {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": dict(sorted(files.items())),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Rebuild a private GitHub release bundle manifest from GitHub asset digests."
    )
    ap.add_argument("--repository", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", default=f".cache/tbt/release-repair/{BUNDLE_MANIFEST}")
    ap.add_argument("--require-asset", action="append", default=[])
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        raise ValueError("Expected owner/repository")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.tag):
        raise ValueError("Invalid release tag")

    release = _gh_json(
        "api", f"repos/{args.repository}/releases/tags/{args.tag}"
    )
    manifest = build_manifest(
        release, required_assets=tuple(str(x) for x in args.require_asset)
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if args.upload:
        if out.name != BUNDLE_MANIFEST:
            raise ValueError(
                f"Upload output must be named exactly {BUNDLE_MANIFEST}"
            )
        result = subprocess.run(
            [
                "gh", "release", "upload", args.tag, str(out),
                "--repo", args.repository, "--clobber",
            ],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[:500])

    print(json.dumps({
        "repository": args.repository,
        "tag": args.tag,
        "files": len(manifest["files"]),
        "required_assets": args.require_asset,
        "uploaded": bool(args.upload),
        "manifest": str(out),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
