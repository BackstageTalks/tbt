from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from tbt.schemas import MatchRecord

SNAPSHOT_SCHEMA_VERSION = 2

_BASE_COLUMNS = (
    "match_id",
    "tour",
    "scheduled_at",
    "player1_id",
    "player1_name",
    "player2_id",
    "player2_name",
    "surface",
    "tournament",
    "tournament_id",
    "tournament_level",
    "round_name",
    "player1_rank",
    "player2_rank",
    "winner_id",
    "status",
    "best_of",
    "indoor",
)


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


def _compact_country(value: Any) -> dict[str, Any] | str | None:
    if isinstance(value, dict):
        compact = {
            key: value.get(key)
            for key in ("id", "name", "alpha2", "alpha3")
            if value.get(key) not in (None, "")
        }
        return compact or None
    if value not in (None, ""):
        return {"name": str(value)}
    return None


def minimize_provider_payload(payload: Any) -> dict[str, Any]:
    """Keep compact provider context required by identity, environment and features.

    Raw TennisApi payloads are intentionally NOT copied to GitHub.  V2 retains a
    very small venue/location subset in addition to canonical identity/category
    fields so old-history environment enrichment can run directly against the
    GitHub snapshot without round-tripping through Supabase.
    """
    raw = payload if isinstance(payload, dict) else {}
    out: dict[str, Any] = {}

    for key in (
        "_tbt_provider_event_id",
        "provider_event_id",
        "event_id",
        "eventId",
        "id",
        "_tbt_source_category_id",
        "_tbt_source_category_name",
    ):
        if raw.get(key) not in (None, ""):
            out[key] = raw.get(key)

    event = raw.get("event") if isinstance(raw.get("event"), dict) else {}
    if event.get("id") not in (None, ""):
        out["event"] = {"id": event.get("id")}

    tournament = raw.get("tournament") if isinstance(raw.get("tournament"), dict) else {}
    unique = (
        tournament.get("uniqueTournament")
        if isinstance(tournament.get("uniqueTournament"), dict)
        else {}
    )

    compact_tournament: dict[str, Any] = {}
    for key in ("id", "name", "city"):
        if tournament.get(key) not in (None, ""):
            compact_tournament[key] = tournament.get(key)
    tournament_country = _compact_country(tournament.get("country"))
    if tournament_country is not None:
        compact_tournament["country"] = tournament_country

    compact_unique: dict[str, Any] = {}
    for key in ("id", "name", "city"):
        if unique.get(key) not in (None, ""):
            compact_unique[key] = unique.get(key)
    unique_country = _compact_country(unique.get("country"))
    if unique_country is not None:
        compact_unique["country"] = unique_country
    if compact_unique:
        compact_tournament["uniqueTournament"] = compact_unique
    if compact_tournament:
        out["tournament"] = compact_tournament

    venue = raw.get("venue") if isinstance(raw.get("venue"), dict) else {}
    compact_venue: dict[str, Any] = {}
    for key in ("id", "name", "city"):
        if venue.get(key) not in (None, ""):
            compact_venue[key] = venue.get(key)
    venue_country = _compact_country(venue.get("country"))
    if venue_country is not None:
        compact_venue["country"] = venue_country
    if venue.get("countryName") not in (None, ""):
        compact_venue["countryName"] = venue.get("countryName")
    if compact_venue:
        out["venue"] = compact_venue

    for key in ("city", "venueCity", "countryName"):
        if raw.get(key) not in (None, ""):
            out[key] = raw.get(key)
    raw_country = _compact_country(raw.get("country"))
    if raw_country is not None:
        out["country"] = raw_country

    env = raw.get("_tbt_environment")
    if isinstance(env, dict) and env:
        out["_tbt_environment"] = env

    return out


def merge_provider_context(existing: Any, incoming: Any) -> dict[str, Any]:
    """Merge two compact provider payloads without losing existing enrichment."""
    left = minimize_provider_payload(existing)
    right = minimize_provider_payload(incoming)
    merged = dict(left)

    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        elif value not in (None, "", {}):
            merged[key] = value

    # Environment is expensive to resolve, so an already-resolved value wins.
    left_env = left.get("_tbt_environment")
    right_env = right.get("_tbt_environment")
    if isinstance(left_env, dict) and left_env.get("venue_resolved") is True:
        merged["_tbt_environment"] = left_env
    elif isinstance(right_env, dict) and right_env:
        merged["_tbt_environment"] = right_env
    elif isinstance(left_env, dict) and left_env:
        merged["_tbt_environment"] = left_env

    return minimize_provider_payload(merged)


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
        "provider_context_json": _json_dumps(
            minimize_provider_payload(match.provider_payload)
        ),
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
