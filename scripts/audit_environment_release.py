"""Read-only environment coverage audit for the private GitHub history release.

This script never calls TennisApi, Open-Meteo or Supabase and never writes back to
history.  It downloads the committed ``tbt-data-v1`` release, loads the canonical
history partitions and reports how much historical venue/weather enrichment is
actually usable.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.schemas import MatchRecord

CORE_WEATHER_FIELDS = (
    "temperature_c",
    "relative_humidity_pct",
    "wind_speed_kmh",
)


def parse_utc(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 10:
        text += "T00:00:00+00:00"
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_number(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _environment(match: MatchRecord) -> dict[str, Any]:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    return _as_dict(payload.get("_tbt_environment"))


def _provider_event_id(match: MatchRecord) -> str | None:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    identity = _as_dict(payload.get("_tbt_event_identity"))
    for value in (
        payload.get("_tbt_provider_event_id"),
        payload.get("provider_event_id"),
        payload.get("event_id"),
        payload.get("eventId"),
        _as_dict(payload.get("event")).get("id"),
        identity.get("event_id"),
        payload.get("id"),
    ):
        if value not in (None, ""):
            return str(value)
    return None


def _weather_usable(weather: dict[str, Any]) -> bool:
    return all(_safe_number(weather.get(field)) is not None for field in CORE_WEATHER_FIELDS)


def _richness(match: MatchRecord) -> tuple[int, int, int, int, str]:
    env = _environment(match)
    weather = _as_dict(env.get("weather"))
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    return (
        int(env.get("venue_resolved") is True),
        int(_weather_usable(weather)),
        len(match.stats or {}),
        len(json.dumps(payload, ensure_ascii=False, default=str)),
        str(match.match_id),
    )


def canonicalize(matches: Iterable[MatchRecord]) -> tuple[list[MatchRecord], dict[str, Any]]:
    """Collapse only rows that share a concrete provider event id."""
    grouped: dict[str, list[MatchRecord]] = defaultdict(list)
    without_provider: list[MatchRecord] = []
    for match in matches:
        provider_id = _provider_event_id(match)
        if provider_id is None:
            without_provider.append(match)
        else:
            grouped[provider_id].append(match)

    canonical: list[MatchRecord] = []
    duplicate_groups = 0
    duplicate_rows = 0
    for group in grouped.values():
        if len(group) > 1:
            duplicate_groups += 1
            duplicate_rows += len(group) - 1
        canonical.append(max(group, key=_richness))
    canonical.extend(without_provider)
    canonical.sort(key=lambda m: (m.scheduled_at, str(m.match_id)))
    return canonical, {
        "raw_completed_rows": sum(len(group) for group in grouped.values()) + len(without_provider),
        "canonical_completed_rows": len(canonical),
        "duplicate_groups": duplicate_groups,
        "duplicate_rows_ignored": duplicate_rows,
        "without_provider_event_id": len(without_provider),
    }


def _coverage(matches: Iterable[MatchRecord]) -> dict[str, Any]:
    rows = list(matches)
    counts = Counter()
    unresolved_tournaments = Counter()
    no_weather_tournaments = Counter()

    for match in rows:
        env = _environment(match)
        weather = _as_dict(env.get("weather"))
        indoor = match.indoor is True

        if env:
            counts["with_environment"] += 1
        else:
            counts["missing_environment"] += 1

        if env.get("venue_resolved") is True:
            counts["venue_resolved"] += 1
        elif env:
            counts["unresolved"] += 1
            unresolved_tournaments[match.tournament or "(unknown tournament)"] += 1

        if weather:
            counts["with_weather_object"] += 1
            if _weather_usable(weather):
                counts["usable_weather"] += 1
            else:
                counts["incomplete_weather"] += 1
        elif env.get("venue_resolved") is True and indoor:
            # Indoor matches intentionally skip historical weather calls.
            counts["indoor_resolved_no_weather_expected"] += 1
        elif env.get("venue_resolved") is True:
            counts["outdoor_resolved_no_weather"] += 1
            no_weather_tournaments[match.tournament or "(unknown tournament)"] += 1

        if indoor:
            counts["indoor"] += 1
        elif match.indoor is False:
            counts["outdoor"] += 1
        else:
            counts["indoor_unknown"] += 1

    total = len(rows)
    ratio = lambda value: (value / total) if total else 0.0
    counts_dict = dict(counts)
    return {
        "total": total,
        **counts_dict,
        "coverage": {
            "environment": ratio(counts["with_environment"]),
            "venue_resolved": ratio(counts["venue_resolved"]),
            "weather_object": ratio(counts["with_weather_object"]),
            "usable_weather": ratio(counts["usable_weather"]),
            "usable_environment_or_expected_indoor": ratio(
                counts["usable_weather"] + counts["indoor_resolved_no_weather_expected"]
            ),
        },
        "top_unresolved_tournaments": unresolved_tournaments.most_common(30),
        "top_resolved_without_weather_tournaments": no_weather_tournaments.most_common(30),
    }


def _breakdown(matches: Iterable[MatchRecord], key_fn) -> dict[str, Any]:
    groups: dict[str, list[MatchRecord]] = defaultdict(list)
    for match in matches:
        groups[str(key_fn(match))].append(match)
    return {key: _coverage(group) for key, group in sorted(groups.items())}




def download_committed_history(store: ReleaseStore, directory: Path, *, attempts: int = 5) -> None:
    """Download one checksum-consistent committed release snapshot.

    Environment enrichment uploads changed parquet assets before committing the
    replacement bundle manifest. A read that lands in that narrow interval
    fails checksum validation by design; retrying gives us the latest fully
    committed checkpoint without pausing the writer.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            store.download()
            return
        except (RuntimeError, FileNotFoundError, ValueError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            for path in directory.glob("history-*.parquet"):
                path.unlink(missing_ok=True)
            for name in ("history_manifest.json", store.BUNDLE_MANIFEST):
                (directory / name).unlink(missing_ok=True)
            wait = min(5 * attempt, 20)
            print(
                f"Committed history snapshot changed during audit download; "
                f"retrying in {wait}s ({attempt}/{attempts})...",
                flush=True,
            )
            time.sleep(wait)
    assert last_error is not None
    raise last_error

def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="", help="Optional inclusive UTC/date")
    parser.add_argument("--end", default="", help="Optional exclusive UTC/date")
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument(
        "--history-dir",
        default=str(ROOT / ".cache" / "tbt" / "environment-audit"),
    )
    parser.add_argument(
        "--report",
        default=str(ROOT / ".cache" / "tbt" / "environment_audit_report.json"),
    )
    args = parser.parse_args()

    start = parse_utc(args.start)
    end = parse_utc(args.end)
    if start and end and end <= start:
        parser.error("--end must be later than --start")

    history_dir = Path(args.history_dir)
    store = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    download_committed_history(store, history_dir)
    matches = [match for match in load_partitions(history_dir) if match.is_completed]
    if start is not None:
        matches = [m for m in matches if m.scheduled_at.astimezone(timezone.utc) >= start]
    if end is not None:
        matches = [m for m in matches if m.scheduled_at.astimezone(timezone.utc) < end]

    canonical, duplicates = canonicalize(matches)
    report = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "private-github-release:tbt-data-v1",
        "read_only": True,
        "external_api_calls": 0,
        "supabase_used": False,
        "window": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "usable_weather_definition": list(CORE_WEATHER_FIELDS),
        "duplicates": duplicates,
        "overall": _coverage(canonical),
        "by_tour": _breakdown(canonical, lambda m: (m.tour or "unknown").upper()),
        "by_year": _breakdown(canonical, lambda m: m.scheduled_at.astimezone(timezone.utc).year),
    }
    _write_json(Path(args.report), report)

    overall = report["overall"]
    print("Environment audit (read-only)")
    print(f"Canonical completed matches: {overall['total']:,}")
    print(f"Environment present:        {overall.get('with_environment', 0):,} ({overall['coverage']['environment']:.2%})")
    print(f"Venue resolved:             {overall.get('venue_resolved', 0):,} ({overall['coverage']['venue_resolved']:.2%})")
    print(f"Weather object:             {overall.get('with_weather_object', 0):,} ({overall['coverage']['weather_object']:.2%})")
    print(f"Usable weather:             {overall.get('usable_weather', 0):,} ({overall['coverage']['usable_weather']:.2%})")
    print(f"Expected indoor no-weather: {overall.get('indoor_resolved_no_weather_expected', 0):,}")
    print(f"Unresolved venues:          {overall.get('unresolved', 0):,}")
    print(f"Missing environment:        {overall.get('missing_environment', 0):,}")
    print(f"Report: {args.report}")
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False, default=str))


if __name__ == "__main__":
    main()
