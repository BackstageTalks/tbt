#!/usr/bin/env python3
"""Unpack ONLY user-uploaded, exact-byte pinned TML match CSV source years.

This is a read-only intake adapter. Canonical player IDs, dates and event
identities are NEVER inferred here. The existing CDB strict linker + guarded
single writer remain the only route to production.
"""
from __future__ import annotations

from datetime import date
import hashlib
import io
import re
import zipfile

# SHA-256 observed directly from the user's 2026-11-16 upload.
OUTER_SHA256 = "77c3aa3fe4cf89b7d850f8155e6cc4dade53fc31b8c89b1917b54a7aeb59aaec"
NESTED_SHA256 = "8ae140c391d2d0a561a935bc34b70b0747288ab6df764eea948c41e720539c42"
SOURCE_NAME = "TML+ ATP WTA.zip"
MAX_NESTED_BYTES = 32 * 1024 * 1024
MAX_RAW_MATCH_BYTES = 40 * 1024 * 1024
MAX_SOURCES = 44
SOURCE_SNAPSHOT_DAY = date(2026, 11, 16)

FAMILIES = (
    ("atp_tour", "", "atp-"),
    ("wta", "_wta", "wta-"),
    ("atp_challenger", "_challenger", "atp-challenger-"),
    ("atp_qualifying", "_atp_quali", "atp-qualifying-"),
)


def expected_sources() -> dict[str, tuple[str, str, int]]:
    """Original archive path -> safe renamed source filename, tour, year."""
    result: dict[str, tuple[str, str, int]] = {}
    for year in range(2016, 2027):
        for family, suffix, renamed_prefix in FAMILIES:
            if family == "atp_qualifying":
                original = f"atp_quali/{year}_atp_quali.csv"
            else:
                original = f"{year}{suffix}.csv"
            result[original] = (
                f"{renamed_prefix}{year}.csv",
                "wta" if family == "wta" else "atp",
                year,
            )
    assert len(result) == MAX_SOURCES
    return result


def _open_zip(blob: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(blob), "r", allowZip64=True)


def source_members(
    outer_bytes: bytes, *,
    expected_outer_sha: str = OUTER_SHA256,
    expected_nested_sha: str = NESTED_SHA256,
) -> list[tuple[str, bytes]]:
    """Return only the 44 original match CSV bytes, independently hash-pinned.

    The outer digest pins the entire received archive including *all* inner
    bytes and therefore transitively pins each selected CSV without turning
    their source-native numeric/string IDs into canonical identities.
    """
    if (not re.fullmatch(r"[0-9a-f]{64}", str(expected_outer_sha))
            or not re.fullmatch(r"[0-9a-f]{64}", str(expected_nested_sha))):
        raise ValueError("Exact outer/nested SHA-256 pins required")
    if hashlib.sha256(outer_bytes).hexdigest() != expected_outer_sha:
        raise ValueError("Original uploaded TML archive SHA mismatch")
    with _open_zip(outer_bytes) as outer:
        members = [f for f in outer.infolist() if not f.is_dir()]
        if len(members) != len({f.filename for f in members}):
            raise ValueError("Duplicate outer archive paths")
        info = outer.getinfo("tml-data.zip")
        if info.flag_bits & 1 or info.file_size > MAX_NESTED_BYTES:
            raise ValueError("Encrypted or oversized nested TML archive")
        nested_bytes = outer.read(info)
    if hashlib.sha256(nested_bytes).hexdigest() != expected_nested_sha:
        raise ValueError("Nested TML archive SHA mismatch")
    sources = expected_sources()
    with _open_zip(nested_bytes) as nested:
        items = {f.filename: f for f in nested.infolist() if not f.is_dir()}
        if len(items) != len([f for f in nested.infolist() if not f.is_dir()]):
            raise ValueError("Duplicate inner archive paths")
        if not sources.keys() <= items.keys():
            raise ValueError("Missing pinned TML source years")
        if sum(items[p].file_size for p in sources) > MAX_RAW_MATCH_BYTES:
            raise ValueError("Selected TML match sources exceed size budget")
        extracted = []
        for original_path, (safe_name, _tour, _year) in sources.items():
            info = items[original_path]
            if (info.flag_bits & 1 or info.file_size > 3 * 1024 * 1024
                    or info.file_size <= 0):
                raise ValueError("Encrypted, oversized or empty TML source member")
            raw = nested.read(info)
            if len(raw) != info.file_size:
                raise ValueError("TML source member truncated")
            extracted.append((safe_name, raw))
        return extracted


def is_approved_member(member_name: str) -> bool:
    return member_name in {safe for safe, _, _ in expected_sources().values()}


def member_year(member_name: str) -> int:
    if not is_approved_member(member_name):
        raise ValueError("Member outside pinned source set")
    return int(member_name.rsplit("-", 1)[-1].removesuffix(".csv"))
