#!/usr/bin/env python3
"""Bounded, content-verified organizer for loose BlinQ Drive files.

External cron may dispatch the existing Drive audit workflow with organize_drive=true.
Default is read-only. No deletes, overwrites, renames, CDB writes or source-tree moves.
Only direct files under the pinned BlinQ root are candidates; existing subtrees and
archives stay untouched. Source IDs and all per-file evidence remain in a PRIVATE log.
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

    def move(self, item, destination):
        # Preserve the immutable Drive file ID; never rename, overwrite or delete.
        return self.request("PATCH", "files/" + item["id"], params={
            "addParents": destination, "removeParents": ROOT,
            "fields": "id,name,mimeType,parents,size,md5Checksum,sha256Checksum",
            "supportsAllDrives": "true",
        }, json={})


def _is_file(row):
    return row.get("mimeType") not in (FOLDER_MIME, SHORTCUT_MIME) and row.get("size") is not None


def _unchanged(old, now):
    return (now.get("id") == old.get("id")
            and now.get("name") == old.get("name")
            and now.get("mimeType") == old.get("mimeType")
            and str(now.get("size")) == str(old.get("size"))
            and now.get("parents") == old.get("parents")
            and now.get("md5Checksum") == old.get("md5Checksum")
            and now.get("sha256Checksum") == old.get("sha256Checksum")
            and not now.get("trashed", False))


def organize(api, *, apply=False, max_moves=50, max_download_mb=512, max_items=12000):
    """Plan globally before a write, then re-check each move independently."""
    if not 1 <= max_moves <= 50 or not 1 <= max_download_mb <= 2048:
        raise ValueError("Invalid bounded organizer limits")
    max_download = max_download_mb * 1024 * 1024
    root = api.metadata(ROOT)
    if root.get("mimeType") != FOLDER_MIME or root.get("trashed"):
        raise ValueError("Pinned root identity mismatch")
    categorized = []
    for name, fid in DESTINATIONS.items():
        folder = api.metadata(fid)
        if (folder.get("id") != fid or folder.get("name") != name
                or folder.get("mimeType") != FOLDER_MIME
                or folder.get("parents") != [ROOT] or folder.get("trashed")):
            raise ValueError("Pinned category identity mismatch")
        for f in api.children(fid):
            if _is_file(f):
                if f.get("parents") != [fid]:
                    raise ValueError("Unexpected category source parent")
                categorized.append((fid, f))
    root_files = [f for f in api.children(ROOT) if _is_file(f)]
    if len(root_files) + len(categorized) > max_items:
        raise ValueError("Inventory cap reached; refusing partial plan")
    if any(f.get("parents") != [ROOT] for f in root_files):
        raise ValueError("Unexpected source parent")
    if len({f["id"] for f in root_files + [f for _, f in categorized]}) != len(root_files) + len(categorized):
        raise ValueError("Duplicate file IDs in inventory")

    all_files = root_files + [f for _, f in categorized]
    by_size = defaultdict(list)
    for f in all_files:
        by_size[int(f["size"])].append(f)
    digests = {}
    blocked_sizes = set()
    # Cross-name byte verification including files already filed into a category.
    for size, group in sorted(by_size.items()):
        if len(group) < 2:
            continue
        for f in sorted(group, key=lambda x: x["id"]):
            try:
                digests[f["id"]] = api.digest(f, max_download)
            except (BudgetExceeded, ValueError, OSError):
                blocked_sizes.add(size)
        if any(f["id"] not in digests for f in group):
            blocked_sizes.add(size)

    hashes = defaultdict(list)
    for fid, digest in digests.items():
        hashes[digest].append(fid)
    group_by_id = {}
    for members in hashes.values():
        if len(members) > 1:
            for fid in members:
                group_by_id[fid] = sorted(members)

    dest_names = defaultdict(list)
    categorized_ids = set()
    for fid, f in categorized:
        dest_names[(fid, f["name"])].append(f)
        categorized_ids.add(f["id"])
    root_ids = {f["id"] for f in root_files}
    root_by_name = defaultdict(list)
    for f in root_files:
        root_by_name[f["name"]].append(f)
    # Never silently merge distinct datasets that merely share a filename.
    colliding_root_names = {
        name for name, group in root_by_name.items()
        if len(group) > 1 and (any(int(f["size"]) in blocked_sizes for f in group)
                               or len({digests.get(f["id"]) for f in group}) != 1)
    }
    planned_dest_names = {}
    details = []
    actions = []
    for item in sorted(root_files, key=lambda x: x["id"]):
        fid = item["id"]
        result = {"source_id": fid, "name": item["name"], "size": item["size"],
                  "original_parent": ROOT, "state": "held", "destination": None}
        details.append(result)
        if item["name"] in colliding_root_names:
            result["state"] = "root_name_collision"
            continue
        if item["name"].casefold().endswith(PROTECTED_SUFFIXES):
            result["state"] = "protected_archive"
            continue
        if int(item["size"]) in blocked_sizes:
            result["state"] = "unverified_same_size"
            continue
        members = group_by_id.get(fid, [])
        if members:
            # Prefer an existing categorized original; otherwise retain one
            # deterministic canonical root original, separate the other copies.
            category_members = [m for m in members if m in categorized_ids]
            canonical = sorted(category_members)[0] if category_members else sorted(members)[0]
            if canonical != fid:
                target = REVIEW
                result["state"] = "verified_duplicate_review"
                result["same_bytes_as_id"] = canonical
                result["sha256"] = digests[fid]
            else:
                target = classify(item["name"], ())
                result["state"] = "unique_canonical"
        else:
            target = classify(item["name"], ())
            result["state"] = "unique_candidate"

        if target == REVIEW and result["state"] != "verified_duplicate_review":
            target = api.sniff_category(item)
            if not target:
                result["state"] = "unknown_content"
                continue
        if target == "10_POVODNE_ZDROJE_ARCHIVY":
            result["state"] = "protected_source"
            continue
        dest = DESTINATIONS[target]
        if any(existing["id"] != fid for existing in dest_names[(dest, item["name"])]):
            # Equal-name collisions are held unless confirmed byte-identical:
            # even an identical copy is sent only to the review category.
            if result["state"] != "verified_duplicate_review":
                result["state"] = "destination_name_collision"
                continue
        if result["state"] != "verified_duplicate_review":
            key = (dest, item["name"])
            # Even two distinct root names cannot be moved into the same
            # destination with the same filename unless they are byte-identical.
            if key in planned_dest_names and planned_dest_names[key] != digests.get(fid):
                result["state"] = "planned_name_collision"
                continue
        if fid not in digests:
            try:
                digests[fid] = api.digest(item, max_download)
            except (BudgetExceeded, ValueError, OSError):
                result["state"] = "unverified_bytes"
                continue
        if result["state"] != "verified_duplicate_review":
            key = (dest, item["name"])
            if key in planned_dest_names and planned_dest_names[key] != digests[fid]:
                result["state"] = "planned_name_collision"
                continue
            planned_dest_names[key] = digests[fid]
        result["sha256"] = digests[fid]
        result["destination"] = dest
        result["category"] = target
        result["state"] = ("duplicate_to_review" if result["state"] == "verified_duplicate_review"
                           else "classified_verified")
        actions.append((item, result))

    moved = 0
    # No mutation beyond this point unless apply is expressly selected.
    if apply:
        for item, result in actions[:max_moves]:
            now = api.metadata(item["id"])
            if not _unchanged(item, now):
                raise ValueError("Source changed between inventory and move")
            # Independent content verification immediately before relocation.
            if api.digest(now, max_download) != result["sha256"]:
                raise ValueError("Pre-move content changed")
            api.move(item, result["destination"])
            check = api.metadata(item["id"])
            if (check.get("id") != item["id"] or check.get("name") != item["name"]
                    or str(check.get("size")) != str(item["size"])
                    or check.get("parents") != [result["destination"]]
                    or check.get("md5Checksum") != item.get("md5Checksum")
                    or check.get("sha256Checksum") != item.get("sha256Checksum")):
                raise ValueError("Move read-back mismatch; stop all further writes")
            if api.digest(check, max_download) != result["sha256"]:
                raise ValueError("Post-move byte read-back mismatch; stop writes")
            result["state"] = "moved_readback_verified"
            moved += 1
    counts = Counter(r["state"] for r in details)
    return {
        "schema": 1, "mode": "organize" if apply else "organize_plan",
        "root_loose_before": len(root_files),
        "root_loose_after_verified": len(root_files) - moved if apply else None,
        "categorized_existing": len(categorized),
        "confirmed_byte_identical_groups": sum(len(v) > 1 for v in hashes.values()),
        "confirmed_byte_identical_root_files": sum(fid in group_by_id for fid in root_ids),
        "actions_planned": len(actions), "moved_readback_verified": moved,
        "unprocessed_actions": len(actions) - moved,
        "downloaded_bytes": getattr(api, "bytes_downloaded", None),
        "statuses": dict(sorted(counts.items())),
        "source_originals_deleted": 0, "cdb_writes": 0, "details": details,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("plan", "organize"), default="plan")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--max-moves", type=int, default=50)
    p.add_argument("--max-download-mb", type=int, default=512)
    p.add_argument("--max-items", type=int, default=12000)
    args = p.parse_args()
    from google.oauth2.service_account import Credentials
    from google.auth.transport.requests import AuthorizedSession
    credentials = os.environ["BLINQ_DRIVE_SORT_CREDENTIALS"]
    scope = "https://www.googleapis.com/auth/drive" if args.mode == "organize" else "https://www.googleapis.com/auth/drive.readonly"
    info = json.loads(credentials)
    api = ContentDriveAPI(AuthorizedSession(
        Credentials.from_service_account_info(info, scopes=[scope])))
    report = organize(api, apply=args.mode == "organize", max_moves=args.max_moves,
                      max_download_mb=args.max_download_mb, max_items=args.max_items)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "details"}, sort_keys=True))


if __name__ == "__main__":
    main()
