#!/usr/bin/env python3
"""Bounded source-only extraction of ORIGINAL Sackmann .7z archives.

Uses system libarchive (Linux, no shell extraction), whitelists known original
source filenames, refuses links/traversal/bombs/overwrite and SHA-attests bytes.
Never updates a CDB, player crosswalk or provider API.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes.util import find_library
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

NATIVE = re.compile(
    r"^(atp|wta)_matches_(?:(qual_chall|futures|qual_itf)_)?(20\d\d)\.csv$"
)
SLAM = re.compile(
    r"^(20\d\d)-(ausopen|frenchopen|wimbledon|usopen)-(points|matches)\.csv$"
)
MAX_ENTRY_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 900 * 1024 * 1024
MAX_ARCHIVE_FILES = 400
ARCHIVE_OK, ARCHIVE_EOF = 0, 1


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def source_path(entry: str, start: int, end: int) -> tuple[str, str] | None:
    if "\\" in entry or entry.startswith("/") or "\x00" in entry:
        raise ValueError("Unsafe archive path")
    parts = PurePosixPath(entry).parts
    if len(parts) != 2 or any(x in {"", ".", ".."} for x in parts):
        raise ValueError("Unrecognized or unsafe archive directory layout")
    kind, name = parts
    if kind not in {"atp", "wta", "slam_pointbypoint"}:
        raise ValueError("Unexpected archive root")
    if name == "UPSTREAM_README.md":
        return kind, name
    native = NATIVE.fullmatch(name)
    if kind in {"atp", "wta"} and native:
        tour, family, year = native.groups()
        if kind != tour or (tour == "atp" and family == "qual_itf") or (
            tour == "wta" and family in {"qual_chall", "futures"}
        ):
            raise ValueError("Native tour/source-family mismatch")
        return (kind, name) if start <= int(year) <= end else None
    slam = SLAM.fullmatch(name)
    if kind == "slam_pointbypoint" and slam:
        return (kind, name) if start <= int(slam.group(1)) <= end else None
    return None


def _open_libarchive():
    library = find_library("archive")
    if not library:
        raise RuntimeError("system libarchive with 7z support is required")
    lib = ctypes.CDLL(library)
    lib.archive_read_new.restype = ctypes.c_void_p
    for name in (
        "archive_read_support_filter_all", "archive_read_support_format_7zip",
        "archive_read_data_skip", "archive_read_free"
    ):
        getattr(lib, name).argtypes = [ctypes.c_void_p]
    lib.archive_read_open_filename.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t
    ]
    lib.archive_read_next_header.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
    ]
    lib.archive_entry_pathname.argtypes = [ctypes.c_void_p]
    lib.archive_entry_pathname.restype = ctypes.c_char_p
    lib.archive_entry_filetype.argtypes = [ctypes.c_void_p]
    lib.archive_entry_filetype.restype = ctypes.c_uint
    lib.archive_entry_size.argtypes = [ctypes.c_void_p]
    lib.archive_entry_size.restype = ctypes.c_int64
    lib.archive_read_data.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t
    ]
    lib.archive_read_data.restype = ctypes.c_ssize_t
    return lib


def unpack(archives: list[Path], output_dir: Path,
           start_year: int = 2016, end_year: int = 2026) -> dict:
    if not 2011 <= start_year <= end_year <= 2026 or not archives:
        raise ValueError("Invalid year range or no archives")
    lib = _open_libarchive()
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    total_bytes = 0
    locations = set()
    manifests = []
    for archive in archives:
        if not archive.is_file() or archive.suffix.lower() != ".7z":
            raise ValueError("Original .7z archive is required")
        original_sha = sha256(archive)
        ar = lib.archive_read_new()
        if not ar:
            raise RuntimeError("Could not allocate libarchive reader")
        try:
            lib.archive_read_support_filter_all(ar)
            lib.archive_read_support_format_7zip(ar)
            if lib.archive_read_open_filename(ar, str(archive).encode(), 102400) != ARCHIVE_OK:
                raise ValueError(f"Cannot open original archive: {archive.name}")
            pointer = ctypes.c_void_p()
            entries = 0
            selected = 0
            while True:
                status = lib.archive_read_next_header(ar, ctypes.byref(pointer))
                if status == ARCHIVE_EOF:
                    break
                if status != ARCHIVE_OK:
                    raise ValueError("Malformed source 7z archive")
                entries += 1
                if entries > MAX_ARCHIVE_FILES:
                    raise ValueError("Too many archive entries")
                name_ptr = lib.archive_entry_pathname(pointer)
                if not name_ptr:
                    raise ValueError("Archive entry lacks name")
                raw_path = name_ptr.decode("utf-8")
                chosen = source_path(raw_path, start_year, end_year)
                if chosen is None:
                    lib.archive_read_data_skip(ar)
                    continue
                if lib.archive_entry_filetype(pointer) != stat.S_IFREG:
                    raise ValueError("Source archive contains a nonregular selected file")
                size = lib.archive_entry_size(pointer)
                if size < 0 or size > MAX_ENTRY_BYTES or total_bytes + size > MAX_TOTAL_BYTES:
                    raise ValueError("Source archive exceeds bounded expansion")
                destination = output_dir.joinpath(*chosen)
                if chosen in locations or destination.exists():
                    raise ValueError("Duplicate archive member or preexisting output refused")
                locations.add(chosen)
                destination.parent.mkdir(parents=True, exist_ok=True)
                checksum = hashlib.sha256()
                length = 0
                buf = ctypes.create_string_buffer(128 * 1024)
                try:
                    with destination.open("xb") as sink:
                        while True:
                            n = lib.archive_read_data(ar, buf, len(buf))
                            if n == 0:
                                break
                            if n < 0 or length + n > MAX_ENTRY_BYTES:
                                raise ValueError("Corrupt or oversized 7z member")
                            payload = buf.raw[:n]
                            sink.write(payload)
                            checksum.update(payload)
                            length += n
                    if length != size:
                        raise ValueError("Extracted length differs from original 7z header")
                except BaseException:
                    destination.unlink(missing_ok=True)
                    raise
                total_bytes += length
                selected += 1
                extracted.append({
                    "source_archive_sha256": original_sha,
                    "relative_path": "/".join(chosen),
                    "sha256": checksum.hexdigest(),
                    "bytes": length,
                })
            manifests.append({
                "archive_name": archive.name,
                "sha256": original_sha,
                "entries_examined": entries,
                "entries_extracted": selected,
            })
        finally:
            lib.archive_read_free(ar)
    result = {
        "schema": "BLINQ_SACKMANN_NATIVE_ARCHIVE_V1",
        "state": "SOURCE_ONLY", "production_mutated": False,
        "api_requests": 0, "canonical_write_authorized": False,
        "license": "CC BY-NC-SA 4.0; noncommercial without separate rights",
        "total_bytes": total_bytes,
        "archives": manifests, "files": extracted,
    }
    (output_dir / "source_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8"
    )
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, required=True, action="append")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--start-year", type=int, default=2016)
    p.add_argument("--end-year", type=int, default=2026)
    a = p.parse_args()
    result = unpack(a.archive, a.out_dir, a.start_year, a.end_year)
    print(json.dumps({"state": result["state"], "archives": len(result["archives"]),
                      "extracted": len(result["files"]), "bytes": result["total_bytes"]}))


if __name__ == "__main__":
    main()
