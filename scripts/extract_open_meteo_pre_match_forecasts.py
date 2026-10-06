"""Extract leakage-safe Open-Meteo 24h pre-match forecast features.

The Previous Runs API returns values at a fixed lead time. We use *_previous_day1,
which represents the forecast for the valid match hour made 24 hours earlier.
The extractor is research/training-data only: it never mutates canonical history
or the production model.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions

API_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
BASE_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "surface_pressure",
    "wind_speed_10m",
    "wind_gusts_10m",
)
LEAD_DAYS = 1
LEAD_HOURS = 24
SOURCE = "open-meteo-previous-runs"


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _environment(match) -> dict[str, Any]:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    env = payload.get("_tbt_environment")
    return env if isinstance(env, dict) else {}


def _venue(match) -> tuple[float, float] | None:
    env = _environment(match)
    venue = env.get("venue") if isinstance(env.get("venue"), dict) else {}
    lat = _number(venue.get("latitude"))
    lon = _number(venue.get("longitude"))
    if env.get("venue_resolved") is not True or lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return round(lat, 4), round(lon, 4)


def _previous_name(base: str) -> str:
    return f"{base}_previous_day{LEAD_DAYS}"


def _nearest_index(times: list[str], scheduled: datetime) -> int | None:
    if not times:
        return None
    target = scheduled.astimezone(timezone.utc)
    best: tuple[float, int] | None = None
    for idx, raw in enumerate(times):
        try:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        delta = abs((stamp.astimezone(timezone.utc) - target).total_seconds())
        if best is None or delta < best[0]:
            best = (delta, idx)
    if best is None or best[0] > 90 * 60:
        return None
    return best[1]


def _request_json(latitude: float, longitude: float, start: date, end: date, retries: int = 4) -> dict:
    hourly = ",".join(_previous_name(name) for name in BASE_VARIABLES)
    params = {
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": hourly,
        "timezone": "UTC",
        "timeformat": "iso8601",
    }
    url = API_URL + "?" + urlencode(params)
    last_error: Exception | None = None
    for attempt in range(retries):
        req = Request(url, headers={"User-Agent": "BlinQ research weather extractor"})
        try:
            with urlopen(req, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
                raise ValueError("Open-Meteo Previous Runs response missing hourly data")
            return payload
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(20, 2 ** attempt))
    assert last_error is not None
    raise last_error


def _eligible(matches, start: date, end: date):
    rows = []
    for match in matches:
        scheduled = match.scheduled_at.astimezone(timezone.utc)
        day = scheduled.date()
        if day < start or day > end:
            continue
        if getattr(match, "indoor", None) is True:
            continue
        venue = _venue(match)
        if venue is None:
            continue
        rows.append((match, venue))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--from-date", default="2024-01-01")
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--max-requests", type=int, default=700)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    start = _parse_day(args.from_date)
    end = _parse_day(args.to_date)
    if end < start:
        raise SystemExit("to-date precedes from-date")
    if end >= datetime.now(timezone.utc).date():
        raise SystemExit("Pre-match weather extraction must stop before the current UTC day")

    matches, safety = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical identity quarantine is non-empty")

    eligible = _eligible(matches, start, end)
    # One request per venue-year. Tennis events are clustered in short windows,
    # so this preserves API efficiency without requesting multi-year hourly grids.
    batches: dict[tuple[float, float, int], list[Any]] = defaultdict(list)
    for match, (lat, lon) in eligible:
        batches[(lat, lon, match.scheduled_at.year)].append(match)

    if len(batches) > args.max_requests:
        raise SystemExit(
            f"Need {len(batches)} Open-Meteo requests but cap is {args.max_requests}; "
            "refusing an implicit partial extraction"
        )

    output_rows = []
    failed_batches = []
    request_count = 0
    for (lat, lon, year), group in sorted(batches.items()):
        days = [m.scheduled_at.astimezone(timezone.utc).date() for m in group]
        batch_start, batch_end = min(days), max(days)
        request_count += 1
        try:
            payload = _request_json(lat, lon, batch_start, batch_end)
        except Exception as exc:  # fail-soft per venue; final gate requires useful output
            failed_batches.append({
                "latitude": lat,
                "longitude": lon,
                "year": year,
                "start": batch_start.isoformat(),
                "end": batch_end.isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        hourly = payload.get("hourly") or {}
        times = list(hourly.get("time") or [])
        for match in group:
            idx = _nearest_index(times, match.scheduled_at)
            if idx is None:
                continue
            values = {}
            for base in BASE_VARIABLES:
                series = hourly.get(_previous_name(base)) or []
                values[base] = _number(series[idx]) if idx < len(series) else None
            known = sum(value is not None for value in values.values())
            if known < 3:
                continue
            output_rows.append({
                "match_id": str(match.match_id),
                "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                "latitude": lat,
                "longitude": lon,
                "forecast_lead_hours": LEAD_HOURS,
                "forecast_reference": "previous_day1",
                "source": SOURCE,
                "temperature_c": values["temperature_2m"],
                "relative_humidity_pct": values["relative_humidity_2m"],
                "surface_pressure_hpa": values["surface_pressure"],
                "wind_speed_kmh": values["wind_speed_10m"],
                "wind_gusts_kmh": values["wind_gusts_10m"],
            })

    by_id = {}
    for row in output_rows:
        mid = row["match_id"]
        if mid in by_id and by_id[mid] != row:
            raise SystemExit(f"Duplicate conflicting pre-match weather row for {mid}")
        by_id[mid] = row
    output_rows = [by_id[key] for key in sorted(by_id)]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "match_id", "scheduled_at", "latitude", "longitude",
        "forecast_lead_hours", "forecast_reference", "source",
        "temperature_c", "relative_humidity_pct", "surface_pressure_hpa",
        "wind_speed_kmh", "wind_gusts_kmh",
    ]
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)

    eligible_count = len(eligible)
    report = {
        "schema": 1,
        "status": "verified" if output_rows else "no_data",
        "source": SOURCE,
        "endpoint": API_URL,
        "lead_hours": LEAD_HOURS,
        "forecast_semantics": "fixed_24h_lead_time_previous_model_runs",
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "canonical_rows": len(matches),
        "eligible_outdoor_resolved_matches": eligible_count,
        "venue_year_batches": len(batches),
        "open_meteo_requests": request_count,
        "failed_batches": len(failed_batches),
        "failed_batch_samples": failed_batches[:25],
        "matched_rows": len(output_rows),
        "eligible_match_coverage": (len(output_rows) / eligible_count) if eligible_count else 0.0,
        "production_mutated": False,
        "canonical_history_mutated": False,
        "model_promoted": False,
        "identity_safety": safety,
    }
    rp = Path(args.report)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not output_rows:
        raise SystemExit("Open-Meteo extraction produced zero leakage-safe rows")


if __name__ == "__main__":
    main()
