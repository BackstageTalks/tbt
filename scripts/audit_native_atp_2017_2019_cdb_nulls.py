#!/usr/bin/env python3
"""Read-only exact-native 2017-19 ATP CDB NULL gap evidence.

Identity report and canonical partitions are independently SHA-attested by the
trusted public runner. This census cannot create an import stage or approve
historical source rights, point-in-time training, or production writes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from audit_drive_atp_2017_2019_current_cdb import (
    REQUIRED_CDB, attest, historical_event_id,
)

YEARS = ("2017", "2018", "2019")
RATE_FIELDS = ("p1_break_point_return_win", "p2_break_point_return_win")
COUNT_FIELDS = (
    "p1_return_break_points_converted_count",
    "p2_return_break_points_converted_count",
)
FIELDS = RATE_FIELDS + COUNT_FIELDS


def json_object(payload, label: str) -> dict:
    try:
        parsed = payload if isinstance(payload, dict) else json.loads(payload)
    except (ValueError, TypeError) as error:
        raise ValueError("Unreadable " + label) from error
    if not isinstance(parsed, dict):
        raise ValueError("Non-object " + label)
    return parsed


def native_bp_side(source: dict, position: int) -> str:
    prefix = "l" if position == 1 else "w"
    try:
        faced = int(source[prefix + "_bpFaced"])
        saved = int(source[prefix + "_bpSaved"])
    except (KeyError, ValueError, TypeError):
        return "missing_or_invalid_raw_counts"
    if faced < 0 or saved < 0 or saved > faced:
        return "invalid_raw_count_constraints"
    return "valid_positive_denominator" if faced else "zero_denominator"


def source_stat_lineage(context: dict, match_id: str, year: str) -> bool:
    raw = context.get("_tbt_statistics")
    return (
        isinstance(raw, dict)
        and raw.get("source") ==
            "jeff_sackmann_match_snapshot:atp_matches_" + year + ".csv"
        and raw.get("event_id") == match_id
    )


def classify(source: dict, canonical: dict, year: str) -> tuple[dict, dict]:
    match_id = canonical["match_id"]
    context = json_object(canonical["provider_context_json"], "provider context")
    stats = json_object(canonical["stats_json"], "canonical stats")
    lineage = source_stat_lineage(context, match_id, year)
    bp = {p: native_bp_side(source, p) for p in (1, 2)}
    states = {}
    for name in FIELDS:
        value = stats.get(name)
        if value is not None:
            states[name] = "present"
        else:
            position = 1 if name.startswith("p1_") else 2
            if not lineage:
                states[name] = "missing_no_original_stat_lineage"
            elif bp[position] != "valid_positive_denominator":
                states[name] = "missing_raw_bp_" + bp[position]
            else:
                states[name] = "research_gap_requires_full_candidate_and_rights_review"
    return {
        "source_stat_lineage": lineage,
        "raw_bp_side_states": {"p1": bp[1], "p2": bp[2]},
        "field_states": states,
        "write_authorized": False,
    }, stats



def strict_count_candidate_review(source: dict, stats: dict) -> str:
    """Stricter source/CDB consistency check. Research-only; never a write gate.

    Requires a completed source score, all original winner/loser match counters,
    source-internal arithmetic, and agreement with *every* pre-existing
    overlapping canonical statistic. Source-derived values are never emitted.
    """
    import math
    import re

    try:
        best_of = int(source.get("best_of") or "")
        score = str(source.get("score") or "").strip()
        if best_of not in (3, 5):
            return "invalid_original_best_of"
        if not score or re.search(
            r"\b(RET|W/O|WO|DEF|ABD|SUSP|WALKOVER)\b", score, re.I
        ):
            return "missing_or_retired_original_score"
        sets = []
        for token in score.split():
            match = re.fullmatch(r"(\d{1,2})-(\d{1,2})(?:\(\d{1,2}\))?", token)
            if not match:
                return "unsupported_original_score_token"
            a, b = int(match[1]), int(match[2])
            hi, lo = max(a, b), min(a, b)
            if not ((hi == 6 and lo <= 4) or (hi == 7 and lo in (5, 6))
                    or (7 < hi <= 13 and hi - lo == 2)):
                return "invalid_original_set_score"
            sets.append((a, b))
        if (len(sets) > best_of or sum(a > b for a, b in sets) != (best_of + 1) // 2
                or not sets or sets[-1][0] <= sets[-1][1]):
            return "incomplete_or_invalid_original_match_score"
        fields = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon",
                  "SvGms", "bpSaved", "bpFaced")
        raw = {}
        for side in ("w", "l"):
            values = {}
            for field in fields:
                value = str(source.get(side + "_" + field) or "").strip()
                if not value.isdecimal():
                    return "missing_or_noninteger_original_" + side + "_" + field
                values[field] = int(value)
            if not (values["svpt"] > 0 and values["SvGms"] > 0
                    and values["1stIn"] <= values["svpt"]
                    and values["1stWon"] <= values["1stIn"]
                    and values["2ndWon"] <= values["svpt"] - values["1stIn"]
                    and values["ace"] <= values["1stWon"] + values["2ndWon"]
                    and values["df"] <= values["svpt"] - values["1stIn"]
                    and values["bpSaved"] <= values["bpFaced"] <= values["svpt"]
                    and values["svpt"] >= 4 * values["SvGms"]):
                return "invalid_original_match_counts"
            raw[side] = values
    except (ValueError, TypeError, KeyError, OverflowError):
        return "unreadable_original_match"

    expected = {}
    for p, side, opponent in (("p1", "w", "l"), ("p2", "l", "w")):
        v, o = raw[side], raw[opponent]
        expected[p + "_aces"] = v["ace"]
        expected[p + "_double_faults"] = v["df"]
        if v["1stIn"]:
            expected[p + "_first_serve_win"] = v["1stWon"] / v["1stIn"]
        second_attempts = v["svpt"] - v["1stIn"]
        if second_attempts:
            expected[p + "_second_serve_win"] = v["2ndWon"] / second_attempts
        expected[p + "_service_points_won"] = (
            v["1stWon"] + v["2ndWon"]
        ) / v["svpt"]
        expected[p + "_return_points_won"] = 1 - (
            o["1stWon"] + o["2ndWon"]
        ) / o["svpt"]
        if v["bpFaced"]:
            expected[p + "_break_point_serve_win"] = (
                v["bpSaved"] / v["bpFaced"]
            )
        expected[p + "_return_break_points_converted_count"] = (
            o["bpFaced"] - o["bpSaved"]
        )
        if o["bpFaced"]:
            expected[p + "_break_point_return_win"] = (
                o["bpFaced"] - o["bpSaved"]
            ) / o["bpFaced"]

    for field, candidate in expected.items():
        observed = stats.get(field)
        if observed is not None and (
            isinstance(observed, bool)
            or not isinstance(observed, (int, float))
            or not math.isfinite(observed)
            or abs(float(observed) - candidate) > 1e-6
        ):
            return "existing_cdb_stat_conflict"
    return "technically_consistent_rights_not_cleared"


def read_source(directory: Path) -> dict:
    original = {}
    for year in YEARS:
        path = directory / ("atp_matches_" + year + ".csv")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        by_key = {}
        for row in rows:
            key = str(row.get("tourney_id") or "") + ":" + str(row.get("match_num") or "")
            if not row.get("tourney_id") or not row.get("match_num") or key in by_key:
                raise ValueError("Original source key missing or duplicate")
            by_key[key] = {**row, "year": year}
        original[year] = by_key
    return original


def scan(report_file: Path, originals: Path, canonical_dir: Path) -> dict:
    import pyarrow.parquet as pq

    identity = json_object(report_file.read_text(), "verified identity report")
    links = identity.get("verified_secondary_ids")
    if (identity.get("source_rows") != 8556
            or identity.get("production_cdb_writes") != 0
            or identity.get("bulk_import_authorized") is not False
            or not isinstance(links, list)
            or identity.get("verified_ids") != len(links)
            or not links):
        raise ValueError("Identity cohort receipt is not verified or stable")
    sources = read_source(originals)
    by_year = {}
    for year in YEARS:
        file = canonical_dir / ("history-" + year + ".parquet")
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        if identity["cdb_year_pins"][year]["sha256"] != digest:
            raise ValueError("CDB year changed since native identity proof")
        f = pq.ParquetFile(file)
        fields = set(REQUIRED_CDB) | {"stats_json"}
        if not fields.issubset(f.schema_arrow.names):
            raise ValueError("Required full canonical stats/identity columns missing")
        index = {}
        for row in f.read(columns=sorted(fields)).to_pylist():
            mid = str(row.get("match_id") or "")
            if not mid or mid in index:
                raise ValueError("Duplicate or absent canonical event")
            index[mid] = row
        by_year[year] = index
    seen_source = set()
    seen_match = set()
    totals = Counter()
    year_counts = defaultdict(Counter)
    fields = {field: Counter() for field in FIELDS}
    strict_count_review = {field: Counter() for field in COUNT_FIELDS}
    observations = []
    for link in links:
        if (not isinstance(link, dict)
                or set(link) != {
                    "tour", "source_namespace", "source_event_id", "canonical_match_id"
                } or link["tour"] != "atp"
                or link["source_namespace"] != "drive-atp-main-sackmann"):
            raise ValueError("Unsupported native-ID mapping row")
        event = link["source_event_id"]
        mid = link["canonical_match_id"]
        year = event[:4]
        if year not in YEARS:
            raise ValueError("Unexpected native year")
        if event in seen_source or mid in seen_match:
            raise ValueError("Native source/canonical owner collision")
        seen_source.add(event)
        seen_match.add(mid)
        row = sources[year].get(event)
        canonical = by_year[year].get(mid)
        if row is None or canonical is None:
            raise ValueError("Linked source or current canonical event missing")
        if historical_event_id(row) != mid:
            raise ValueError("Original source-native event fingerprint changed")
        if attest(row, canonical) != "VERIFIED_NATIVE_EVENT_AND_BOTH_PLAYERS":
            raise ValueError("Current canonical native and both-player proof no longer holds")
        classified, _ = classify(row, canonical, year)
        totals["identity_rechecked"] += 1
        year_counts[year]["identities"] += 1
        if classified["source_stat_lineage"]:
            totals["original_match_stat_lineage"] += 1
            year_counts[year]["original_match_stat_lineage"] += 1
        else:
            totals["identity_proven_but_match_stats_lineage_missing"] += 1
        for name, status in classified["field_states"].items():
            fields[name][status] += 1
            year_counts[year][name + "_" + status] += 1
        review_fields = {}
        if any(classified["field_states"][field] ==
               "research_gap_requires_full_candidate_and_rights_review"
               for field in COUNT_FIELDS):
            decision = strict_count_candidate_review(row, json_object(
                canonical["stats_json"], "canonical stats"))
            for field in COUNT_FIELDS:
                if (classified["field_states"][field] ==
                        "research_gap_requires_full_candidate_and_rights_review"):
                    strict_count_review[field][decision] += 1
                    review_fields[field] = decision
        observations.append({
            "strict_count_candidate_review": review_fields,
            "year": year,
            "source_event_id": event,
            "canonical_match_id": mid,
            **classified,
        })
    if totals["identity_rechecked"] != identity["verified_ids"]:
        raise ValueError("Exact native identity cohort not fully processed")
    return {
        "schema": "BLINQ_ATP_2017_2019_NATIVE_CDB_NULL_GAP_READONLY_V1",
        "source_identity_report_sha256": hashlib.sha256(report_file.read_bytes()).hexdigest(),
        "verified_link_count": totals["identity_rechecked"],
        "counts": dict(sorted(totals.items())),
        "years": {k: dict(sorted(v.items())) for k, v in sorted(year_counts.items())},
        "field_status": {k: dict(sorted(v.items())) for k, v in fields.items()},
        "strict_count_review": {k: dict(sorted(v.items())) for k, v in strict_count_review.items()},
        "strict_technical_review_executed": True,
        "per_event": observations,
        "rights_cleared_for_import": False,
        "exact_full_candidate_policy_executed": False,
        "import_authorized": False,
        "canonical_writes": 0,
        "production_model_changes": 0,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--identity-report", type=Path, required=True)
    p.add_argument("--source-dir", type=Path, required=True)
    p.add_argument("--cdb-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    report = scan(args.identity_report, args.source_dir, args.cdb_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("ATP_2017_2019_NATIVE_NULL_GAP_READONLY", json.dumps({
        "verified_link_count": report["verified_link_count"],
        "original_match_stat_lineage": report["counts"].get("original_match_stat_lineage", 0),
        "per_field_nulls": {
            name: report["verified_link_count"] - states.get("present", 0)
            for name, states in report["field_status"].items()
        },
        "strict_count_review": report["strict_count_review"],
        "per_field_research_only_gaps": {
            name: states.get("research_gap_requires_full_candidate_and_rights_review", 0)
            for name, states in report["field_status"].items()
        },
        "canonical_writes": 0,
        "import_authorized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
