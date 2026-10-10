"""Read-only tournament logo cache inventory. No API requests or asset mutation.

The archived logos are presentation-only; their presence does not establish
reusable copyright permission or production deployment.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from zipfile import ZipFile, BadZipFile

FEED_KEYS = (
    "upcoming", "results", "top200_picks", "prime_picks", "top_daily_picks",
    "top_daily", "daily_picks", "value_picks", "value", "doubles_picks",
    "doubles", "ace_picks", "aces", "ace_markets", "sg_picks",
    "sets_games", "set_game_picks",
)
ARCHIVE_FILE = re.compile(r"^tournaments/([0-9]+)\.(png|jpe?g|webp)$", re.I)


def feed_ids(feed: dict) -> set[str]:
    """Only exact provider IDs; never infer logo identity from a name."""
    ids: set[str] = set()
    lists = [feed.get(key) for key in FEED_KEYS]
    markets = feed.get("markets")
    if isinstance(markets, dict):
        lists.extend(markets.values())
    for rows in lists:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get("tournament_logo_id") or row.get("tournament_id") or row.get("tournamentId")
            if value is not None and str(value).isdigit():
                ids.add(str(value))
    return ids


def _valid_media(data: bytes, extension: str) -> bool:
    ext = extension.lower()
    if ext == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24
    if ext in ("jpg", "jpeg"):
        return data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")
    if ext == "webp":
        return data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def inventory(feed: dict, profiles: dict, archive: ZipFile) -> dict:
    if not isinstance(profiles, dict) or profiles.get("schema") != 1:
        raise ValueError("Tournament profile schema invalid")
    records = profiles.get("tournaments")
    if not isinstance(records, dict):
        raise ValueError("Tournament profiles must contain ID-keyed mapping")
    active = feed_ids(feed)
    archive_files: dict[str, list[dict]] = defaultdict(list)
    unexpected_members = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        match = ARCHIVE_FILE.fullmatch(info.filename)
        if not match:
            unexpected_members += 1
            continue
        identifier, ext = match.groups()
        data = archive.read(info)  # validates ZIP CRC; fails closed on corruption
        archive_files[identifier].append({
            "filename": info.filename,
            "sha256": sha256(data).hexdigest(),
            "size": len(data),
            "valid_magic": _valid_media(data, ext),
        })
    unique_ids = active | set(records) | set(archive_files)
    images_by_hash: dict[str, list[str]] = defaultdict(list)
    rows = []
    for identifier in sorted(unique_ids, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x)):
        profile = records.get(identifier) or {}
        if not isinstance(profile, dict):
            profile = {}
        files = archive_files.get(identifier, [])
        announced = str(profile.get("logo_file") or "")
        matching = [entry for entry in files if entry["filename"].rsplit("/", 1)[-1] == announced]
        if len(files) > 1 or (files and not all(x["valid_magic"] for x in files)):
            status = "invalid_or_ambiguous_archive"
        elif files and announced and len(matching) == 1:
            status = "cached_valid_not_deployment_verified"
        elif files:
            status = "cached_unlinked_filename"
        elif announced:
            status = "profile_points_to_missing_file"
        elif profile.get("logo_status") == "invalid_media":
            status = "invalid_provider_media"
        elif profile.get("logo_status") == "unavailable":
            status = "provider_declared_unavailable"
        elif not profile.get("logo_checked_at"):
            status = "never_attempted_or_not_recorded"
        else:
            status = "missing_other"
        for entry in files:
            images_by_hash[entry["sha256"]].append(identifier)
        rows.append({
            "tournament_id": identifier,
            "in_current_feed": identifier in active,
            "status": status,
            "archive": files,
            "reported_logo_file": announced or None,
            "provider_status": profile.get("logo_status"),
            "provider_checked_at": profile.get("logo_checked_at"),
            "original_url": profile.get("original_url") or profile.get("logo_source_url"),
            "license_declared": profile.get("license") or profile.get("logo_license"),
            "license_verified_for_reuse": False,
            "deployed_verified": False,
        })
    counts = dict(Counter(row["status"] for row in rows))
    duplicates = {hash_value: ids for hash_value, ids in images_by_hash.items() if len(ids) > 1}
    return {
        "schema": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "presentation_only; no model/CDB/provider/API/deploy writes",
        "source_of_truth": "private tbt-player-assets-v1 and tbt-predictions-v1",
        "current_feed_ids": len(active),
        "unique_audited_ids": len(unique_ids),
        "profiles": len(records),
        "archive_provider_ids": len(archive_files),
        "status_counts": counts,
        "unexpected_zip_members": unexpected_members,
        "duplicate_hash_groups": duplicates,
        "deployed_readback_completed": False,
        "license_review_completed": False,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--logos", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    feed = json.loads(args.feed.read_text(encoding="utf-8"))
    profiles = json.loads(args.profiles.read_text(encoding="utf-8"))
    if not isinstance(feed, dict):
        parser.error("Feed must be JSON object")
    with ZipFile(args.logos) as archive:
        result = inventory(feed, profiles, archive)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in ("rows", "duplicate_hash_groups")}, sort_keys=True))


if __name__ == "__main__":
    main()
