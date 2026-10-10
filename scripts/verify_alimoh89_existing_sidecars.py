"""Independent verification of an already-persisted alimoh89 research sidecar.

No canonical database write. Rejects source drift, incomplete/modified release
assets and compressed-byte differences by comparing decompressed JSONL records.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_existing(preparation: dict, manifest: dict, release: dict,
                    local_dir: Path, remote_dir: Path) -> dict:
    if preparation.get("canonical_market_stage_rows") != 0:
        raise ValueError("Canonical market delta is nonzero; not an idempotent readback")
    if preparation.get("canonical_mutated") is not False or preparation.get("model_promoted") is not False:
        raise ValueError("Unexpected mutation or model promotion")
    if preparation.get("provider_api_requests") != 0:
        raise ValueError("Provider API usage is forbidden")
    old = manifest.get("preparation") or {}
    if (preparation.get("source", {}).get("file_sha256") != old.get("source", {}).get("file_sha256")
            or preparation.get("source", {}).get("file_sha256") !=
            "8bc187158931957d92ffaa5dc7e5a3e4bd58b30023e8c470bcb85521a58bee16"):
        raise ValueError("Source checksum changed since immutable integration")
    if preparation.get("staged_rows") != old.get("staged_rows"):
        raise ValueError("Mapped match coverage changed since integration")
    if preparation.get("sidecar_years") != old.get("sidecar_years"):
        raise ValueError("Mapped per-year match coverage changed")
    canonical = manifest.get("canonical_import") or {}
    if (canonical.get("counts", {}).get("updated") != 20342
            or canonical.get("stage_rows") != 20342
            or manifest.get("release_tag") != "blinq-alimoh89-markets-2026-10-07"):
        raise ValueError("Expected existing canonical import provenance missing")
    if release.get("tag_name") != manifest["release_tag"]:
        raise ValueError("Release tag mismatch")

    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != 12:
        raise ValueError("Expected exactly 12 historical sidecars")
    wanted = {str(x.get("name")) for x in entries}
    if len(wanted) != len(entries) or any(not n.startswith("market-sidecar-") or
                                          not n.endswith(".jsonl.gz") for n in wanted):
        raise ValueError("Sidecar manifest has duplicate or invalid names")
    local_names = {p.name for p in local_dir.glob("market-sidecar-*.jsonl.gz")}
    remote_names = {p.name for p in remote_dir.glob("market-sidecar-*.jsonl.gz")}
    if local_names != wanted or remote_names != wanted:
        raise ValueError("Incomplete local or independently downloaded sidecar set")
    assets = {str(x.get("name")): x for x in release.get("assets", [])}
    if wanted != set(assets):
        raise ValueError("Remote release asset inventory changed")

    total_rows = 0
    for entry in entries:
        name = entry["name"]
        original = remote_dir / name
        local = local_dir / name
        checksum = digest(original)
        if checksum != entry.get("sha256") or assets[name].get("digest") != "sha256:" + checksum:
            raise ValueError(f"Persisted SHA-256 mismatch: {name}")
        if original.stat().st_size != entry.get("bytes") or assets[name].get("size") != entry.get("bytes"):
            raise ValueError(f"Persisted asset size mismatch: {name}")
        with gzip.open(original, "rb") as handle:
            stored_lines = handle.read()
        with gzip.open(local, "rb") as handle:
            replay_lines = handle.read()
        if hashlib.sha256(stored_lines).digest() != hashlib.sha256(replay_lines).digest():
            raise ValueError(f"Stored historical sidecar differs from fresh linked source: {name}")
        rows = stored_lines.count(b"\n")
        if rows != entry.get("rows") or not stored_lines.endswith(b"\n"):
            raise ValueError(f"Persisted row count or JSONL framing changed: {name}")
        total_rows += rows
    if total_rows != preparation["staged_rows"]:
        raise ValueError("Total persisted market sidecar coverage mismatched")
    return {
        "status": "already_integrated_verified",
        "canonical_rows_added": 0,
        "existing_canonical_markets": canonical["counts"]["updated"],
        "research_sidecar_matches": total_rows,
        "sidecar_files_sha256_verified": len(entries),
        "provider_api_requests": 0,
        "model_promoted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--remote", type=Path, required=True)
    args = parser.parse_args()
    result = verify_existing(
        json.loads(args.preparation.read_text()),
        json.loads(args.manifest.read_text()),
        json.loads(args.release.read_text()), args.local, args.remote)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
