#!/usr/bin/env python3
"""Archive MoviOdds FINISHED tennis stats into a dedicated Google Drive folder.

Read-only from BlinQ's independently read-backed Azure Table export endpoint.
Never writes CDB. Immutable SHA-addressed JSON archives: same bytes -> skip,
changed results -> new revision; every uploaded byte is independently reread.
Keeps provider payloads and verified source digests alongside CDB-linkable,
NOT import-ready normalized rows. Drive writer credentials are environment-bound.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from moviodds_cdb_format import format_cdb_archive, verify_cdb_archive

DEFAULT_FOLDER = "13kDDxOaQ0L1Jr5ZjbSNjbDFJiNSz9uwx"
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"


def _json_bytes(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_daily_final(*, date_utc: str, base_url: str, token: str,
                      session=None) -> dict:
    import requests
    date.fromisoformat(date_utc)
    if not token or not base_url.startswith("https://"):
        raise ValueError("Secure export endpoint and worker token required")
    session = session or requests.Session()
    url = base_url.rstrip("/") + "/api/v1/internal/moviodds-stats-worker"
    reply = session.get(url, params={"date": date_utc},
                        headers={"X-Blinq-Worker-Token": token},
                        timeout=60, stream=True)
    reply.raise_for_status()
    content = bytearray()
    for chunk in reply.iter_content(chunk_size=65536):
        content.extend(chunk)
        if len(content) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Stats archive exceeds max bytes")
    body = json.loads(content)
    if (not isinstance(body, dict) or body.get("schema") != 1
        or body.get("verified") is not True
        or body.get("source") != "moviodds"
        or body.get("days") != [date_utc]
        or not isinstance(body.get("records"), list)
        or body.get("count") != len(body["records"])):
        raise ValueError("Invalid final stats export contract")
    for item in body["records"]:
        if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
            raise ValueError("Invalid final stats payload")
        digest = _sha(_json_bytes(item["payload"]).rstrip(b"\n"))
        if item.get("sha256") != digest:
            raise ValueError("Final stats payload digest invalid")
        if item["payload"].get("status") != "finished":
            raise ValueError("Live record cannot enter finalized archive")
        if item["payload"].get("finished_at", "")[:10] != date_utc:
            raise ValueError("Cross-day final stats export")
    return body


def _writer():
    # Use the already-configured BlinQ service account, but request Drive
    # write scope ONLY in this isolated archive job. Other Drive intake jobs
    # continue requesting read-only scope. The operator must grant this
    # identity Editor on the specific MoviOdds folder before activation.
    raw = os.environ.get("BLINQ_DRIVE_WRITER_JSON", "").strip() or os.environ.get(
        "BLINQ_DRIVE_READER_JSON", "").strip()
    if not raw:
        raise RuntimeError("BLOCKED_DRIVE_ARCHIVE_CREDENTIAL_NOT_CONFIGURED")
    info = json.loads(raw)
    from google.auth.transport.requests import AuthorizedSession
    if info.get("type") == "service_account":
        from google.oauth2.service_account import Credentials
        credentials = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"])
    elif info.get("type") == "authorized_user":
        from google.oauth2.credentials import Credentials
        credentials = Credentials.from_authorized_user_info(
            info, scopes=["https://www.googleapis.com/auth/drive"])
    else:
        raise ValueError("Unrecognized Drive writer credential type")
    return AuthorizedSession(credentials)


def _list_name(session, folder_id: str, name: str) -> list[dict]:
    result, token = [], None
    while True:
        params = {
            "q": ("'" + folder_id + "' in parents and name = '" +
                  name.replace("'", "\\'") + "' and trashed = false"),
            "fields": "nextPageToken,files(id,name,size,md5Checksum,mimeType,parents)",
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
            raise ValueError("Incomplete Drive listing")
        result.extend(payload["files"])
        new_token = payload.get("nextPageToken")
        if not new_token:
            return result
        if new_token == token:
            raise ValueError("Repeated Drive page token")
        token = new_token


def _readback(session, file_id: str, expected: bytes) -> None:
    response = session.get(DRIVE_FILES + "/" + file_id,
                           params={"alt": "media", "supportsAllDrives": "true"},
                           timeout=60, stream=True)
    response.raise_for_status()
    body = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        body.extend(chunk)
        if len(body) > MAX_UPLOAD_BYTES:
            raise ValueError("Drive archive readback too large")
    if _sha(body) != _sha(expected) or bytes(body) != expected:
        raise ValueError("Drive archive independent readback mismatch")


def upload_archive(session, *, date_utc: str, folder_id: str, export: dict) -> dict:
    date.fromisoformat(date_utc)
    if not folder_id or not isinstance(export, dict) or export.get("days") != [date_utc]:
        raise ValueError("Archive target/export mismatch")
    verify_cdb_archive(export)
    # Keep empty day exports as reports too, because their absence differs from
    # a successful verified zero-result collection.
    body = _json_bytes(export)
    if len(body) > MAX_UPLOAD_BYTES:
        raise ValueError("Drive archive payload too large")
    sha = _sha(body)
    name = "moviodds-tennis-final-" + date_utc + "-" + sha[:16] + ".json"
    found = _list_name(session, folder_id, name)
    if len(found) > 1:
        raise ValueError("Duplicate file names in Drive archive")
    if found:
        file_id = str(found[0].get("id") or "")
        if not file_id:
            raise ValueError("Existing Drive file has no ID")
        _readback(session, file_id, body)
        return {"status": "already_archived", "id": file_id, "name": name,
                "sha256": sha, "records": export["count"]}
    boundary = "blinqmoviodds" + sha[:24]
    metadata = _json_bytes({"name": name, "parents": [folder_id],
                            "mimeType": "application/json"}).rstrip(b"\n")
    prefix = (("--" + boundary + "\r\n"
               "Content-Type: application/json; charset=UTF-8\r\n\r\n").encode("ascii")
              + metadata + b"\r\n"
              + ("--" + boundary + "\r\nContent-Type: application/json\r\n\r\n").encode("ascii"))
    upload = prefix + body + ("\r\n--" + boundary + "--\r\n").encode("ascii")
    response = session.post(DRIVE_UPLOAD, params={
        "uploadType": "multipart",
        "fields": "id,name,parents,mimeType,size,md5Checksum",
        "supportsAllDrives": "true",
    }, headers={"Content-Type": f"multipart/related; boundary={boundary}"},
       data=upload, timeout=90)
    if not response.ok:
        # Do not print entire Google response, request, service-account key
        # or token. The documented Google reason is sufficient for root cause.
        try:
            error = response.json().get("error") or {}
            reasons = error.get("errors") or []
            reason = str(reasons[0].get("reason") or "") if reasons else ""
            if not reason:
                reason = str(error.get("status") or "unknown")
        except (ValueError, AttributeError, TypeError, IndexError):
            reason = "unavailable"
        raise RuntimeError(
            f"MoviOdds Drive upload denied HTTP {response.status_code} "
            f"reason={reason[:80]}"
        )
    result = response.json()
    if (result.get("name") != name or folder_id not in (result.get("parents") or [])
        or not result.get("id")):
        raise ValueError("Drive upload metadata readback mismatch")
    _readback(session, result["id"], body)
    return {"status": "verified_archived", "id": result["id"], "name": name,
            "sha256": sha, "records": export["count"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="finished UTC date, YYYY-MM-DD")
    ap.add_argument("--folder-id", default=DEFAULT_FOLDER)
    ap.add_argument("--out-dir", type=Path, default=Path("work/moviodds"))
    ap.add_argument("--dry-run", action="store_true", help="no Drive write")
    a = ap.parse_args()
    now = datetime.now(timezone.utc).date()
    requested = date.fromisoformat(a.date)
    if requested > now or (now - requested).days > 7:
        ap.error("Only recent finished dates may be archived")
    source_export = fetch_daily_final(
        date_utc=a.date,
        base_url=os.getenv("BLINQ_PUBLIC_BASE_URL",
                           "https://agreeable-sky-011a7fe10.7.azurestaticapps.net"),
        token=os.environ.get("BLINQ_LIVE_WORKER_TOKEN", ""),
    )
    export = format_cdb_archive(source_export)
    verify_cdb_archive(export)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    local_bytes = _json_bytes(export)
    filename = f"moviodds-tennis-final-{a.date}-{_sha(local_bytes)[:16]}.json"
    path = a.out_dir / filename
    path.write_bytes(local_bytes)
    if _sha(path.read_bytes()) != _sha(local_bytes):
        raise ValueError("Local archive readback mismatch")
    if a.dry_run:
        result = {"status": "dry_run_only", "records": export["count"],
                  "sha256": _sha(local_bytes), "file": filename}
    else:
        result = upload_archive(_writer(), date_utc=a.date,
                                folder_id=a.folder_id, export=export)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
