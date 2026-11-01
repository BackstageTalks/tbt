"""Repair canonical history without guessing ambiguous match identities.

This is the safe gate for writer runs. It is intentionally conservative:
- malformed identity rows / impossible self-matches / malformed statistics are quarantined;
- provably identical provider events are merged deterministically;
- unresolved duplicate match/provider identities are quarantined as a group;
- only changed year partitions are rewritten;
- a corruption budget prevents a broad data-loss event from being auto-published.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import date
from collections import Counter
from numbers import Real
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.data.history_snapshot import (
    load_snapshot, write_year_partition, load_manifest,
    _interpret_wimbledon_2023_count_fields,
)
from tbt.data.history_safety import (sanitize_history_identities, quarantine_budget,
    guard_scoped_history_identity_repair)
from tbt.services.data_quality import audit_history
from tbt.utils import is_rate_stat_field

NULLISH = {"", "nan", "none", "null", "<na>", "nat"}


def clean_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.casefold() in NULLISH else text


def _valid_stats_json(value, *, row=None, scheduled_at=None) -> bool:
    if value in (None, ""):
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    try:
        data = value if isinstance(value, dict) else json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    if (row is not None and scheduled_at is not None
            and scheduled_at.year == 2023
            and clean_text(row.get("tour")).lower() == "wta"
            and "wimbledon" in clean_text(row.get("tournament")).lower()):
        # Match the canonical reader's narrowly pinned Wimbledon 2023
        # count-vs-rate compatibility rule before classifying a RAW row
        # as invalid. The raw bytes are preserved; we do not normalize
        # other matches or relax bounds on genuine rate statistics.
        try:
            data = _interpret_wimbledon_2023_count_fields(
                data,
                tour=clean_text(row.get("tour")),
                scheduled_at=scheduled_at,
                tournament=clean_text(row.get("tournament")),
                player1_name=clean_text(row.get("player1_name")),
                player2_name=clean_text(row.get("player2_name")),
            )
        except (ValueError, TypeError):
            return False
    for key, item in data.items():
        if item in (None, ""):
            continue
        if isinstance(item, bool) or not isinstance(item, Real):
            return False
        numeric = float(item)
        if not math.isfinite(numeric):
            return False
        if is_rate_stat_field(str(key)) and not 0.0 <= numeric <= 1.0:
            return False
    return True


def invalid_reason(row) -> str | None:
    match_id = clean_text(row.get("match_id"))
    p1 = clean_text(row.get("player1_id"))
    p2 = clean_text(row.get("player2_id"))
    if not match_id:
        return "missing_match_id"
    if not p1 or not p2:
        return "missing_player_identity"
    if p1 == p2:
        return "identical_player_ids"
    try:
        parsed = pd.to_datetime(row.get("scheduled_at"), utc=True, errors="raise")
        if pd.isna(parsed):
            return "invalid_scheduled_at"
    except Exception:
        return "invalid_scheduled_at"
    if not _valid_stats_json(row.get("stats_json"), row=row, scheduled_at=parsed):
        return "invalid_statistics"
    return None


def _year_identity_counter(records, year: int) -> Counter:
    return Counter(
        (
            str(m.match_id or ""),
            str(m.scheduled_at.isoformat()),
            str(m.player1_id or ""),
            str(m.player2_id or ""),
            str(m.winner_id or ""),
        )
        for m in records
        if int(m.scheduled_at.year) == int(year)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument("--release-tag", default="tbt-data-v1")
    parser.add_argument("--max-details", type=int, default=200)
    parser.add_argument("--max-quarantine-ratio", type=float, default=0.001)
    parser.add_argument("--min-quarantine-budget", type=int, default=20)
    parser.add_argument("--max-quarantine-rows", type=int, default=500)
    parser.add_argument("--scope-start", default=None,
                        help="Bound a read-only integrity preflight to the target history years")
    parser.add_argument("--scope-end", default=None,
                        help="Required with --scope-start; no canonical repair is published")
    args = parser.parse_args()
    if bool(args.scope_start) != bool(args.scope_end):
        parser.error("--scope-start and --scope-end must be supplied together")
    scope = None
    if args.scope_start:
        try:
            scope = (date.fromisoformat(args.scope_start), date.fromisoformat(args.scope_end))
        except ValueError as exc:
            parser.error(f"Invalid scoped history date: {exc}")

    directory = ROOT / ".cache/tbt/history-repair-all"
    directory.mkdir(parents=True, exist_ok=True)
    store = ReleaseStore(args.data_repository, args.release_tag, directory)
    store.download()

    partitions = sorted(directory.glob("history-*.parquet"))
    if not partitions:
        raise SystemExit("No history partitions found")

    raw_quarantine = []
    original_rows = 0
    original_years = set()
    parsed_records = []
    raw_changed_years = set()

    with tempfile.TemporaryDirectory() as temp_name:
        temp = Path(temp_name)
        for path in partitions:
            try:
                year = int(path.stem.split("-")[-1])
                original_years.add(year)
            except Exception:
                year = None
            frame = pd.read_parquet(path, engine="pyarrow")
            original_rows += len(frame)
            keep = []
            for row_number, (_, row) in enumerate(frame.iterrows(), start=1):
                reason = invalid_reason(row)
                if reason:
                    if year is not None:
                        raw_changed_years.add(year)
                    raw_quarantine.append({
                        "file": path.name,
                        "row": row_number,
                        "match_id": clean_text(row.get("match_id")),
                        "player1_id": clean_text(row.get("player1_id")),
                        "player2_id": clean_text(row.get("player2_id")),
                        "scheduled_at": clean_text(row.get("scheduled_at")),
                        "reason": reason,
                    })
                else:
                    keep.append(row.name)
            clean = frame.loc[keep].copy()
            if clean.empty:
                continue
            staged = temp / path.name
            clean.to_parquet(staged, engine="pyarrow", compression="zstd", index=False)
            parsed_records.extend(load_snapshot(staged))

    safe, identity = sanitize_history_identities(parsed_records)
    _, strict_report = audit_history(safe)

    identity_changed_years = set(identity.get("affected_years") or [])
    changed_years = set(raw_changed_years) | identity_changed_years
    for year in original_years | {int(m.scheduled_at.year) for m in safe}:
        if _year_identity_counter(parsed_records, year) != _year_identity_counter(safe, year):
            changed_years.add(int(year))

    total_quarantined = len(raw_quarantine) + int(identity.get("quarantined_rows") or 0)
    limit = quarantine_budget(
        original_rows,
        ratio=args.max_quarantine_ratio,
        minimum=args.min_quarantine_budget,
        maximum=args.max_quarantine_rows,
    )
    report = {
        "schema": 2,
        "status": "clean" if not changed_years else "repaired",
        "input_rows": int(original_rows),
        "raw_invalid_rows_quarantined": len(raw_quarantine),
        "identity": identity,
        "total_quarantined": total_quarantined,
        "quarantine_budget": limit,
        "changed_years": sorted(changed_years),
        "output_rows": len(safe),
        "strict_history_quality": strict_report,
        "raw_quarantine": raw_quarantine[: max(0, args.max_details)],
        "raw_quarantine_truncated": max(0, len(raw_quarantine) - max(0, args.max_details)),
        "policy": "merge only proven identities; quarantine unresolved collisions; never guess",
    }

    if total_quarantined > limit:
        report["status"] = "blocked_large_corruption"
        report_path = directory / "history_repair_report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        raise SystemExit(
            f"History repair blocked: {total_quarantined} quarantined rows exceed safety budget {limit}."
        )

    if scope is not None:
        # A historical one-off must not rewrite unrelated (e.g. 2026) CDB
        # partitions to "repair" unresolved native-ID collisions. The
        # canonical release remains unchanged; only a local QA report is saved.
        disposition = guard_scoped_history_identity_repair(
            changed_years, start=scope[0], end=scope[1])
        report["scoped_history_disposition"] = disposition
        report["status"] = ("scoped_out_of_scope_identity_quarantine"
                            if changed_years else "clean")
        report["canonical_writes"] = 0
        report_path = directory / "history_repair_report.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(json.dumps({
            "status": report["status"],
            "scope": disposition,
            "input_rows": report["input_rows"],
            "total_quarantined": report["total_quarantined"],
            "canonical_writes": 0,
        }, sort_keys=True), flush=True)
        return

    if not changed_years:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return

    final_years = {int(m.scheduled_at.year) for m in safe}
    output_paths = []
    remove_names = []
    for year in sorted(changed_years):
        selected = [m for m in safe if int(m.scheduled_at.year) == year]
        target = directory / f"history-{year:04d}.parquet"
        if selected:
            write_year_partition(
                safe,
                directory,
                year,
                extra_manifest={"identity_safety_repair": "repair_history_data_v2"},
            )
            output_paths.append(target)
        elif target.exists():
            target.unlink()
            remove_names.append(target.name)

    manifest = load_manifest(directory)
    years_map = manifest.get("years") if isinstance(manifest, dict) else None
    if isinstance(years_map, dict):
        manifest_changed = False
        for year in list(years_map):
            if int(year) not in final_years:
                years_map.pop(year, None)
                manifest_changed = True
        if manifest_changed:
            from tbt.data.history_snapshot import write_manifest
            manifest["years"] = years_map
            write_manifest(directory, manifest)

    report_path = directory / "history_repair_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    manifest_path = directory / "history_manifest.json"
    output_paths.extend([manifest_path, report_path])
    store.upload_bundle(output_paths, remove_names=remove_names)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
