#!/usr/bin/env python3
"""Private, read-only list of Drive/CDB matches worth provider-native verification.

A name/date match is NOT proof. This queue never grants source usage rights,
imports cells, calls sports APIs, or promotes source IDs to canonical IDs.
Output with canonical match IDs must stay PRIVATE; public reports are counts only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import math
from pathlib import Path

MAX_CANDIDATES = 500
ALLOWED_YEARS = set(range(2023, 2027))


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return value


def _records(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("Non-object stage row")
            records.append(record)
            if len(records) > MAX_CANDIDATES:
                raise ValueError("Unbounded candidate queue")
    return records


def build(link_dir: Path, normalized_report: Path, stage_dir: Path,
          private_dir: Path) -> dict:
    if private_dir.exists() and any(private_dir.iterdir()):
        raise ValueError("Private queue destination must be empty")
    normalized = _json(normalized_report)
    linker = _json(link_dir / "report.json")
    stage = _json(stage_dir / "report.json")
    if (normalized.get("production_mutated") is not False
            or normalized.get("api_requests") != 0
            or linker.get("production_mutated") is not False
            or linker.get("api_requests") != 0
            or linker.get("matching_strategy") != "verified_ids"
            or stage.get("production_mutated") is not False
            or stage.get("api_requests") != 0
            or stage.get("license_review_required") is not True):
        raise ValueError("Input is not a strictly read-only candidate audit")
    source_names = {}
    for entry in normalized.get("normalized", []):
        if not isinstance(entry, dict):
            raise ValueError("Bad normalized source entry")
        name = "sackmann:" + Path(str(entry.get("path") or "")).name
        sha = entry.get("source_sha256")
        if (name in source_names or entry.get("tour") not in ("atp", "wta")
                or not isinstance(sha, str) or len(sha) != 64
                or any(c not in "0123456789abcdef" for c in sha)):
            raise ValueError("Invalid or duplicate source evidence")
        source_names[name] = (entry["tour"], sha)
    if not source_names:
        raise ValueError("Missing input provenance")
    conflicts = {
        str(row.get("match_id") or "")
        for row in _records(link_dir / "quarantine.jsonl")
    }
    eligible = {
        str(row.get("match_id") or "")
        for row in _records(stage_dir / "eligible.jsonl")
    }
    if len(eligible) != stage.get("eligible_matches"):
        raise ValueError("Strict stage eligibility mismatch")
    queue = []
    seen = set()
    reasons = Counter()
    years = Counter()
    for row in _records(link_dir / "auto_linked.jsonl"):
        mid = str(row.get("match_id") or "")
        if not mid or mid in seen:
            raise ValueError("Duplicate/missing canonical candidate ID")
        seen.add(mid)
        if mid in conflicts:
            reasons["canonical_conflict_quarantined"] += 1
            continue
        if mid in eligible:
            reasons["already_strictly_eligible"] += 1
            continue
        canonical = row.get("canonical")
        if not isinstance(canonical, dict) or canonical.get("tour") not in ("atp", "wta"):
            reasons["invalid_canonical_tour"] += 1
            continue
        day = str(canonical.get("scheduled_date_utc") or "")
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            reasons["invalid_date"] += 1
            continue
        if parsed.isoformat() != day or parsed.year not in ALLOWED_YEARS:
            reasons["out_of_scope_year"] += 1
            continue
        stats = row.get("incoming_stats")
        if (not isinstance(stats, dict) or not stats
                or any(not isinstance(key, str) or
                       not key.startswith(("p1_", "p2_"))
                       or isinstance(value, bool) or
                       not isinstance(value, (int, float)) or
                       not math.isfinite(value)
                       for key, value in stats.items())):
            reasons["missing_or_invalid_candidate_stats"] += 1
            continue
        sources = row.get("sources")
        if not isinstance(sources, list) or not sources:
            reasons["missing_source_provenance"] += 1
            continue
        validated = []
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("Malformed source proof")
            name = source.get("source")
            details = source_names.get(name)
            if not details or details[0] != canonical["tour"]:
                raise ValueError("Candidate references unaudited source")
            validated.append({"source_sha256": details[1],
                              "link_evidence": sorted(set(source.get("evidence") or []))})
        queue.append({
            "canonical_match_id": mid,
            "tour": canonical["tour"],
            "utc_day": day,
            "missing_stat_fields_to_check": sorted(stats),
            "source_provenance": validated,
            "next_action": "check_native_api_event_identity_and_fields_under_shared_budget",
            "source_player_ids_verified": False,
            "source_reuse_rights_verified": False,
            "cdb_import_ready": False,
            "provider_api_requests_made": 0,
        })
        years[f"{parsed.year}_{canonical['tour']}"] += 1
        reasons["pending_independent_provider_identity"] += 1
    queue.sort(key=lambda x: (x["utc_day"], x["tour"], x["canonical_match_id"]), reverse=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n"
                      for row in queue).encode("utf-8")
    (private_dir / "api-identity-review.jsonl").write_bytes(payload)
    report = {
        "schema": 1,
        "state": "PRIVATE_SOURCE_ONLY_API_IDENTITY_REVIEW",
        "production_mutated": False,
        "api_requests": 0,
        "write_authorized": False,
        "source_reuse_rights_verified": False,
        "canonical_matches_confirmed": 0,
        "queued_unique_canonical_candidates": len(queue),
        "candidate_stat_fields_to_verify": sum(
            len(row["missing_stat_fields_to_check"]) for row in queue),
        "by_year_tour": dict(sorted(years.items())),
        "reason_counts": dict(sorted(reasons.items())),
        "private_queue_sha256": hashlib.sha256(payload).hexdigest(),
        "note": "No API lookups dispatched; candidate IDs may not be published in public artifacts.",
    }
    (private_dir / "aggregate-only.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--link-dir", type=Path, required=True)
    p.add_argument("--normalized-report", type=Path, required=True)
    p.add_argument("--stage-dir", type=Path, required=True)
    p.add_argument("--private-dir", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(build(args.link_dir, args.normalized_report,
                           args.stage_dir, args.private_dir), sort_keys=True))


if __name__ == "__main__":
    main()
