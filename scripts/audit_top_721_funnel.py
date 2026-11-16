"""Read-only, pre-match TOP selection funnel from immutable candidate snapshots.

No provider calls, no CDB/model/publication writes, no odds used as model inputs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
import gzip
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bratislava")
FLOORS = (0.65, 0.70, 0.75, 0.80)


def aware(value):
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None and dt.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def during_day(row, date):
    start = aware(row.get("scheduled_at"))
    if start is None:
        return False
    local = start.astimezone(TZ)
    return local.date().isoformat() == date and local.hour >= 6


def depth_gate(row, *, depth=0.8, surface=5):
    samples = row.get("samples") or {}
    values = [number(samples.get(k)) for k in
              ("player1_surface_matches", "player2_surface_matches")]
    d = number(row.get("data_depth"))
    return d is not None and d >= depth and all(
        x is not None and x >= surface for x in values)


def tour(row):
    name = str(row.get("competition") or row.get("tournament_level") or "").upper()
    if "CHALLENGER" in name:
        return "challenger"
    if "ITF" in name:
        return "itf"
    if name == "ATP" or name == "WTA" or name.startswith(("ATP ", "WTA ")):
        return "main_tour"
    return "other"


def analyze_snapshot(snapshot, day):
    sources = [r for r in snapshot.get("rows", []) if isinstance(r, dict)]
    rows = [r for r in sources if during_day(r, day)]
    reasons, sections, tours, evidence = (Counter() for _ in range(4))
    tiers = {str(int(f * 100)): Counter() for f in FLOORS}
    for row in rows:
        sections[str(row.get("selected_section") or "unselected")] += 1
        tours[tour(row)] += 1
        feature = row.get("feature_evidence")
        if isinstance(feature, dict):
            evidence[str(feature.get("serve_return_known_both"))] += 1
        reason_list = set(str(x) for x in (row.get("top_rejection_reasons") or []) if x)
        reasons.update(reason_list)
        p = number(row.get("blinq_probability"))
        for floor in FLOORS:
            if p is None or p + 1e-12 < floor:
                continue
            tier = tiers[str(int(floor * 100))]
            tier["model_probability_at_least"] += 1
            if depth_gate(row):
                tier["also_top_depth_and_surface"] += 1
                if row.get("priced") is True:
                    tier["priced_after_depth_and_surface"] += 1
                    if not reason_list:
                        tier["passes_recorded_top_gates"] += 1
                else:
                    tier["unpriced_after_depth_and_surface"] += 1
    return {
        "generated_at": snapshot.get("generated_at"),
        "all_singles_in_snapshot": len(sources),
        "today_singles": len(rows),
        "today_priced": sum(r.get("priced") is True for r in rows),
        "selected_sections": dict(sorted(sections.items())),
        "tour_group_counts": dict(sorted(tours.items())),
        "top_rejection_reasons_nonexclusive": dict(sorted(reasons.items())),
        "serve_return_both_available": dict(sorted(evidence.items())),
        "confidence_floor_funnel": {
            k: {key: v.get(key, 0) for key in (
                "model_probability_at_least", "also_top_depth_and_surface",
                "priced_after_depth_and_surface", "unpriced_after_depth_and_surface",
                "passes_recorded_top_gates")} for k, v in tiers.items()
        },
    }


def analyze_archive(data, day):
    if not isinstance(data, dict) or not isinstance(data.get("snapshots"), list):
        raise ValueError("Invalid immutable selector snapshot archive")
    selected = []
    for snapshot in data["snapshots"]:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("rows"), list):
            continue
        t = aware(snapshot.get("generated_at"))
        if t is not None and t.astimezone(TZ).date().isoformat() == day and t.astimezone(TZ).hour >= 6:
            selected.append((t, snapshot))
    if not selected:
        raise ValueError("No snapshot at or after 06:00 on requested local day")
    selected.sort(key=lambda pair: pair[0])
    return {
        "schema": 1,
        "status": "READ_ONLY_DESCRIPTIVE_NOT_MODEL_VALIDATION",
        "betting_day": day,
        "snapshots_today": len(selected),
        "first_snapshot": analyze_snapshot(selected[0][1], day),
        "last_snapshot": analyze_snapshot(selected[-1][1], day),
        "limits": [
            "Unpriced predictions are not actionable bets.",
            "Recorded rejection reasons are nonexclusive.",
            "No settled outcomes in the snapshot: this does not establish improved accuracy.",
            "Odds never enter model probability.",
            "Selection is unchanged; there is no forced fill.",
        ],
        "provider_requests": 0,
        "model_changed": False,
        "CDB_mutated": False,
        "selection_changed": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--day", required=True)
    ap.add_argument("--source", default="")
    ap.add_argument("--out", default=".cache/tbt/top-721-funnel-report.json")
    args = ap.parse_args()
    datetime.fromisoformat(args.day)
    if args.source:
        path = Path(args.source)
    else:
        from release_store import ReleaseStore
        name = f"selection_candidates_{args.day[:7]}.json.gz"
        store = ReleaseStore("BackstageTalks/tbt-data", "tbt-predictions-v1",
                             Path(".cache/tbt/top-721-funnel-candidates"))
        store.download(required_names=(name,), require_bundle_manifest=True)
        path = store.directory / name
    with gzip.open(path, "rt", encoding="utf-8") as fp:
        archive = json.load(fp)
    report = analyze_archive(archive, args.day)
    report["source_sha256"] = sha256(path.read_bytes()).hexdigest()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
