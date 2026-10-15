#!/usr/bin/env python3
"""Read-only, byte-verified duplicate and CSV-schema audit for the BlinQ Drive root.

No Drive writes, shortcuts, moves, deletes, CDB operations or schedules.
Only verified identical bytes count as duplicate evidence; classification by
filename is a hypothesis until corroborated by a source schema.
All file names, IDs and hashes stay in a private report, not stdout.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import os
from pathlib import Path

try:
    from scripts.drive_sort_prefolders import (
        ROOT, DESTINATIONS, FOLDER_MIME, SHORTCUT_MIME, DriveAPI, classify,
    )
except ModuleNotFoundError:  # direct invocation: python scripts/drive_content_organizer.py
    from drive_sort_prefolders import (
        ROOT, DESTINATIONS, FOLDER_MIME, SHORTCUT_MIME, DriveAPI, classify,
    )

# The legacy pinned BlinQ subfolder contains category 11/12 only.
# Actual source uploads and categories 01-10 live in its parent BlinQ_data.
# Confirmed by independent Google Drive IDs and current parent read-back.
SOURCE_ROOT = "1jzdzztz8cXquO8VDswqE19PHupQau-xM"
CONTAINER_ROOT = ROOT
REVIEW = "12_NA_KONTROLU"
PROTECTED_SUFFIXES = (".zip", ".7z", ".rar", ".tar", ".gz", ".sqlite", ".db")
MAX_SINGLE_FILE = 128 * 1024 * 1024


class BudgetExceeded(ValueError):
    pass


class ContentDriveAPI(DriveAPI):
    def __init__(self, session):
        super().__init__(session)
        self.bytes_downloaded = 0

    def metadata(self, file_id):
        return self.request("GET", "files/" + file_id, params={
            "fields": "id,name,mimeType,parents,trashed,size,md5Checksum,sha256Checksum,modifiedTime",
            "supportsAllDrives": "true",
        })

    def children(self, folder_id):
        token = None
        while True:
            params = {
                "q": "'" + folder_id + "' in parents and trashed = false",
                "fields": "nextPageToken,incompleteSearch,files(id,name,mimeType,parents,size,md5Checksum,sha256Checksum,modifiedTime)",
                "pageSize": 1000, "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if token:
                params["pageToken"] = token
            page = self.request("GET", "files", params=params)
            if page.get("incompleteSearch"):
                raise ValueError("Incomplete Drive listing; refusing organization")
            yield from page.get("files", [])
            token = page.get("nextPageToken")
            if not token:
                break

    def digest(self, item, max_download):
        size = int(item["size"])
        if size < 0 or size > MAX_SINGLE_FILE:
            raise BudgetExceeded("Protected or oversized file")
        if self.bytes_downloaded + size > max_download:
            raise BudgetExceeded("Download budget exceeded")
        url = "https://www.googleapis.com/drive/v3/files/" + item["id"]
        response = self.session.request("GET", url, params={"alt": "media", "supportsAllDrives": "true"},
                                        stream=True, timeout=90)
        try:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("Unexpected full-download status")
            sha = hashlib.sha256()
            md5 = hashlib.md5()
            read = 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                read += len(chunk)
                self.bytes_downloaded += len(chunk)
                if read > size or self.bytes_downloaded > max_download:
                    raise BudgetExceeded("Stream exceeded declared size or budget")
                sha.update(chunk)
                md5.update(chunk)
            if read != size:
                raise ValueError("Full-download byte count mismatch")
            if item.get("md5Checksum") and item["md5Checksum"] != md5.hexdigest():
                raise ValueError("Drive MD5 does not match downloaded bytes")
            if item.get("sha256Checksum") and item["sha256Checksum"].lower() != sha.hexdigest():
                raise ValueError("Drive SHA256 does not match downloaded bytes")
            return sha.hexdigest()
        finally:
            response.close()

    def sniff_category(self, item):
        if item.get("mimeType") not in ("text/csv", "text/plain", "application/csv"):
            return None
        url = "https://www.googleapis.com/drive/v3/files/" + item["id"]
        response = self.session.request(
            "GET", url, params={"alt": "media", "supportsAllDrives": "true"},
            headers={"Range": "bytes=0-8191"}, stream=True, timeout=30,
        )
        try:
            # A non-Range 200 could silently download a huge file; never use it.
            if response.status_code != 206:
                return None
            snippet = next(response.iter_content(chunk_size=8193), b"")
            if len(snippet) > 8192:
                return None
            header = next(csv.reader(io.StringIO(snippet.decode("utf-8-sig").splitlines()[0])), [])
            keys = {k.strip().casefold().replace(" ", "_") for k in header}
            signals = [
                ({"winner", "loser", "date"}, "01_ZAPASY_A_VYSLEDKY"),
                ({"player_id", "rank", "ranking_date"}, "05_REBRICKY_A_ELO"),
                ({"player_id", "aces", "double_faults"}, "04_SERVIS_RETURN_STATISTIKY"),
                ({"match_id", "point_number", "server"}, "03_POINT_BY_POINT"),
            ]
            hits = [category for required, category in signals if required <= keys]
            return hits[0] if len(hits) == 1 else None
        except (UnicodeError, ValueError, IndexError):
            return None
        finally:
            response.close()


def audit(api, *, max_download_mb=512, max_items=12000):
    """Read the source once, fail closed on incomplete listings, make no changes."""
    if not 1 <= max_download_mb <= 2048:
        raise ValueError("Invalid download cap")
    source_root = api.metadata(SOURCE_ROOT)
    if (source_root.get("id") != SOURCE_ROOT or source_root.get("name") != "BlinQ_data"
            or source_root.get("mimeType") != FOLDER_MIME
            or source_root.get("trashed")):
        raise ValueError("Pinned source parent identity mismatch")
    container = api.metadata(CONTAINER_ROOT)
    if (container.get("id") != CONTAINER_ROOT
            or container.get("name") != "BlinQ"
            or container.get("mimeType") != FOLDER_MIME
            or container.get("parents") != [SOURCE_ROOT]
            or container.get("trashed")):
        raise ValueError("Pinned child container identity mismatch")
    records = []
    categories = {}
    for name, folder_id in DESTINATIONS.items():
        folder = api.metadata(folder_id)
        expected_parent = CONTAINER_ROOT if name in ("11_ZALOHY", "12_NA_KONTROLU") else SOURCE_ROOT
        if (folder.get("id") != folder_id or folder.get("name") != name
                or folder.get("mimeType") != FOLDER_MIME
                or folder.get("parents") != [expected_parent] or folder.get("trashed")):
            raise ValueError("Pinned category identity mismatch")
        categories[folder_id] = [f for f in api.children(folder_id)
                                  if f.get("size") is not None
                                  and f.get("mimeType") not in (FOLDER_MIME, SHORTCUT_MIME)]
        if any(f.get("parents") != [folder_id] for f in categories[folder_id]):
            raise ValueError("Unexpected category file parent")
        records.extend(categories[folder_id])
    root_files = [f for f in api.children(SOURCE_ROOT) if f.get("size") is not None
                  and f.get("mimeType") not in (FOLDER_MIME, SHORTCUT_MIME)]
    if any(f.get("parents") != [SOURCE_ROOT] for f in root_files):
        raise ValueError("Unexpected source parent")
    records.extend(root_files)
    if len(records) > max_items or len({f["id"] for f in records}) != len(records):
        raise ValueError("Incomplete, oversized or duplicate-ID inventory")
    max_bytes = max_download_mb * 1024 * 1024
    groups = defaultdict(list)
    for f in records:
        groups[int(f["size"])].append(f)
    digests = {}
    blocked_sizes = set()
    for size, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        for f in sorted(members, key=lambda x: x["id"]):
            try:
                digests[f["id"]] = api.digest(f, max_bytes)
            except (BudgetExceeded, ValueError, OSError):
                blocked_sizes.add(size)
        if any(f["id"] not in digests for f in members):
            blocked_sizes.add(size)
    by_digest = defaultdict(list)
    for f in records:
        if int(f["size"]) not in blocked_sizes and f["id"] in digests:
            by_digest[(int(f["size"]), digests[f["id"]])].append(f)
    duplicate_groups = [g for g in by_digest.values() if len(g) > 1]
    roots = {x["id"] for x in root_files}
    categories_by_name = defaultdict(list)
    for folder_id, items in categories.items():
        for f in items:
            categories_by_name[(folder_id, f["name"].casefold())].append(f)
    output = []
    stats = Counter()
    for source in sorted(root_files, key=lambda x: x["id"]):
        size = int(source["size"])
        entry = {
            "id": source["id"], "name": source["name"], "size": size,
            "parent": SOURCE_ROOT, "sha256": digests.get(source["id"]),
            "metadata_category_hypothesis": classify(source["name"], ()),
            "content_schema_category": None, "status": "unverified",
        }
        if size in blocked_sizes:
            entry["status"] = "bytes_unverified_same_size"
        else:
            matching = next((g for g in duplicate_groups if source["id"] in {m["id"] for m in g}), None)
            if matching:
                entry["status"] = "byte_identical_duplicate_group"
                entry["same_bytes_ids"] = sorted(x["id"] for x in matching if x["id"] != source["id"])
                entry["same_bytes_in_category"] = any(x["id"] not in roots for x in matching)
            elif source["name"].casefold().endswith(PROTECTED_SUFFIXES):
                entry["status"] = "protected_archive_not_duplicate"
            else:
                entry["status"] = "no_known_duplicate_scoped"
        category = entry["metadata_category_hypothesis"]
        if source.get("mimeType") in ("text/csv", "text/plain", "application/csv"):
            try:
                entry["content_schema_category"] = api.sniff_category(source)
            except (ValueError, OSError):
                entry["content_schema_category"] = None
        if (category != REVIEW and entry["content_schema_category"] is not None
                and entry["content_schema_category"] != category):
            entry["status"] = "schema_name_disagreement"
        elif entry["status"] == "no_known_duplicate_scoped":
            entry["status"] = (
                "header_signature_match_plan_only"
                if category != REVIEW and entry["content_schema_category"] == category
                else "filename_only_or_schema_unknown"
            )
        suggested = entry["content_schema_category"] or category
        if suggested != REVIEW:
            dest = DESTINATIONS[suggested]
            collisions = categories_by_name[(dest, source["name"].casefold())]
            if collisions and not any(
                    x["id"] != source["id"] and x["id"] in digests
                    and source["id"] in digests and digests[x["id"]] == digests[source["id"]]
                    and int(x["size"]) == size for x in collisions):
                entry["target_name_conflict_ids"] = [x["id"] for x in collisions]
                entry["status"] = "target_content_conflict_unverified"
        stats[entry["status"]] += 1
        output.append(entry)
    return {
        "schema": 1, "mode": "read_only_plan", "source_originals_moved": 0,
        "source_originals_deleted": 0, "drive_mutations": 0, "cdb_writes": 0,
        "root_loose_files": len(root_files), "category_direct_files": len(records) - len(root_files),
        "confirmed_identical_groups": len(duplicate_groups),
        "confirmed_identical_root_files": sum(sum(f["id"] in roots for f in g) for g in duplicate_groups),
        "unverified_equal_size_groups": len(blocked_sizes),
        "downloaded_bytes": api.bytes_downloaded, "statuses": dict(sorted(stats.items())),
        "note": "Header signature is a hypothesis, not row-semantic validation or permission to move/import.",
        "details": output,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--max-download-mb", type=int, default=512)
    p.add_argument("--max-items", type=int, default=12000)
    args = p.parse_args()
    from google.oauth2.service_account import Credentials
    from google.auth.transport.requests import AuthorizedSession
    credential_json = json.loads(os.environ["BLINQ_DRIVE_SORT_CREDENTIALS"])
    credential = Credentials.from_service_account_info(
        credential_json, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    api = ContentDriveAPI(AuthorizedSession(credential))
    report = audit(api, max_download_mb=args.max_download_mb, max_items=args.max_items)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "details"}, sort_keys=True))


if __name__ == "__main__":
    main()
