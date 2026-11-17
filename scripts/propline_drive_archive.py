#!/usr/bin/env python3
"""Immutable, read-back-verified PropLine evening odds archives on Google Drive.

Separate from canonical CDB, predictions, pricing and the MoviOdds stats archive.
The GitHub workflow preserves its private research JSON before invoking this writer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from pathlib import Path

DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
MAX_BYTES = 24 * 1024 * 1024
DEFAULT_FOLDER = "1C7_B2LB37IVTK9gBu2TT9dSj5XClIUKh"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validated_archive(path: Path, target_day: str) -> bytes:
    date.fromisoformat(target_day)
    data = path.read_bytes()
    if not data or len(data) > MAX_BYTES:
        raise ValueError("PropLine archive empty or exceeds safe size")
    report = json.loads(data)
    if not isinstance(report, dict) or (
        report.get("schema"), report.get("source"),
        report.get("target_betting_day")
    ) != (1, "propline_free", target_day):
        raise ValueError("Invalid PropLine archive provenance or betting day")
    if (report.get("cdb_writes") != 0 or
        report.get("published_picks_changed") != 0 or
        report.get("provider_paid_calls") != 0 or
        report.get("provider_requests") != 1 or
        report.get("status") not in ("audited", "no_exact_aces_market_available")):
        raise ValueError("Unsafe or incomplete evening quote snapshot")
    if not isinstance(report.get("events_in_target_window"), list):
        raise ValueError("Missing target event list")
    return data


def authenticated_session():
    raw = (os.getenv("BLINQ_DRIVE_WRITER_JSON") or "").strip()
    if not raw:
        raise RuntimeError("BLOCKED_PROPLINE_DRIVE_WRITER_CREDENTIAL_MISSING")
    info = json.loads(raw)
    from google.auth.transport.requests import AuthorizedSession
    if info.get("type") == "service_account":
        from google.oauth2.service_account import Credentials
        credentials = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive.file"])
    elif info.get("type") == "authorized_user":
        from google.oauth2.credentials import Credentials
        credentials = Credentials.from_authorized_user_info(
            info, scopes=["https://www.googleapis.com/auth/drive"])
    else:
        raise ValueError("Unsupported Google Drive writer credential type")
    return AuthorizedSession(credentials)


def listed(session, folder: str, name: str) -> list:
    if not folder:
        raise ValueError("Missing Drive folder")
    found, token = [], None
    while True:
        params = {
            "q": "'" + folder + "' in parents and name = '" +
                 name.replace("'", "\\'") + "' and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,parents)",
            "pageSize": 100,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if token:
            params["pageToken"] = token
        response = session.get(DRIVE_FILES, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload.get("files"), list):
            raise ValueError("Invalid Drive file listing")
        found.extend(payload["files"])
        next_token = payload.get("nextPageToken")
        if not next_token:
            return found
        if next_token == token:
            raise ValueError("Repeated Drive page token")
        token = next_token


def readback(session, file_id: str, expected: bytes):
    response = session.get(
        DRIVE_FILES + "/" + file_id,
        params={"alt": "media", "supportsAllDrives": "true"},
        timeout=90, stream=True,
    )
    response.raise_for_status()
    data = bytearray()
    for part in response.iter_content(chunk_size=65536):
        data.extend(part)
        if len(data) > MAX_BYTES:
            raise ValueError("Oversized Drive readback")
    if bytes(data) != expected or sha256(data) != sha256(expected):
        raise ValueError("PropLine Drive readback mismatch")


def archive(session, *, data: bytes, day: str, run_id: str, folder: str) -> dict:
    date.fromisoformat(day)
    if not run_id.isdecimal() or not folder:
        raise ValueError("Invalid run ID or folder")
    digest = sha256(data)
    name = f"propline-{day}-{run_id}-{digest[:16]}.json"
    found = listed(session, folder, name)
    if len(found) > 1:
        raise ValueError("Duplicate PropLine Drive archives")
    if found:
        file_id = str(found[0].get("id") or "")
        if not file_id:
            raise ValueError("Missing existing archive ID")
        readback(session, file_id, data)
        return {"status": "already_verified", "file_id": file_id,
                "name": name, "sha256": digest}
    boundary = "blinqpropline" + digest[:24]
    metadata = json.dumps({
        "name": name, "parents": [folder], "mimeType": "application/json",
    }, separators=(",", ":")).encode()
    body = (
        ("--" + boundary + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n").encode()
        + metadata + b"\r\n"
        + ("--" + boundary + "\r\nContent-Type: application/json\r\n\r\n").encode()
        + data + ("\r\n--" + boundary + "--\r\n").encode()
    )
    response = session.post(
        DRIVE_UPLOAD,
        params={"uploadType": "multipart",
                "fields": "id,name,parents,mimeType",
                "supportsAllDrives": "true"},
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        data=body, timeout=90,
    )
    if not response.ok:
        # Never log Drive credential material or response body.
        raise RuntimeError("PropLine Drive write denied HTTP " + str(response.status_code))
    uploaded = response.json()
    file_id = str(uploaded.get("id") or "")
    if (not file_id or uploaded.get("name") != name or
        folder not in (uploaded.get("parents") or [])):
        raise ValueError("PropLine Drive upload metadata mismatch")
    readback(session, file_id, data)
    return {"status": "PERSISTED_VERIFIED_READBACK", "file_id": file_id,
            "name": name, "sha256": digest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--day", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--folder", default=DEFAULT_FOLDER)
    args = parser.parse_args()
    data = validated_archive(args.report, args.day)
    result = archive(authenticated_session(), data=data, day=args.day,
                     run_id=args.run_id, folder=args.folder)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
