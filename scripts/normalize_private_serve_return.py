"""Normalize private TennisAPI statistics staging into importer schema v2.

The output deliberately keeps home/away orientation UNVERIFIED. Canonical player
orientation is resolved later by import_private_serve_return.py against the
private tbt-data history. Raw provider responses never need to enter the app repo.
"""
from __future__ import annotations

import argparse
import json
import math
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


COUNT_KEYS = {
    "aces": "aces",
    "doubleFaults": "double_faults",
}
RATE_KEYS = {
    "firstServePointsAccuracy": "first_serve_win",
    "secondServePointsAccuracy": "second_serve_win",
}


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _all_period_items(provider_response: object) -> dict[str, dict]:
    if not isinstance(provider_response, dict):
        return {}
    periods = provider_response.get("statistics")
    if not isinstance(periods, list):
        return {}
    all_period = next(
        (
            row for row in periods
            if isinstance(row, dict)
            and str(row.get("period") or "").strip().upper() == "ALL"
        ),
        None,
    )
    if not isinstance(all_period, dict):
        return {}
    items = {}
    for group in all_period.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("statisticsItems") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if key:
                items[key] = item
    return items


def _ratio(item: dict | None, side: str):
    if not isinstance(item, dict):
        return None
    won = _number(item.get(side + "Value"))
    total = _number(item.get(side + "Total"))
    if won is None or total is None or total <= 0 or won < 0 or won > total:
        return None
    return won / total


def extract_home_away_stats(provider_response: object) -> dict[str, float | int]:
    items = _all_period_items(provider_response)
    out: dict[str, float | int] = {}

    for side in ("home", "away"):
        for provider_key, target in COUNT_KEYS.items():
            item = items.get(provider_key)
            value = _number(item.get(side + "Value")) if isinstance(item, dict) else None
            if value is not None and value >= 0 and value.is_integer():
                out[f"{side}_{target}"] = int(value)

        for provider_key, target in RATE_KEYS.items():
            value = _ratio(items.get(provider_key), side)
            if value is not None:
                out[f"{side}_{target}"] = value

    # Whole-match serve/return point rates use complementary counters rather
    # than display percentages. For home service points, away receiver points
    # are the lost service points; vice versa for away.
    service = items.get("servicePointsScored")
    receiver = items.get("receiverPointsScored")
    if isinstance(service, dict) and isinstance(receiver, dict):
        home_service = _number(service.get("homeValue"))
        away_service = _number(service.get("awayValue"))
        home_return = _number(receiver.get("homeValue"))
        away_return = _number(receiver.get("awayValue"))

        pairs = (
            ("home_service_points_won", home_service, away_return),
            ("away_service_points_won", away_service, home_return),
            ("home_return_points_won", home_return, away_service),
            ("away_return_points_won", away_return, home_service),
        )
        for key, won, lost in pairs:
            if won is None or lost is None or won < 0 or lost < 0 or won + lost <= 0:
                continue
            out[key] = won / (won + lost)

    return out


def normalize_raw_row(row: object) -> dict:
    if not isinstance(row, dict):
        raise ValueError("Invalid raw staging row")
    match_id = str(row.get("match_id") or "").strip()
    event_id = str(row.get("event_id") or "").strip()
    if not match_id or not event_id:
        raise ValueError("Raw staging row is missing match/event identity")
    stats = extract_home_away_stats(row.get("provider_response"))
    return {
        "match_id": match_id,
        "provider_event_id": event_id,
        "orientation": "UNVERIFIED",
        "import_ready": False,
        "fetched_at": str(row.get("fetched_at") or ""),
        "home_away_stats": stats,
    }


def build_stage(raw_path: str | Path, out_path: str | Path) -> dict:
    raw_path, out_path = Path(raw_path), Path(out_path)
    rows = []
    seen_matches, seen_events = set(), set()
    field_counts = Counter()
    for line_number, line in enumerate(raw_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            source = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"Invalid JSON on raw staging line {line_number}") from exc
        row = normalize_raw_row(source)
        if row["match_id"] in seen_matches:
            raise ValueError("Duplicate raw staging match ID")
        if row["provider_event_id"] in seen_events:
            raise ValueError("Duplicate raw staging provider event ID")
        seen_matches.add(row["match_id"])
        seen_events.add(row["provider_event_id"])
        field_counts.update(row["home_away_stats"].keys())
        rows.append(row)

    if not rows:
        raise ValueError("Raw staging contains no rows")

    with_quality = sum(
        1 for row in rows
        if any(
            key.endswith("service_points_won") or key.endswith("return_points_won")
            for key in row["home_away_stats"]
        )
    )
    both_quality = sum(
        1 for row in rows
        if all(
            row["home_away_stats"].get(f"{side}_{metric}") is not None
            for side in ("home", "away")
            for metric in ("service_points_won", "return_points_won")
        )
    )
    manifest = {
        "schema_version": 2,
        "source_schema": 1,
        "stage_rows": len(rows),
        "rows_with_serve_return_quality": with_quality,
        "rows_with_both_players_quality": both_quality,
        "field_counts": dict(sorted(field_counts.items())),
        "orientation": "UNVERIFIED",
        "import_ready": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "staged_serve_return.jsonl",
            "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        )
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True, help="provider_responses.jsonl")
    parser.add_argument("--out", required=True, help="private schema-v2 staging ZIP")
    args = parser.parse_args()
    manifest = build_stage(args.raw, args.out)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
