#!/usr/bin/env python3
"""Release THIS run's own orphaned CDB lock after a lost runner (fail closed).

Kept separate so cdb_global_writer_lock.py stays byte-identical to the
private-data repository copy.
"""
from __future__ import annotations

import json
import subprocess

from cdb_global_writer_lock import DEFAULT_REPOSITORY, _api, _owner, _remote_lock


def _bundle_consistent(repository: str) -> tuple[bool, str]:
    """Every file in the CDB bundle manifest matches its release asset digest."""
    release = _api(repository, "releases/tags/tbt-data-v1")
    assets = {a["name"]: a for a in release.get("assets", [])}
    meta = assets.get("_tbt_bundle_manifest.json")
    if not meta:
        return False, "bundle manifest asset missing"
    raw = subprocess.run(
        ["gh", "api", "-H", "Accept: application/octet-stream",
         f"repos/{repository}/releases/assets/{meta['id']}"],
        text=True, capture_output=True)
    if raw.returncode:
        return False, "bundle manifest unreadable"
    files = json.loads(raw.stdout).get("files")
    items = files.items() if isinstance(files, dict) else [(f.get("name"), f) for f in files or []]
    checked = 0
    for name, info in items:
        asset = assets.get(name)
        if asset is None:
            return False, f"missing asset {name}"
        digest, size = info.get("sha256"), info.get("bytes") or info.get("size")
        if digest and asset.get("digest") and asset["digest"] != "sha256:" + digest:
            return False, f"digest mismatch {name}"
        if size and size != asset.get("size"):
            return False, f"size mismatch {name}"
        checked += 1
    if not checked:
        return False, "empty bundle manifest"
    return True, f"{checked} files consistent"


def release_orphan(repository: str) -> str:
    """Release a lock left by THIS run after its runner died.

    Only the exact owner string of the current run/attempt is ever deleted,
    and only when the published CDB bundle is self-consistent; otherwise the
    lock stays for the operator (fail closed).
    """
    owner = _owner()
    remote = _remote_lock(repository)
    if remote is None:
        return "no lock"
    sha = remote.get("object", {}).get("sha")
    tag = _api(repository, f"git/tags/{sha}") if sha else {}
    if tag.get("message") != f"owner={owner}":
        return "lock held by another run; untouched"
    ok, detail = _bundle_consistent(repository)
    if not ok:
        raise RuntimeError("Orphaned own CDB lock kept: bundle inconsistent (" + detail + ")")
    _api(repository, "git/refs/tags/blinq-cdb-global-writer", method="DELETE")
    return "released orphaned own lock; " + detail



if __name__ == "__main__":
    print(release_orphan(DEFAULT_REPOSITORY), flush=True)
