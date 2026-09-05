from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from tbt.schemas import MatchRecord
from .provider_context import merge_provider_context, minimize_provider_payload

SNAPSHOT_SCHEMA_VERSION = 2
MANIFEST_SCHEMA_VERSION = 1
PARTITION_PATTERN = re.compile(r"^history-(\d{4})\.parquet$")


def _json_dumps(value: Any) -> str:
    return json.dumps(
        value if value is not None else {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        if pd.isna(value):
            return {}
    except (TypeError, ValueError):
        pass
    if value == "":
        return {}
    try:
        loaded = json.loads(str(value))
        return loaded if isinstance(loaded, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _none_if_na(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _record_to_row(match: MatchRecord) -> dict[str, Any]:
    return {
        "match_id": str(match.match_id),
        "tour": str(match.tour or "").lower(),
        "scheduled_at": match.scheduled_at.astimezone(timezone.utc),
        "player1_id": str(match.player1_id or ""),
        "player1_name": str(match.player1_name or ""),
        "player2_id": str(match.player2_id or ""),
        "player2_name": str(match.player2_name or ""),
        "surface": str(match.surface or "unknown"),
        "tournament": str(match.tournament or ""),
        "tournament_id": str(match.tournament_id or ""),
        "tournament_level": str(match.tournament_level or ""),
        "round_name": str(match.round_name or ""),
        "player1_rank": match.player1_rank,
        "player2_rank": match.player2_rank,
        "winner_id": str(match.winner_id) if match.winner_id else None,
        "status": str(match.status or ""),
        "best_of": match.best_of,
        "indoor": match.indoor,
        "stats_json": _json_dumps(match.stats if isinstance(match.stats, dict) else {}),
        "provider_context_json": _json_dumps(minimize_provider_payload(match.provider_payload)),
    }


def write_snapshot(matches: Iterable[MatchRecord], path: str | Path) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(list(matches), key=lambda item: (item.scheduled_at, str(item.match_id)))
    frame = pd.DataFrame([_record_to_row(match) for match in ordered])
    if frame.empty:
        raise ValueError("Refusing to write an empty training snapshot")
    frame.to_parquet(path, engine="pyarrow", compression="zstd", index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    timestamps = pd.to_datetime(frame["scheduled_at"], utc=True)
    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "rows": int(len(frame)),
        "history_start": timestamps.min().isoformat(),
        "history_end": timestamps.max().isoformat(),
        "sha256": digest,
        "bytes": int(path.stat().st_size),
        "raw_provider_payload_included": False,
        "provider_context": (
            "identity + canonical category + compact venue/location + "
            "_tbt_environment only"
        ),
    }


def load_snapshot(path: str | Path, before: datetime | None = None) -> list[MatchRecord]:
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"History snapshot missing or empty: {path}")
    frame = pd.read_parquet(path, engine="pyarrow")
    if "scheduled_at" not in frame.columns:
        raise ValueError("Invalid history snapshot: scheduled_at column is missing")
    if before is not None:
        cutoff = pd.Timestamp(before.astimezone(timezone.utc))
        scheduled = pd.to_datetime(frame["scheduled_at"], utc=True)
        frame = frame.loc[scheduled < cutoff]

    matches: list[MatchRecord] = []
    for row in frame.to_dict(orient="records"):
        matches.append(
            MatchRecord(
                match_id=str(row.get("match_id") or ""),
                tour=str(row.get("tour") or "").lower(),
                scheduled_at=_dt(row.get("scheduled_at")),
                player1_id=str(row.get("player1_id") or ""),
                player1_name=str(row.get("player1_name") or ""),
                player2_id=str(row.get("player2_id") or ""),
                player2_name=str(row.get("player2_name") or ""),
                surface=str(row.get("surface") or "unknown"),
                tournament=str(row.get("tournament") or ""),
                tournament_id=str(row.get("tournament_id") or ""),
                tournament_level=str(row.get("tournament_level") or ""),
                round_name=str(row.get("round_name") or ""),
                player1_rank=_none_if_na(row.get("player1_rank")),
                player2_rank=_none_if_na(row.get("player2_rank")),
                winner_id=(
                    str(row.get("winner_id"))
                    if _none_if_na(row.get("winner_id")) not in (None, "")
                    else None
                ),
                status=str(row.get("status") or ""),
                best_of=_none_if_na(row.get("best_of")),
                indoor=_none_if_na(row.get("indoor")),
                stats=_json_loads(row.get("stats_json")),
                provider_payload=_json_loads(row.get("provider_context_json")),
            )
        )
    matches.sort(key=lambda item: (item.scheduled_at, str(item.match_id)))
    return matches


def partition_path(directory: str | Path, year: int) -> Path:
    return Path(directory) / f"history-{int(year):04d}.parquet"


def manifest_path(directory: str | Path) -> Path:
    return Path(directory) / "history_manifest.json"


def list_partition_years(directory: str | Path) -> list[int]:
    directory = Path(directory)
    years: list[int] = []
    if not directory.is_dir():
        return years
    for path in directory.iterdir():
        match = PARTITION_PATTERN.match(path.name)
        if match and path.is_file() and path.stat().st_size > 0:
            years.append(int(match.group(1)))
    return sorted(set(years))


def load_manifest(directory: str | Path) -> dict[str, Any]:
    path = manifest_path(directory)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def write_manifest(directory: str | Path, manifest: dict[str, Any]) -> Path:
    path = manifest_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = dict(manifest)
    manifest["manifest_schema_version"] = MANIFEST_SCHEMA_VERSION
    manifest["partition_schema_version"] = SNAPSHOT_SCHEMA_VERSION
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    manifest.setdefault("storage_policy", {"supabase_mode": "rolling_hot_buffer", "year_independent": True})
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def update_year_manifest(
    directory: str | Path,
    year: int,
    partition_meta: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(directory)
    years = manifest.setdefault("years", {})
    previous = years.get(str(year), {}) if isinstance(years, dict) else {}
    entry = dict(previous) if isinstance(previous, dict) else {}
    entry.update(partition_meta)
    entry["year"] = int(year)
    entry["asset"] = partition_path(directory, year).name
    entry.setdefault(
        "coverage_status",
        "partitioned_history",
    )
    if extra:
        entry.update(extra)
    years[str(year)] = entry
    manifest["years"] = years
    write_manifest(directory, manifest)
    return manifest


def write_year_partition(
    matches: Iterable[MatchRecord],
    directory: str | Path,
    year: int,
    *,
    extra_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    year = int(year)
    selected = [
        match
        for match in matches
        if match.scheduled_at.astimezone(timezone.utc).year == year
    ]
    if not selected:
        raise ValueError(f"Refusing to write empty history partition for {year}")
    path = partition_path(directory, year)
    meta = write_snapshot(selected, path)
    update_year_manifest(directory, year, meta, extra=extra_manifest)
    return meta


def load_partitions(
    directory: str | Path,
    *,
    years: Iterable[int] | None = None,
    before: datetime | None = None,
) -> list[MatchRecord]:
    directory = Path(directory)
    selected_years = sorted(set(int(year) for year in years)) if years is not None else list_partition_years(directory)
    if not selected_years:
        raise FileNotFoundError(f"No history-YYYY.parquet partitions found in {directory}")
    matches: list[MatchRecord] = []
    for year in selected_years:
        path = partition_path(directory, year)
        if path.is_file() and path.stat().st_size > 0:
            matches.extend(load_snapshot(path, before=before))
    matches.sort(key=lambda item: (item.scheduled_at, str(item.match_id)))
    return matches


def _legacy_meta(legacy_snapshot: str | Path) -> dict[str, Any]:
    legacy_path = Path(legacy_snapshot)
    candidates = [
        legacy_path.with_name(f"{legacy_path.stem}.meta.json"),
        legacy_path.with_name("training_snapshot.meta.json"),
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return {}


def migrate_legacy_snapshot(
    legacy_snapshot: str | Path,
    directory: str | Path,
) -> dict[str, Any]:
    """Split the old monolithic snapshot locally without reading Supabase.

    V20.6 also carries the old ``source_updated_at_max`` cursor forward.  Without
    this, the first hot-tier sync after partitioning could unnecessarily re-read more of the
    operational buffer than required.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    legacy_path = Path(legacy_snapshot)
    matches = load_snapshot(legacy_path)
    legacy_meta = _legacy_meta(legacy_path)

    by_year: dict[int, list[MatchRecord]] = {}
    for match in matches:
        year = match.scheduled_at.astimezone(timezone.utc).year
        by_year.setdefault(year, []).append(match)

    for year, year_matches in sorted(by_year.items()):
        path = partition_path(directory, year)
        existing = load_snapshot(path) if path.is_file() and path.stat().st_size > 0 else []
        merged = merge_matches(existing, year_matches)
        write_year_partition(
            merged,
            directory,
            year,
            extra_manifest={
                "migration_source": legacy_path.name,
                "coverage_status": (
                    "legacy_snapshot_seed"
                ),
            },
        )

    manifest = load_manifest(directory)
    source_updated_at_max = legacy_meta.get("source_updated_at_max")
    if source_updated_at_max:
        manifest["source_updated_at_max"] = source_updated_at_max
    manifest["migration"] = {
        "source": legacy_path.name,
        "legacy_rows": len(matches),
        "legacy_sha256": legacy_meta.get("sha256"),
        "source_updated_at_max": source_updated_at_max,
        "migrated_at": datetime.now(timezone.utc).isoformat(),
        "supabase_used": False,
    }
    write_manifest(directory, manifest)
    return manifest


def ensure_partitions(
    directory: str | Path,
    *,
    legacy_snapshot: str | Path | None = None,
) -> dict[str, Any]:
    if list_partition_years(directory):
        manifest = load_manifest(directory)
        if not manifest:
            manifest = {"years": {}}
            for year in list_partition_years(directory):
                matches = load_snapshot(partition_path(directory, year))
                meta = write_snapshot(matches, partition_path(directory, year))
                update_year_manifest(directory, year, meta)
            manifest = load_manifest(directory)
        return manifest
    if legacy_snapshot is not None and Path(legacy_snapshot).is_file():
        return migrate_legacy_snapshot(legacy_snapshot, directory)
    raise FileNotFoundError(
        "No partitioned history is available and no legacy training_snapshot.parquet was supplied"
    )


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "SNAPSHOT_SCHEMA_VERSION",
    "ensure_partitions",
    "list_partition_years",
    "load_manifest",
    "load_partitions",
    "load_snapshot",
    "merge_matches",
    "manifest_path",
    "merge_provider_context",
    "migrate_legacy_snapshot",
    "minimize_provider_payload",
    "partition_path",
    "update_year_manifest",
    "write_manifest",
    "write_snapshot",
    "write_year_partition",
]

# ---------------------------------------------------------------------------
# Canonical merge helpers shared by direct provider bootstrap and hot-tier sync
# ---------------------------------------------------------------------------

def _provider_event_id(match: MatchRecord) -> str | None:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    for key in (
        "_tbt_provider_event_id",
        "provider_event_id",
        "event_id",
        "eventId",
        "id",
    ):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    value = event.get("id")
    return str(value) if value not in (None, "") else None


def _signature(match: MatchRecord) -> tuple[str, str, tuple[str, str], str]:
    return (
        str(match.tour or "").lower(),
        match.scheduled_at.astimezone(timezone.utc).date().isoformat(),
        tuple(sorted((str(match.player1_id or ""), str(match.player2_id or "")))),
        str(match.round_name or "").strip().lower(),
    )


def _richness(match: MatchRecord) -> tuple[int, int, int, int]:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    env = payload.get("_tbt_environment")
    environment_score = 2 if isinstance(env, dict) and env.get("venue_resolved") else int(bool(env))
    stats = match.stats if isinstance(match.stats, dict) else {}
    stats_score = sum(value not in (None, "") for value in stats.values())
    normalized = sum(
        value not in (None, "", "unknown")
        for value in (
            match.tournament,
            match.tournament_id,
            match.tournament_level,
            match.round_name,
            match.surface,
            match.status,
            match.best_of,
            match.indoor,
            match.player1_rank,
            match.player2_rank,
        )
    )
    return (environment_score, stats_score, normalized, len(minimize_provider_payload(payload)))


def _merge_record(existing: MatchRecord, incoming: MatchRecord) -> MatchRecord:
    from copy import deepcopy
    from dataclasses import replace

    prefer_incoming = _richness(incoming) >= _richness(existing)
    base = deepcopy(incoming if prefer_incoming else existing)
    other = existing if prefer_incoming else incoming

    merged_stats = dict(existing.stats or {})
    for key, value in (incoming.stats or {}).items():
        if value not in (None, ""):
            merged_stats[key] = value

    updates: dict[str, Any] = {
        "provider_payload": merge_provider_context(
            existing.provider_payload,
            incoming.provider_payload,
        ),
        "stats": merged_stats,
    }
    for field_name in (
        "tournament",
        "tournament_id",
        "tournament_level",
        "round_name",
        "surface",
        "status",
        "player1_rank",
        "player2_rank",
        "best_of",
        "indoor",
    ):
        current = getattr(base, field_name)
        candidate = getattr(other, field_name)
        if current in (None, "", "unknown") and candidate not in (None, "", "unknown"):
            updates[field_name] = candidate
    if not base.winner_id and other.winner_id:
        updates["winner_id"] = other.winner_id
    return replace(base, **updates)


def merge_matches(*groups: Iterable[MatchRecord]) -> list[MatchRecord]:
    by_match: dict[str, MatchRecord] = {}
    for group in groups:
        for match in group:
            key = str(match.match_id)
            by_match[key] = _merge_record(by_match[key], match) if key in by_match else match

    by_provider: dict[str, MatchRecord] = {}
    without_provider: list[MatchRecord] = []
    for match in by_match.values():
        provider_id = _provider_event_id(match)
        if provider_id:
            by_provider[provider_id] = (
                _merge_record(by_provider[provider_id], match)
                if provider_id in by_provider
                else match
            )
        else:
            without_provider.append(match)

    by_signature: dict[tuple[str, str, tuple[str, str], str], MatchRecord] = {}
    for match in list(by_provider.values()) + without_provider:
        signature = _signature(match)
        by_signature[signature] = (
            _merge_record(by_signature[signature], match)
            if signature in by_signature
            else match
        )

    result = list(by_signature.values())
    result.sort(key=lambda item: (item.scheduled_at, str(item.match_id)))
    return result
