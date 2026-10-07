"""Bulk leakage-safe Open-Meteo 24h pre-match forecast extractor.

This is the read-only closeout variant of the canonical extractor. It preserves
exactly the same *_previous_day1 semantics, but batches multiple venue
coordinates into one Previous Runs API request to reduce HTTP overhead.
"""
from __future__ import annotations

import argparse
import csv
import json
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from _bootstrap import ROOT  # noqa: F401
from extract_open_meteo_pre_match_forecasts import (
    API_URL,
    BASE_VARIABLES,
    LEAD_HOURS,
    SOURCE,
    _eligible,
    _nearest_index,
    _number,
    _parse_day,
    _previous_name,
)
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions

_RATE_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0


def _wait_for_slot(min_interval_seconds: float) -> None:
    global _NEXT_REQUEST_AT
    if min_interval_seconds <= 0:
        return
    with _RATE_LOCK:
        now = time.monotonic()
        wait = max(0.0, _NEXT_REQUEST_AT - now)
        _NEXT_REQUEST_AT = max(_NEXT_REQUEST_AT, now) + min_interval_seconds
    if wait > 0:
        time.sleep(wait)


def _request_many(
    descriptors: list[dict[str, Any]],
    *,
    retries: int,
    timeout_seconds: float,
    min_interval_seconds: float,
) -> list[dict[str, Any]]:
    if not descriptors:
        return []
    start = min(row["start"] for row in descriptors)
    end = max(row["end"] for row in descriptors)
    params = {
        "latitude": ",".join(f"{row['lat']:.4f}" for row in descriptors),
        "longitude": ",".join(f"{row['lon']:.4f}" for row in descriptors),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(_previous_name(name) for name in BASE_VARIABLES),
        "timezone": "UTC",
        "timeformat": "iso8601",
    }
    url = API_URL + "?" + urlencode(params)
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        _wait_for_slot(min_interval_seconds)
        req = Request(url, headers={"User-Agent": "BlinQ research weather bulk extractor"})
        try:
            with urlopen(req, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rows = payload if isinstance(payload, list) else [payload]
            if len(rows) != len(descriptors):
                raise ValueError(
                    f"Open-Meteo multi-location response count mismatch: {len(rows)} != {len(descriptors)}"
                )
            if any(not isinstance(row, dict) or not isinstance(row.get("hourly"), dict) for row in rows):
                raise ValueError("Open-Meteo multi-location response missing hourly data")
            return rows
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < max(1, retries):
                time.sleep(min(8, 2 ** attempt))
    assert last_error is not None
    raise last_error


def _rows_for_descriptor(descriptor: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    hourly = payload.get("hourly") or {}
    times = list(hourly.get("time") or [])
    rows = []
    for match in descriptor["group"]:
        idx = _nearest_index(times, match.scheduled_at)
        if idx is None:
            continue
        values = {}
        for base in BASE_VARIABLES:
            series = hourly.get(_previous_name(base)) or []
            values[base] = _number(series[idx]) if idx < len(series) else None
        if sum(value is not None for value in values.values()) < 3:
            continue
        rows.append({
            "match_id": str(match.match_id),
            "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
            "latitude": descriptor["lat"],
            "longitude": descriptor["lon"],
            "forecast_lead_hours": LEAD_HOURS,
            "forecast_reference": "previous_day1",
            "source": SOURCE,
            "temperature_c": values["temperature_2m"],
            "relative_humidity_pct": values["relative_humidity_2m"],
            "surface_pressure_hpa": values["surface_pressure"],
            "wind_speed_kmh": values["wind_speed_10m"],
            "wind_gusts_kmh": values["wind_gusts_10m"],
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--from-date", default="2024-01-01")
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--max-requests", type=int, default=1800)
    ap.add_argument("--bulk-size", type=int, default=20)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--requests-per-minute", type=int, default=120)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--timeout-seconds", type=float, default=45)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    start = _parse_day(args.from_date)
    end = _parse_day(args.to_date)
    if end < start:
        raise SystemExit("to-date precedes from-date")
    if end >= datetime.now(timezone.utc).date():
        raise SystemExit("Pre-match weather extraction must stop before the current UTC day")
    if not 1 <= args.bulk_size <= 50:
        raise SystemExit("bulk-size must be between 1 and 50")
    if not 1 <= args.workers <= 8:
        raise SystemExit("workers must be between 1 and 8")
    if not 1 <= args.requests_per_minute <= 240:
        raise SystemExit("requests-per-minute must be between 1 and 240")

    matches, safety = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical identity quarantine is non-empty")

    eligible = _eligible(matches, start, end)
    batches: dict[tuple[float, float, int], list[Any]] = defaultdict(list)
    for match, (lat, lon) in eligible:
        batches[(lat, lon, match.scheduled_at.year)].append(match)
    if len(batches) > args.max_requests:
        raise SystemExit(
            f"Need {len(batches)} venue-year source batches but cap is {args.max_requests}; "
            "refusing an implicit partial extraction"
        )

    descriptors = []
    for (lat, lon, year), group in sorted(batches.items()):
        days = [m.scheduled_at.astimezone(timezone.utc).date() for m in group]
        descriptors.append({
            "lat": lat,
            "lon": lon,
            "year": year,
            "start": min(days),
            "end": max(days),
            "group": group,
        })

    # Keep common date windows tight so bulk requests do not pull unnecessary
    # multi-month grids. Month buckets are then chunked by a small location cap.
    buckets: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in descriptors:
        buckets[(row["start"].year, row["start"].month)].append(row)

    chunks: list[list[dict[str, Any]]] = []
    for key in sorted(buckets):
        rows = sorted(buckets[key], key=lambda r: (r["start"], r["lat"], r["lon"]))
        for idx in range(0, len(rows), args.bulk_size):
            chunks.append(rows[idx:idx + args.bulk_size])

    min_interval_seconds = 60.0 / float(args.requests_per_minute)

    def process_chunk(chunk: list[dict[str, Any]]):
        try:
            payloads = _request_many(
                chunk,
                retries=args.retries,
                timeout_seconds=args.timeout_seconds,
                min_interval_seconds=min_interval_seconds,
            )
        except Exception as exc:
            return [], [
                {
                    "latitude": row["lat"],
                    "longitude": row["lon"],
                    "year": row["year"],
                    "start": row["start"].isoformat(),
                    "end": row["end"].isoformat(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                for row in chunk
            ]
        out = []
        for descriptor, payload in zip(chunk, payloads):
            out.extend(_rows_for_descriptor(descriptor, payload))
        return out, []

    output_rows: list[dict[str, Any]] = []
    failed_batches: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for rows, failures in pool.map(process_chunk, chunks):
            output_rows.extend(rows)
            failed_batches.extend(failures)

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
    failed_rate = (len(failed_batches) / len(descriptors)) if descriptors else 0.0
    report = {
        "schema": 2,
        "status": "verified" if output_rows else "no_data",
        "source": SOURCE,
        "endpoint": API_URL,
        "lead_hours": LEAD_HOURS,
        "forecast_semantics": "fixed_24h_lead_time_previous_model_runs",
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "canonical_rows": len(matches),
        "eligible_outdoor_resolved_matches": eligible_count,
        "venue_year_batches": len(descriptors),
        "bulk_http_requests": len(chunks),
        "open_meteo_requests": len(chunks),
        "bulk_size": args.bulk_size,
        "workers": args.workers,
        "requests_per_minute": args.requests_per_minute,
        "failed_batches": len(failed_batches),
        "failed_batch_rate": failed_rate,
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
        raise SystemExit("Open-Meteo bulk extraction produced zero leakage-safe rows")
    allowed_failures = max(10, int(len(descriptors) * 0.02))
    if len(failed_batches) > allowed_failures:
        raise SystemExit(
            f"Open-Meteo bulk extraction failed too many venue-year batches: "
            f"{len(failed_batches)} > {allowed_failures}"
        )


if __name__ == "__main__":
    main()
