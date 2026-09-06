from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from tbt.schemas import MatchRecord
from tbt.utils import is_rate_stat_field
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


def _json_loads(
    value: Any,
    *,
    field: str = "json",
    strict: bool = False,
) -> dict[str, Any]:
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
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        if strict:
            raise ValueError(f"Malformed {field}") from exc
        return {}

    if not isinstance(loaded, dict):
        if strict:
            raise ValueError(f"Invalid {field}: expected JSON object")
        return {}
    return loaded


def _validate_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Validate stored canonical statistics without imputing missing values."""
    import math
    from numbers import Real

    validated: dict[str, Any] = {}
    for key, value in stats.items():
        if value in (None, ""):
            validated[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"Invalid statistic value for {key}: {value!r}")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"Non-finite statistic value for {key}: {value!r}")
        if is_rate_stat_field(key) and not 0.0 <= numeric <= 1.0:
            raise ValueError(f"Rate statistic out of range for {key}: {value!r}")
        validated[key] = numeric
    return validated


def _dt(value: Any) -> datetime:
    value = _none_if_na(value)
    if value in (None, ""):
        raise ValueError("Missing historical scheduled_at")
    try:
        if isinstance(value, datetime):
            result = value
        else:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid historical scheduled_at: {value!r}") from exc
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


def _text_or_empty(value: Any) -> str:
    value = _none_if_na(value)
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "<na>", "nat"}:
        return ""
    return text


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
    temporary = path.with_name(path.name + ".tmp")
    try:
        frame.to_parquet(
            temporary,
            engine="pyarrow",
            compression="zstd",
            index=False,
        )
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
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
    for row_number, row in enumerate(frame.to_dict(orient="records"), start=1):
        scheduled_at = _dt(row.get("scheduled_at"))
        player1_id = _text_or_empty(row.get("player1_id"))
        player2_id = _text_or_empty(row.get("player2_id"))

        if not player1_id or not player2_id:
            raise ValueError(
                f"Invalid history snapshot row {row_number}: missing player identity"
            )
        if player1_id == player2_id:
            raise ValueError(
                f"Invalid history snapshot row {row_number}: identical player identities"
            )

        matches.append(
            MatchRecord(
                match_id=_text_or_empty(row.get("match_id")),
                tour=_text_or_empty(row.get("tour")).lower(),
                scheduled_at=scheduled_at,
                player1_id=player1_id,
                player1_name=_text_or_empty(row.get("player1_name")),
                player2_id=player2_id,
                player2_name=_text_or_empty(row.get("player2_name")),
                surface=_text_or_empty(row.get("surface")) or "unknown",
                tournament=_text_or_empty(row.get("tournament")),
                tournament_id=_text_or_empty(row.get("tournament_id")),
                tournament_level=_text_or_empty(row.get("tournament_level")),
                round_name=_text_or_empty(row.get("round_name")),
                player1_rank=_none_if_na(row.get("player1_rank")),
                player2_rank=_none_if_na(row.get("player2_rank")),
                winner_id=_text_or_empty(row.get("winner_id")) or None,
                status=_text_or_empty(row.get("status")),
                best_of=_none_if_na(row.get("best_of")),
                indoor=_none_if_na(row.get("indoor")),
                stats=_validate_stats(
                    _json_loads(
                        row.get("stats_json"),
                        field="stats_json",
                        strict=True,
                    )
                ),
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
    manifest.setdefault("storage_policy", {"supabase_mode": "auth_only", "year_independent": True})
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)
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

    if not _compatible_players(existing, incoming):
        raise ValueError("Cannot merge incompatible player/tour identities")
    if (_provider_event_id(existing) and _provider_event_id(incoming)
            and _provider_event_id(existing) != _provider_event_id(incoming)):
        raise ValueError("Cannot merge conflicting provider event identities")
    prefer_incoming = _richness(incoming) >= _richness(existing)
    if existing.player1_id != incoming.player1_id:
        if prefer_incoming:
            existing = existing.swapped()
        else:
            incoming = incoming.swapped()
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
    # A rank filled from the other record must not inherit the base's claim.
    claims = []
    for name in ("player1_rank", "player2_rank"):
        source = other if name in updates else base
        if getattr(source, name) is not None:
            claims.append((source.provider_payload or {}).get("_tbt_rank_provenance"))
    context = updates["provider_payload"]
    context.pop("_tbt_rank_provenance", None)
    if claims and isinstance(claims[0], dict) and all(c == claims[0] for c in claims):
        context["_tbt_rank_provenance"] = deepcopy(claims[0])
    return replace(base, **updates)


def _compatible_players(left, right):
    return (str(left.tour).lower() == str(right.tour).lower()
            and bool(left.player1_id) and bool(left.player2_id)
            and left.player1_id != left.player2_id
            and {left.player1_id, left.player2_id} == {right.player1_id, right.player2_id})


def _merge_identity(left, right, *, fallback=False):
    if not _compatible_players(left, right):
        return False
    a, b = _provider_event_id(left), _provider_event_id(right)
    if a and b and a != b:
        return False
    if not fallback:
        return bool((a and a == b) or (left.match_id and left.match_id == right.match_id))
    # Missing identities require exact time plus positive tournament agreement.
    # Do not guess a reschedule from players/day/round alone.
    if left.scheduled_at != right.scheduled_at or _signature(left) != _signature(right):
        return False
    if left.tournament_id and right.tournament_id:
        return str(left.tournament_id) == str(right.tournament_id)
    a, b = left.tournament.strip().casefold(), right.tournament.strip().casefold()
    return bool(a and a != "unknown" and a == b)


def merge_matches(*groups: Iterable[MatchRecord]) -> list[MatchRecord]:
    records = []
    by_match, by_provider = {}, {}
    for group in groups:
        for match in group:
            provider = _provider_event_id(match)
            indices = set(by_match.get(str(match.match_id), []))
            if provider:
                indices.update(by_provider.get(provider, []))
            candidates = [i for i in indices if _merge_identity(records[i], match)]
            if len(candidates) == 1:
                index = candidates[0]
                records[index] = _merge_record(records[index], match)
            else:
                index = len(records)
                records.append(match)
            by_match.setdefault(str(match.match_id), []).append(index)
            if provider:
                by_provider.setdefault(provider, []).append(index)

    buckets = {}
    for i, match in enumerate(records):
        buckets.setdefault(_signature(match), []).append(i)
    neighbors = {i: [] for i in range(len(records))}
    for indices in buckets.values():
        for offset, i in enumerate(indices):
            for j in indices[offset + 1:]:
                if _merge_identity(records[i], records[j], fallback=True):
                    neighbors[i].append(j)
                    neighbors[j].append(i)
    # Only mutually unambiguous pairs qualify. A missing-ID record between two
    # conflicting provider events must not be assigned by input order.
    consumed, result = set(), []
    for i, match in enumerate(records):
        if i in consumed:
            continue
        choices = neighbors[i]
        if len(choices) == 1 and neighbors[choices[0]] == [i]:
            j = choices[0]
            match = _merge_record(match, records[j])
            consumed.add(j)
        result.append(match)
    return sorted(result, key=lambda item: (item.scheduled_at, str(item.match_id)))
