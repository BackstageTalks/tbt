"""Strict importer for output of link_offline_serve_return.py.

Default is dry-run. It verifies that the canonical identity recorded by the
linker still exactly matches current private history before any stats can be
applied. No release upload occurs here.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date
from collections import Counter
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions, write_year_partition
from tbt.data.history_safety import sanitize_history_identities
from tbt.models.feature_builder import FeatureBuilder

RATE_FIELDS = {
    "first_serve_win",
    "second_serve_win",
    "service_points_won",
    "return_points_won",
    "first_strike_serve_win",
    "return_in_play_rate",
    "return_deep_rate",
    "break_point_serve_win",
    "break_point_return_win",
    "net_points_win",
    "attacking_points_rate",
    "unforced_error_rate",
}
COUNT_FIELDS = {"aces", "double_faults"}
ALLOWED = {f"{side}_{field}" for side in ("p1", "p2") for field in RATE_FIELDS | COUNT_FIELDS}


def _quality(stats):
    return all(
        FeatureBuilder._extract_quality(stats or {}, side)[0] is not None
        and FeatureBuilder._extract_quality(stats or {}, side)[1] is not None
        for side in ("p1", "p2")
    )


def _signature(match) -> dict[str, str]:
    return {
        "tour": str(match.tour or "").lower(),
        "scheduled_date_utc": match.scheduled_at.date().isoformat(),
        "player1_id": str(match.player1_id),
        "player1_name": str(match.player1_name),
        "player2_id": str(match.player2_id),
        "player2_name": str(match.player2_name),
        "surface": str(match.surface or ""),
        "tournament": str(match.tournament or ""),
        "round_name": str(match.round_name or ""),
        "winner_id": str(match.winner_id or ""),
    }


def _read(path: str) -> list[dict]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Stage line {number} is not an object")
            rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--write-partitions", action="store_true")
    ap.add_argument("--write-history-dir", default="")
    args = ap.parse_args()
    if args.write_history_dir and not args.write_partitions:
        ap.error("--write-history-dir requires --write-partitions")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    by_id = {str(m.match_id): m for m in matches}
    rows = _read(args.stage)
    seen = set()
    counts = Counter()
    review = []
    changed_years = set()
    before = sum(1 for m in matches if _quality(m.stats or {}))

    for row in rows:
        if row.get("schema") != 1 or row.get("import_ready") is not True:
            raise ValueError("Unexpected offline stage trust marker")
        mid = str(row.get("match_id") or "")
        if not mid or mid in seen:
            raise ValueError("Missing or duplicate staged match ID")
        seen.add(mid)
        match = by_id.get(mid)
        if match is None:
            counts["identity_missing"] += 1
            review.append({"match_id": mid, "reason": "identity_missing"})
            continue

        recorded = row.get("canonical")
        if not isinstance(recorded, dict) or recorded != _signature(match):
            counts["identity_changed"] += 1
            review.append({"match_id": mid, "reason": "identity_changed"})
            continue

        delayed = row.get("delayed_observation")
        if delayed is not None:
            if row.get("baseline_stats") != dict(match.stats or {}):
                counts["baseline_stats_changed"] += 1
                review.append({"match_id": mid, "reason": "canonical_baseline_stats_changed"})
                continue
            if not isinstance(delayed, dict) or row.get("incoming_stats") != {}:
                counts["invalid_delayed_observation"] += 1
                review.append({"match_id": mid, "reason": "invalid_delayed_payload"})
                continue
            values = delayed.get("stats")
            try:
                observation_date = date.fromisoformat(str(delayed.get("source_date") or ""))
                event_date = match.scheduled_at.date()
                age_days = (observation_date - event_date).days
            except ValueError:
                age_days = -1
            valid_provenance = (
                mid.startswith("hist-js:")
                and delayed.get("schema") == 1
                and delayed.get("source") == "tennisvisuals_validated_pointbypoint"
                and delayed.get("status") == "pit_quarantined_unconsumed"
                and delayed.get("score_validated") is True
                and isinstance(delayed.get("source_file"), str)
                and delayed.get("source_file") in {"ATP_Singles_pbpx.csv", "WTA_Singles_pbpx.csv"}
                and isinstance(delayed.get("source_row"), int)
                and delayed["source_row"] > 1
                and isinstance(delayed.get("source_ref"), str)
                and re.fullmatch(r"[0-9a-f]{40}", delayed["source_ref"]) is not None
                and 1 <= age_days <= 21
                and str(match.winner_id or "") in (str(match.player1_id), str(match.player2_id))
            )
            valid_stats = isinstance(values, dict) and set(values) == {
                f"{side}_{field}"
                for side in ("p1", "p2")
                for field in ("service_points_won", "return_points_won", "aces", "double_faults")
            }
            if valid_stats:
                for key, value in values.items():
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                        valid_stats = False
                        break
                    if key.endswith(("aces", "double_faults")):
                        if value < 0 or not float(value).is_integer():
                            valid_stats = False
                    elif not 0 <= value <= 1:
                        valid_stats = False
            if not valid_provenance or not valid_stats:
                counts["invalid_delayed_observation"] += 1
                review.append({"match_id": mid, "reason": "invalid_pit_quarantine_observation"})
                continue
            payload = dict(match.provider_payload or {})
            prior = payload.get("_tbt_pbpx_delayed_observation")
            if prior is not None:
                if prior == delayed:
                    counts["already_present"] += 1
                else:
                    counts["provenance_conflicts"] += 1
                    review.append({"match_id": mid, "reason": "existing_pit_observation_conflict"})
                continue
            payload["_tbt_pbpx_delayed_observation"] = delayed
            match.provider_payload = payload
            counts["updated"] += 1
            counts["pit_observations_added"] += 1
            changed_years.add(match.scheduled_at.year)
            continue

        incoming = row.get("incoming_stats")
        if not isinstance(incoming, dict) or not incoming:
            counts["no_stats"] += 1
            continue
        clean = {}
        invalid = []
        for key, value in incoming.items():
            if key not in ALLOWED or isinstance(value, bool):
                invalid.append(key)
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                invalid.append(key)
                continue
            if not math.isfinite(numeric):
                invalid.append(key)
                continue
            field = key.split("_", 1)[1]
            if field in RATE_FIELDS and not 0 <= numeric <= 1:
                invalid.append(key)
                continue
            if field in COUNT_FIELDS and (numeric < 0 or not numeric.is_integer()):
                invalid.append(key)
                continue
            clean[key] = numeric
        if invalid:
            counts["invalid_stats"] += 1
            review.append({"match_id": mid, "reason": "invalid_stats", "keys": invalid})
            continue

        existing = dict(match.stats or {})
        conflicts = [
            key for key, value in clean.items()
            if existing.get(key) is not None and abs(float(existing[key]) - value) > 1e-6
        ]
        if conflicts:
            counts["stat_conflicts"] += 1
            review.append({"match_id": mid, "reason": "stat_conflicts", "keys": conflicts})
            continue

        new_stats = dict(existing)
        added = {key: value for key, value in clean.items() if new_stats.get(key) is None}
        new_stats.update(added)
        if new_stats == existing:
            counts["already_present"] += 1
            continue

        # Canonical stats provenance is mandatory for TennisVisuals imports.
        # Other legacy offline imports retain their existing provenance contract.
        provenance = row.get("provenance") or []
        pbpx_sources = [
            item for item in provenance
            if isinstance(item, dict)
            and item.get("source") == "tennisvisuals_validated_pointbypoint"
        ]
        if pbpx_sources:
            if len(pbpx_sources) != 1:
                counts["invalid_provenance"] += 1
                review.append({"match_id": mid, "reason": "ambiguous_pbpx_provenance"})
                continue
            proof = pbpx_sources[0]
            evidence = proof.get("evidence") or []
            source_date = str(proof.get("source_date") or "")
            if (
                proof.get("score_validated") is not True
                or not source_date
                or "winner_derived_from_point_tape" not in evidence
                or "full_set_score_matches_point_tape" not in evidence
                or not proof.get("source_file")
                or not isinstance(proof.get("source_row"), int)
                or source_date > match.scheduled_at.date().isoformat()
            ):
                counts["invalid_provenance"] += 1
                review.append({"match_id": mid, "reason": "invalid_pbpx_provenance"})
                continue
            payload = dict(match.provider_payload or {})
            marker = {
                "schema": 1,
                "source": proof["source"],
                "source_file": str(proof["source_file"]),
                "source_row": proof["source_row"],
                "source_ref": str(proof.get("source_ref") or ""),
                "source_date": source_date,
                "score_validated": True,
                "stat_keys": sorted(added),
            }
            previous = payload.get("_tbt_pbpx_enrichment")
            if previous is not None and previous != marker:
                counts["provenance_conflicts"] += 1
                review.append({"match_id": mid, "reason": "pbpx_provenance_conflict"})
                continue
            payload["_tbt_pbpx_enrichment"] = marker
            match.provider_payload = payload

        match.stats = new_stats
        counts["stat_fields_added"] += len(added)
        counts["updated"] += 1
        changed_years.add(match.scheduled_at.year)

    after = sum(1 for m in matches if _quality(m.stats or {}))
    target = Path(args.write_history_dir) if args.write_history_dir else out / "history"
    if args.write_partitions:
        for year in sorted(changed_years):
            write_year_partition(
                matches,
                target,
                year,
                extra_manifest={"coverage_status": "offline_serve_return_import_pending_review"},
            )

    report = {
        "schema": 1,
        "stage_rows": len(rows),
        "counts": dict(counts),
        "changed_years": sorted(changed_years),
        "quality_ready_before": before,
        "quality_ready_after": after,
        "quality_ready_added": after - before,
        "production_mutated": False,
        "local_partitions_written": bool(args.write_partitions and changed_years),
        "api_requests": 0,
        "note": "Importer never uploads a release; publish only after review and full history integrity validation.",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out / "review.jsonl").open("w", encoding="utf-8") as handle:
        for item in review:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
