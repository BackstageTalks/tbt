#!/usr/bin/env python3
"""Recursive, checkpointed, read-only Drive source intake for canonical CDB.

Inventory every descendant of the configured BlinQ_data folder, assess every
file's format, then fetch only a bounded number of new/changed supported files.
The next checkpoint is NEVER persisted by this script; the guarded workflow
commits it privately only after the entire import/readback succeeds.
"""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import os
import re
from pathlib import Path

MAX_FILES = 100
MAX_BYTES = 256 * 1024 * 1024
MAX_SINGLE = 64 * 1024 * 1024
MAX_FOLDERS = 10000
MAX_INVENTORY = 100000
MAX_DEPTH = 30
SUPPORTED = {".csv", ".tsv", ".json", ".jsonl", ".xlsx", ".parquet", ".zip"}
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
FOLDER_MIME = "application/vnd.google-apps.folder"
BASE = "https://www.googleapis.com/drive/v3/files"


def credentials():
    from google.oauth2.service_account import Credentials
    value = os.environ.get("BLINQ_DRIVE_READER_JSON", "")
    if not value:
        raise RuntimeError("Missing Drive reader secret")
    raw = json.loads(value)
    if raw.get("type") != "service_account":
        raise ValueError("Drive credentials are not a service account")
    return Credentials.from_service_account_info(
        raw, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )


def _inventory(session, root):
    """Page through EVERY folder, refusing partial or runaway inventories."""
    directories = deque([(root, "", 0)])
    visited_folders = set()
    found_files = {}
    while directories:
        folder_id, parent_path, depth = directories.popleft()
        if folder_id in visited_folders:
            continue
        if depth > MAX_DEPTH or len(visited_folders) >= MAX_FOLDERS:
            raise ValueError("Recursive Drive folder guard exceeded")
        visited_folders.add(folder_id)
        page_token = None
        seen_tokens = set()
        while True:
            params = {
                "q": "'" + folder_id + "' in parents and trashed = false",
                "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime)",
                "pageSize": 1000,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            response = session.get(BASE, params=params, timeout=90)
            response.raise_for_status()
            page = response.json()
            if not isinstance(page, dict) or not isinstance(page.get("files"), list):
                raise ValueError("Drive returned incomplete folder listing")
            for info in page["files"]:
                if not isinstance(info, dict):
                    raise ValueError("Invalid Drive file metadata")
                file_id = str(info.get("id") or "")
                if not re.fullmatch(r"[A-Za-z0-9_-]{12,150}", file_id):
                    raise ValueError("Invalid child Drive ID")
                name = str(info.get("name") or "")
                if not name:
                    raise ValueError("Drive file without name")
                path = parent_path + "/" + name
                if info.get("mimeType") == FOLDER_MIME:
                    directories.append((file_id, path, depth + 1))
                else:
                    entry = dict(info)
                    entry["path"] = path
                    # Duplicated ID in an odd multi-parent listing must not
                    # cause two independent writes or source observations.
                    found_files.setdefault(file_id, entry)
                if len(found_files) + len(directories) > MAX_INVENTORY:
                    raise ValueError("Recursive Drive inventory safety limit exceeded")
            next_token = page.get("nextPageToken")
            if not next_token:
                break
            if not isinstance(next_token, str) or next_token in seen_tokens:
                raise ValueError("Invalid or repeated Drive page cursor")
            seen_tokens.add(next_token)
            page_token = next_token
    return sorted(found_files.values(), key=lambda x: (x["path"].casefold(), x["id"])), len(visited_folders)


def _fingerprint(info):
    fields = ("id", "name", "mimeType", "size", "md5Checksum", "modifiedTime")
    encoded = json.dumps(
        [str(info.get(key) or "") for key in fields],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _state(folder_id, path):
    if path is None or not Path(path).is_file():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema") != 1
            or data.get("folder_id") != folder_id
            or not isinstance(data.get("processed"), dict)):
        raise ValueError("Private CDB inbox checkpoint invalid or wrong folder")
    values = data["processed"]
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{12,150}", k)
           or not re.fullmatch(r"[0-9a-f]{64}", str(v))
           for k, v in values.items()):
        raise ValueError("Invalid private CDB inbox fingerprint")
    return dict(values)


def fetch(folder_id: str, output: Path, *, state_path: Path | None = None,
          next_state_path: Path | None = None, session=None, max_files: int = MAX_FILES):
    if not re.fullmatch(r"[A-Za-z0-9_-]{15,150}", folder_id):
        raise ValueError("Invalid Drive inbox root ID")
    if not 1 <= max_files <= MAX_FILES:
        raise ValueError("Invalid bounded per-run file count")
    if session is None:
        from google.auth.transport.requests import AuthorizedSession
        session = AuthorizedSession(credentials())
    output.mkdir(parents=True, exist_ok=True)
    known = _state(folder_id, state_path)
    inventory, folder_count = _inventory(session, folder_id)
    current_ids = {info["id"] for info in inventory}
    # Remove stale metadata for files that are no longer in the selected tree.
    updated = {k: v for k, v in known.items() if k in current_ids}
    entries = []
    candidates = []
    previously_seen = 0
    for info in inventory:
        file_id = info["id"]
        fingerprint = _fingerprint(info)
        if known.get(file_id) == fingerprint:
            previously_seen += 1
            continue
        name = info["name"]
        suffix = Path(name).suffix.lower()
        size = int(info.get("size") or 0)
        if size < 0:
            raise ValueError("Invalid Drive file size")
        if info.get("mimeType") == SHEET_MIME:
            reason = "review_native_sheet_requires_conversion"
        elif suffix not in SUPPORTED:
            reason = "review_unsupported_format"
        elif size > MAX_SINGLE:
            reason = "review_size_budget"
        else:
            candidates.append((info, fingerprint))
            continue
        entries.append({"id": file_id, "status": reason})
        updated[file_id] = fingerprint

    total_bytes = 0
    downloaded = 0
    seen_sha = set()
    for info, fingerprint in candidates:
        if downloaded >= max_files:
            break
        size = int(info.get("size") or 0)
        if total_bytes + size > MAX_BYTES:
            # Keep pending for a later run; other smaller files can fit now.
            continue
        file_id = info["id"]
        response = session.get(BASE + "/" + file_id, params={"alt": "media"}, timeout=120)
        response.raise_for_status()
        blob = response.content
        if len(blob) > MAX_SINGLE or total_bytes + len(blob) > MAX_BYTES:
            raise ValueError("Source bytes exceed download bounds")
        if size and len(blob) != size:
            raise ValueError("Drive source size changed during download")
        md5 = info.get("md5Checksum")
        if md5 and hashlib.md5(blob).hexdigest() != md5:
            raise ValueError("Drive source content checksum mismatch")
        sha = hashlib.sha256(blob).hexdigest()
        total_bytes += len(blob)
        downloaded += 1
        if sha in seen_sha:
            entries.append({"id": file_id, "status": "duplicate_bytes", "sha256": sha})
        else:
            seen_sha.add(sha)
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(info["name"]).name)[:90]
            destination = output / (file_id + "__" + safe)
            destination.write_bytes(blob)
            entries.append({"id": file_id, "status": "fetched", "sha256": sha,
                            "bytes": len(blob), "local_file": str(destination)})
        updated[file_id] = fingerprint
    pending = sum(known.get(info["id"]) != _fingerprint(info)
                  and info["id"] not in updated for info in inventory)
    state = {"schema": 1, "folder_id": folder_id, "processed": updated}
    state_dest = next_state_path or output.parent / "cdb_inbox_next_state.json"
    state_dest.parent.mkdir(parents=True, exist_ok=True)
    state_dest.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
                          encoding="utf-8")
    report = {"schema": 2, "state": "DRIVE_SOURCE_FETCH_ONLY",
              "production_mutated": False, "api_requests": 0,
              "folder_id": folder_id, "recursive": True,
              "folders_seen": folder_count, "inventory_files": len(inventory),
              "previously_seen": previously_seen, "reviewed": len(entries) - downloaded,
              "pending_supported": pending, "fetched": sum(x["status"] == "fetched" for x in entries),
              "downloaded_bytes": total_bytes, "files": entries}
    (output.parent / "drive_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--next-state", type=Path)
    parser.add_argument("--max-files", type=int, default=MAX_FILES)
    args = parser.parse_args()
    report = fetch(args.folder_id, args.output, state_path=args.state_file,
                   next_state_path=args.next_state, max_files=args.max_files)
    print(json.dumps({k: report[k] for k in (
        "folders_seen", "inventory_files", "previously_seen",
        "reviewed", "pending_supported", "fetched", "downloaded_bytes"
    )}))


if __name__ == "__main__":
    main()
