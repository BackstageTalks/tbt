#!/usr/bin/env python3
"""Fetch bounded files from a private Google Drive inbox without changing Drive.

No source payload is printed, no public artifact is created, no CDB writer runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

MAX_FILES = 100
MAX_BYTES = 256 * 1024 * 1024
MAX_SINGLE = 64 * 1024 * 1024
SUPPORTED = {".csv", ".tsv", ".json", ".jsonl", ".xlsx", ".parquet", ".zip"}
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
BASE = "https://www.googleapis.com/drive/v3/files"

def credentials():
    from google.oauth2.service_account import Credentials
    value = os.environ.get("BLINQ_DRIVE_READER_JSON", "")
    if not value:
        raise RuntimeError("Missing Drive reader secret")
    raw = json.loads(value)
    if raw.get("type") != "service_account":
        raise ValueError("Drive credentials are not a service account")
    return Credentials.from_service_account_info(raw, scopes=[
        "https://www.googleapis.com/auth/drive.readonly"
    ])

def fetch(folder_id: str, output: Path) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{15,150}", folder_id):
        raise ValueError("Invalid Drive inbox ID")
    from google.auth.transport.requests import AuthorizedSession
    session = AuthorizedSession(credentials())
    output.mkdir(parents=True, exist_ok=True)
    files = []
    token = None
    while True:
        params = {
            "q": "'" + folder_id + "' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime)",
            "pageSize": 1000, "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if token:
            params["pageToken"] = token
        response = session.get(BASE, params=params, timeout=90)
        response.raise_for_status()
        page = response.json()
        files.extend(page.get("files", []))
        if len(files) > MAX_FILES:
            raise ValueError("Inbox contains too many files; fail closed")
        token = page.get("nextPageToken")
        if not token:
            break
    files.sort(key=lambda f: (f.get("name", ""), f.get("id", "")))
    entries = []
    total_bytes = 0
    seen_sha = set()
    for info in files:
        name = str(info.get("name") or "")
        mime = info.get("mimeType", "")
        suffix = Path(name).suffix.lower()
        if mime == SHEET_MIME:
            # Only first worksheet is exported by the provider; do not assume
            # it represents a multi-tab workbook. Export stays in review.
            entries.append({"name": name, "status": "review_native_sheet_export_not_enabled"})
            continue
        if suffix not in SUPPORTED:
            entries.append({"name": name, "status": "review_unsupported_format"})
            continue
        size = int(info.get("size") or 0)
        if size > MAX_SINGLE or total_bytes + size > MAX_BYTES:
            entries.append({"name": name, "status": "review_size_budget"})
            continue
        file_id = str(info.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,150}", file_id):
            raise ValueError("Invalid Drive file identifier")
        response = session.get(BASE + "/" + file_id, params={"alt": "media"},
                               timeout=120)
        response.raise_for_status()
        blob = response.content
        if len(blob) > MAX_SINGLE or total_bytes + len(blob) > MAX_BYTES:
            raise ValueError("Drive file exceeds download bounds")
        if size and size != len(blob):
            raise ValueError("Drive file size changed during fetch")
        md5 = info.get("md5Checksum")
        if md5 and hashlib.md5(blob).hexdigest() != md5:
            raise ValueError("Drive file integrity mismatch")
        sha = hashlib.sha256(blob).hexdigest()
        if sha in seen_sha:
            entries.append({"name": name, "status": "duplicate_bytes", "sha256": sha})
            continue
        seen_sha.add(sha)
        # File IDs and arbitrary Drive names never become filesystem paths.
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(name).name)[:90]
        dest = output / (file_id + "__" + safe_name)
        dest.write_bytes(blob)
        total_bytes += len(blob)
        entries.append({"name": name, "status": "fetched", "sha256": sha,
                        "bytes": len(blob), "modified": info.get("modifiedTime"),
                        "local_file": str(dest)})
    manifest = {"schema": 1, "state": "DRIVE_SOURCE_FETCH_ONLY",
                "production_mutated": False, "api_requests": 0,
                "files_seen": len(files), "downloaded_bytes": total_bytes,
                "files": entries}
    (output.parent / "drive_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = fetch(args.folder_id, args.output)
    print(json.dumps({"files_seen": report["files_seen"],
                      "fetched": sum(x["status"] == "fetched" for x in report["files"]),
                      "downloaded_bytes": report["downloaded_bytes"]}))
if __name__ == "__main__":
    main()
