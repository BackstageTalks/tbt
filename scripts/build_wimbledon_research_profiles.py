#!/usr/bin/env python3
"""Build a research-only Wimbledon serve-context player/year profile.

The output is intentionally not wired into production model features. It is a
small reproducible sidecar for later grass-specific ablation research.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median


FIELDS = [
    "year", "player", "surface", "tournament", "matches", "service_points",
    "first_speed_n", "first_speed_mean_mph", "first_speed_median_mph",
    "first_speed_p90_mph", "second_speed_n", "second_speed_mean_mph",
    "second_speed_median_mph", "ace_count", "double_fault_count",
    "serve_and_volley_count", "serve_direction_entropy_bits",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _number(value: object) -> float | None:
    try:
        x = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _server_side(value: object) -> int | None:
    text = str(value or "").strip()
    if text.startswith("1"):
        return 1
    if text.startswith("2"):
        return 2
    return None


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def _percentile90(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = 0.9 * (len(ordered) - 1)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return ordered[low]
    frac = rank - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def _entropy(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return -sum((count / total) * math.log2(count / total) for count in counter.values() if count)


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return ""
    return str(round(float(value), digits))


def build(source_files: list[Path]) -> list[dict[str, object]]:
    acc: dict[tuple[int, str], dict[str, object]] = defaultdict(
        lambda: {
            "matches": set(),
            "service_points": 0,
            "first_speed": [],
            "second_speed": [],
            "ace_count": 0,
            "double_fault_count": 0,
            "serve_and_volley_count": 0,
            "directions": Counter(),
        }
    )
    required = {
        "Tournament", "Year", "Match", "Player1", "Player2", "Server",
        "Service", "ServeDirection", "S_and_V", "SpeedMPH", "ShotMain",
    }

    for path in source_files:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
            for row in reader:
                try:
                    year = int(float(str(row.get("Year") or "").strip()))
                except ValueError:
                    continue
                side = _server_side(row.get("Server"))
                if side not in {1, 2}:
                    continue
                player = str(row.get("Player1") if side == 1 else row.get("Player2") or "").strip()
                if not player:
                    continue

                key = (year, player)
                item = acc[key]
                item["matches"].add(str(row.get("Match") or "").strip())
                item["service_points"] += 1

                service = _number(row.get("Service"))
                speed = _number(row.get("SpeedMPH"))
                if speed is not None and 20.0 <= speed <= 170.0:
                    if service == 1:
                        item["first_speed"].append(speed)
                    elif service == 2:
                        item["second_speed"].append(speed)

                shot = _number(row.get("ShotMain"))
                if shot == 3:
                    item["ace_count"] += 1
                if shot == 5 or service == 0:
                    item["double_fault_count"] += 1
                if _truthy(row.get("S_and_V")):
                    item["serve_and_volley_count"] += 1

                direction = str(row.get("ServeDirection") or "").strip().upper()
                if direction in {"W", "C", "B"}:
                    item["directions"][direction] += 1

    out = []
    for (year, player), item in sorted(acc.items()):
        first = list(item["first_speed"])
        second = list(item["second_speed"])
        out.append({
            "year": year,
            "player": player,
            "surface": "grass",
            "tournament": "Wimbledon",
            "matches": len({m for m in item["matches"] if m}),
            "service_points": int(item["service_points"]),
            "first_speed_n": len(first),
            "first_speed_mean_mph": _fmt(mean(first) if first else None),
            "first_speed_median_mph": _fmt(median(first) if first else None),
            "first_speed_p90_mph": _fmt(_percentile90(first)),
            "second_speed_n": len(second),
            "second_speed_mean_mph": _fmt(mean(second) if second else None),
            "second_speed_median_mph": _fmt(median(second) if second else None),
            "ace_count": int(item["ace_count"]),
            "double_fault_count": int(item["double_fault_count"]),
            "serve_and_volley_count": int(item["serve_and_volley_count"]),
            "serve_direction_entropy_bits": _fmt(_entropy(item["directions"]), 6),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--source-commit", required=True)
    args = ap.parse_args()

    sources = [Path(p) for p in args.source]
    for path in sources:
        if not path.is_file() or path.stat().st_size <= 0:
            raise SystemExit(f"Missing Wimbledon source: {path}")

    rows = build(sources)
    if len(rows) < 400:
        raise SystemExit(f"Unexpectedly small Wimbledon profile: {len(rows)} rows")
    years = sorted({int(r["year"]) for r in rows})
    if years != [2014, 2015]:
        raise SystemExit(f"Unexpected Wimbledon years: {years}")

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    source_meta = [
        {"name": p.name, "sha256": _sha256(p), "bytes": p.stat().st_size}
        for p in sources
    ]
    manifest = {
        "schema": 1,
        "source": "ibm-datapalooza/wimbledon-datasets",
        "source_commit": args.source_commit,
        "license": "Apache-2.0",
        "scope": "Wimbledon 2014-2015 point-level serve context, rounds 1-3 as supplied",
        "rows": len(rows),
        "players": len({str(r["player"]) for r in rows}),
        "years": years,
        "source_files": source_meta,
        "derived_file": target.name,
        "derived_sha256": _sha256(target),
        "model_policy": "research_only_not_promoted; sparse grass-specific historical prior",
        "api_requests": 0,
    }
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
