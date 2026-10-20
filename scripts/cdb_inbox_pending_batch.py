"""Private, SHA-verified source staging across CDB writer contention.

Prepare normalized Drive rows once; do not keep a GitHub runner waiting for a
long-running model's canonical CDB lock. Persist only to a PRIVATE tbt-data
release, and require its original checkpoint SHA to match on restore. The CDB
linker always re-runs against freshly downloaded canonical partitions after
the writer becomes idle; the staged source can never bypass CAS/NULL-only gates.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

PRIVATE_REPO = "BackstageTalks/tbt-data"
PENDING_TAG = "blinq-cdb-inbox-pending-v1"
ROOT = Path("work")
ARTIFACT = ROOT / "pending" / "batch.tar.gz"
MANIFEST = ROOT / "pending" / "manifest.json"
MAX_UNCOMPRESSED = 512 * 1024 * 1024
MAX_COMPRESSED = 256 * 1024 * 1024
SAFE_NAME = re.compile(r"^source/normalized/[A-Za-z0-9_.-]+\.csv$")


class PendingInvalid(RuntimeError):
    pass


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _gh(args: list[str], *, missing_ok: bool = False) -> str | None:
    if not os.environ.get("GH_TOKEN"):
        raise PendingInvalid("Missing authenticated PRIVATE GitHub token")
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode:
        if missing_ok and "HTTP 404" in result.stderr:
            return None
        raise PendingInvalid("Private CDB prepared-batch API unavailable")
    return result.stdout


def _remote_manifest() -> dict | None:
    result = _gh(["api", f"repos/{PRIVATE_REPO}/releases/tags/{PENDING_TAG}"],
                 missing_ok=True)
    return json.loads(result) if result is not None else None


def _files() -> dict[str, bytes]:
    source = ROOT / "source"
    report = source / "report.json"
    next_state = ROOT / "private-state" / "next.json"
    if not report.is_file() or not next_state.is_file():
        raise PendingInvalid("Incomplete normalized source or next checkpoint")
    raw_report = json.loads(report.read_text(encoding="utf-8"))
    if raw_report.get("schema") != 1 or raw_report.get("state") != "SOURCE_ONLY":
        raise PendingInvalid("Untrusted source normalization schema")
    paths = {"source/report.json": report, "private-state/next.json": next_state}
    for entry in raw_report.get("normalized", []):
        source_path = Path(str(entry.get("path", "")))
        if (not source_path.is_relative_to(source)
                or not SAFE_NAME.fullmatch(source_path.as_posix().removeprefix("work/"))):
            raise PendingInvalid("Unexpected source normalization path")
        paths[source_path.as_posix().removeprefix("work/")] = source_path
    normalized_dir = source / "normalized"
    existing = {p.as_posix().removeprefix("work/") for p in normalized_dir.glob("*.csv")}
    if existing != (set(paths) - {"source/report.json", "private-state/next.json"}):
        raise PendingInvalid("Normalized source file enumeration mismatch")
    contents = {name: path.read_bytes() for name, path in paths.items()}
    if sum(map(len, contents.values())) > MAX_UNCOMPRESSED:
        raise PendingInvalid("Prepared source exceeds private storage bound")
    return contents


def _expected(root: str, contents: dict[str, bytes], base_sha: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{15,150}", root):
        raise PendingInvalid("Invalid BlinQ_data root")
    if base_sha and not re.fullmatch(r"[a-f0-9]{40}", base_sha):
        raise PendingInvalid("Invalid base checkpoint SHA")
    return {"schema": 1, "folder_id": root,
            "base_sha": base_sha,
            "files": {name: sha256(blob) for name, blob in sorted(contents.items())}}


def _base_sha() -> str:
    path = ROOT / "private-state" / "original-sha"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _download() -> tuple[dict, bytes]:
    if _remote_manifest() is None:
        raise PendingInvalid("Expected prepared batch missing")
    dest = ROOT / "pending"
    dest.mkdir(parents=True, exist_ok=True)
    _gh(["release", "download", PENDING_TAG, "-R", PRIVATE_REPO,
         "-p", "manifest.json", "-p", "batch.tar.gz", "-D", str(dest), "--clobber"])
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    blob = ARTIFACT.read_bytes()
    if len(blob) > MAX_COMPRESSED or sha256(blob) != document.get("archive_sha256"):
        raise PendingInvalid("Private prepared archive digest/size mismatch")
    return document, blob


def _unpack(document: dict, blob: bytes) -> dict[str, bytes]:
    expected = document.get("files")
    if (document.get("schema") != 1 or not isinstance(expected, dict)
            or "source/report.json" not in expected
            or "private-state/next.json" not in expected):
        raise PendingInvalid("Private prepared manifest malformed")
    items = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            for member in tar:
                name = member.name
                if (name not in expected or name in items or not member.isfile()
                        or member.size < 0 or member.size > MAX_UNCOMPRESSED
                        or not (name in {"source/report.json", "private-state/next.json"}
                                or SAFE_NAME.fullmatch(name))):
                    raise PendingInvalid("Unsafe or extra private archive entry")
                total += member.size
                if total > MAX_UNCOMPRESSED:
                    raise PendingInvalid("Prepared source exceeds size bound")
                file = tar.extractfile(member)
                if file is None:
                    raise PendingInvalid("Unreadable prepared source file")
                data = file.read()
                if sha256(data) != expected[name]:
                    raise PendingInvalid("Prepared source SHA mismatch")
                items[name] = data
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise PendingInvalid("Prepared source archive unreadable") from exc
    if set(items) != set(expected):
        raise PendingInvalid("Prepared source archive incomplete")
    report = json.loads(items["source/report.json"])
    if report.get("schema") != 1 or report.get("state") != "SOURCE_ONLY":
        raise PendingInvalid("Prepared source report corrupted")
    declared = {Path(str(item["path"])).as_posix().removeprefix("work/")
                for item in report.get("normalized", [])}
    if declared != (set(items) - {"source/report.json", "private-state/next.json"}):
        raise PendingInvalid("Prepared report/normalized data inconsistent")
    return items


def _clear() -> None:
    if _remote_manifest() is None:
        return
    document, blob = _download()
    files = _unpack(document, blob)
    next_file = ROOT / "private-state" / "next.json"
    if not next_file.is_file() or sha256(next_file.read_bytes()) != sha256(files["private-state/next.json"]):
        raise PendingInvalid("Refusing to delete uncommitted private source batch")
    _gh(["release", "delete", PENDING_TAG, "-R", PRIVATE_REPO, "--yes", "--cleanup-tag"])
    print("CDB_INBOX_PREPARED_BATCH_CLEARED_AFTER_CHECKPOINT", flush=True)


def restore(root: str) -> bool:
    if _remote_manifest() is None:
        print("CDB_INBOX_PREPARED_BATCH_ABSENT", flush=True)
        return False
    document, blob = _download()
    if document.get("folder_id") != root:
        raise PendingInvalid("Prepared batch belongs to another Drive root")
    items = _unpack(document, blob)
    base = document.get("base_sha")
    if not isinstance(base, str):
        raise PendingInvalid("Prepared checkpoint base absent")
    if base != _base_sha():
        current = ROOT / "private-state" / "current.json"
        # The checkpoint was committed but clearing the staged archive failed.
        if current.is_file() and current.read_bytes() == items["private-state/next.json"]:
            (ROOT / "private-state" / "next.json").write_bytes(items["private-state/next.json"])
            _clear()
            print("CDB_INBOX_PREPARED_ALREADY_CONSUMED", flush=True)
            return False
        raise PendingInvalid("Private checkpoint moved since source was prepared")
    for name, data in items.items():
        target = ROOT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    print("CDB_INBOX_PREPARED_BATCH_RESTORED", len(items), flush=True)
    return True


def persist(root: str) -> None:
    contents = _files()
    base = _base_sha()
    expected = _expected(root, contents, base)
    if _remote_manifest() is not None:
        document, blob = _download()
        _unpack(document, blob)
        if {key: document.get(key) for key in expected} != expected:
            raise PendingInvalid("Different pending batch already exists in private CDB")
        print("CDB_INBOX_PREPARED_BATCH_ALREADY_SAVED", flush=True)
        return
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(ARTIFACT, "w:gz") as tar:
        for name, data in sorted(contents.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    blob = ARTIFACT.read_bytes()
    if len(blob) > MAX_COMPRESSED:
        raise PendingInvalid("Compressed prepared batch exceeds private release budget")
    document = {**expected, "archive_sha256": sha256(blob)}
    MANIFEST.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    _gh(["release", "create", PENDING_TAG, str(ARTIFACT), str(MANIFEST),
         "-R", PRIVATE_REPO, "--title", "Private CDB inbox staged source",
         "--notes", "Verified private-only normalized Drive source awaiting safe CDB publication"])
    remote_document, remote_blob = _download()
    if remote_document != document or _unpack(remote_document, remote_blob) != contents:
        raise PendingInvalid("Private normalized source remote readback mismatch")
    print("CDB_INBOX_PREPARED_PRIVATE_READBACK_VERIFIED", flush=True)


def _output(restored: bool) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise PendingInvalid("GITHUB_OUTPUT missing")
    with open(path, "a", encoding="utf-8") as out:
        out.write(f"restored={str(restored).lower()}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("restore", "persist", "clear"))
    parser.add_argument("--folder-id", required=True)
    args = parser.parse_args()
    if args.action == "restore":
        _output(restore(args.folder_id))
    elif args.action == "persist":
        persist(args.folder_id)
    else:
        _clear()


if __name__ == "__main__":
    main()
