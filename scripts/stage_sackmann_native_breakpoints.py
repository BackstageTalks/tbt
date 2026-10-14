"""Revalidate same-origin Sackmann historical break-point rates; PRIVATE STAGE ONLY.

This is not cross-provider identity attestation. Never accept research match proposals
as writer input or mutate CDB. Only records whose CDB ID, original source marker,
both native player IDs, names, winner and date reconstruct exactly are eligible for
a separate, reviewed protected rehydration step. source: CC BY-NC-SA 4.0;
retain attribution and original-pinned SHA in the private evidence.
"""
from __future__ import annotations
import argparse
import collections
import csv
import gzip
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

from audit_pbp_source_vs_current_cdb import valid, native_key, breakpoint_return_value, norm
from audit_source_value_routes import historical_id

FIELDS = frozenset(("p1_break_point_return_win", "p2_break_point_return_win"))
LINEAGE = "HISTORICAL_SOURCE_PROVENANCE_NATIVE_PLAYERS"
SOURCE_SHA = "83733587353df8a41f2fd4f516147d5aa83f5a8d"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def js(v):
    return json.loads(v) if isinstance(v, str) else (v if isinstance(v, dict) else {})


def rate(saved, faced):
    if type(saved) is not int or type(faced) is not int or faced <= 0 or not 0 <= saved <= faced:
        return None
    return (faced - saved) / faced


def check_exact(candidate, source_row, match):
    """Full canonical same-origin certificate; never trust a prior lineage label."""
    mid = str(match["match_id"])
    tour = candidate["tour"]
    rel = candidate["source_file"]
    player1 = str(match["player1_id"])
    player2 = str(match["player2_id"])
    if str(match["status"]).lower() not in ("completed", "finished", "ended"):
        return {}, "match_not_completed"
    if tour not in ("atp", "wta") or norm(match["tour"]) != tour:
        return {}, "tour_mismatch"
    if native_key(tour, source_row) != tuple(candidate["source_native_key"]):
        return {}, "native_key_mismatch"
    historical, category = historical_id(tour, rel, source_row)
    if mid != historical:
        return {}, "historical_id_mismatch"
    ctx = js(match["provider_context_json"])
    marker = (ctx.get("_tbt_statistics") or {}).get("source")
    if (ctx.get("_tbt_provider_event_id") != mid
            or marker != "jeff_sackmann_match_snapshot:" + Path(rel).name
            or ctx.get("_tbt_source_category_name") != "historical_" + category):
        return {}, "provenance_mismatch"
    if not (player1 == "hist-js:" + tour + ":" + source_row["winner_id"]
            and player2 == "hist-js:" + tour + ":" + source_row["loser_id"]
            and str(match["winner_id"]) == player1
            and norm(match["player1_name"]) == norm(source_row["winner_name"])
            and norm(match["player2_name"]) == norm(source_row["loser_name"])):
        return {}, "player_identity_or_winner_mismatch"
    if match["scheduled_at"].strftime("%Y%m%d") != source_row["tourney_date"]:
        return {}, "date_mismatch"
    source_stats = valid(source_row)
    if source_stats is None:
        return {}, "incomplete_or_invalid_full_match"
    stats = js(match["stats_json"])
    if type(stats) is not dict:
        return {}, "invalid_canonical_stats"
    try:
        proposed = {
            "p1_break_point_return_win": rate(source_stats["l_bpSaved"], source_stats["l_bpFaced"]),
            "p2_break_point_return_win": rate(source_stats["w_bpSaved"], source_stats["w_bpFaced"]),
        }
    except (ValueError, KeyError):
        return {}, "invalid_source_breakpoints"
    offered = candidate["missing_candidate_cells"]
    if not offered or any(k not in FIELDS for k in offered):
        return {}, "unexpected_external_field"
    additions = {}
    for field, value in offered.items():
        derived = proposed[field]
        if derived is None or type(value) not in (int, float) or abs(derived - value) > 1e-12:
            return {}, "candidate_source_value_mismatch"
        if stats.get(field) is not None:
            return {}, "no_longer_null"
        additions[field] = derived
    # Do not force zero-faced break points into a 0% conversion rate.
    for field, value in proposed.items():
        old = stats.get(field)
        if old is not None and (type(old) not in (int, float) or value is None or abs(old - value) > 1e-6):
            return {}, "existing_breakpoint_conflict"
    return additions, ""


def stage(cdb, source, evidence, output):
    output.mkdir(parents=True, exist_ok=True)
    audit = json.loads((evidence / "pbp-current-cdb-gap.json").read_text())
    routes = json.loads((evidence / "value-routes-report.json").read_text())
    manifest_path = cdb / "history_manifest.json"
    if digest(manifest_path) != audit["canonical_manifest_sha256"]:
        raise ValueError("Current CDB differs from verified private source audit")
    if routes["canonical_manifest_sha256"] != audit["canonical_manifest_sha256"]:
        raise ValueError("Mismatched private audit manifests")
    if audit["source_mirror_sha"] != SOURCE_SHA:
        raise ValueError("Unpinned Sackmann archive")
    if routes["production_writes"] != 0 or audit["approved_cdb_cells"] != 0:
        raise ValueError("Research report unexpectedly includes writer authorization")
    if digest(evidence / "pbp-candidates-private.jsonl.gz") != audit["candidate_ledger_sha256"]:
        raise ValueError("Candidate ledger SHA mismatch")
    for name, expected in routes["outputs"].items():
        if digest(evidence / name) != expected:
            raise ValueError("Route ledger SHA mismatch: " + name)
    paths = collections.defaultdict(dict)
    native = {}
    count = collections.Counter()
    with gzip.open(evidence / "source-value-routes.jsonl.gz", "rt") as f:
        for line in f:
            item = json.loads(line)
            if item["lineage"] != LINEAGE:
                continue
            mid = item["canonical_match_id_candidate"]
            if mid in native:
                raise ValueError("Duplicate canonical native lineage")
            native[mid] = item
            count["original_native_external_cells"] += len(item["external_value_fields"])
    wanted = {}
    with gzip.open(evidence / "pbp-candidates-private.jsonl.gz", "rt") as f:
        for line in f:
            candidate = json.loads(line)
            mid = candidate["canonical_match_id_candidate"]
            if mid not in native:
                continue
            if (candidate["independent_identity_verified"] is not False
                    or candidate["write_authorized"] is not False
                    or candidate["source_namespace"] != "sackmann"
                    or candidate["source_native_key"] != native[mid]["source_native_key"]
                    or sorted(candidate["missing_candidate_cells"]) != sorted(native[mid]["external_value_fields"])):
                raise ValueError("Research candidate/native route disagreement")
            if mid in wanted:
                raise ValueError("Duplicate same-origin candidate")
            wanted[mid] = candidate
            idx = candidate["source_record_number"]
            if type(idx) is not int or idx < 1:
                raise ValueError("Invalid CSV source record number")
            path = candidate["source_file"]
            if idx in paths[path]:
                raise ValueError("Duplicate source row use")
            paths[path][idx] = mid
    if set(wanted) != set(native):
        raise ValueError("Native source candidates missing from research ledger")
    original = {}
    for relative, indices in sorted(paths.items()):
        file = source / relative
        if (not file.is_file() or digest(file) != audit["source_file_sha256"][relative]
                or digest(file) != wanted[next(iter(indices.values()))]["source_sha256"]):
            raise ValueError("Source CSV SHA mismatch: " + relative)
        with file.open(encoding="utf-8-sig", newline="") as f:
            for i, row in enumerate(csv.DictReader(f), 1):
                if i in indices:
                    original[indices[i]] = row
    if set(original) != set(wanted):
        raise ValueError("Source CSV records missing")
    counts_by_year = {}
    staged = []
    found = set()
    manifest = json.loads(manifest_path.read_text())
    for year, meta in sorted(manifest["years"].items()):
        file = cdb / ("history-" + year + ".parquet")
        if digest(file) != meta["sha256"]:
            raise ValueError("Canonical partition SHA changed: " + year)
        pf = pq.ParquetFile(file)
        for batch in pf.iter_batches(
            columns=("match_id", "tour", "scheduled_at", "status", "player1_id",
                     "player2_id", "player1_name", "player2_name", "winner_id",
                     "provider_context_json", "stats_json"), batch_size=8192
        ):
            for match in batch.to_pylist():
                mid = str(match["match_id"])
                if mid not in wanted:
                    continue
                if mid in found:
                    raise ValueError("Canonical match duplicated")
                found.add(mid)
                candidate = wanted[mid]
                additions, reason = check_exact(candidate, original[mid], match)
                if reason:
                    count["rejected_" + reason] += len(candidate["missing_candidate_cells"])
                    continue
                if not additions:
                    count["rejected_no_additions"] += 1
                    continue
                row = {
                    "schema": 1,
                    "match_id": mid,
                    "utc_year": int(year),
                    "source_file": candidate["source_file"],
                    "source_row": candidate["source_record_number"],
                    "source_sha256": candidate["source_sha256"],
                    "native_key": candidate["source_native_key"],
                    "stats_sha256": hashlib.sha256(
                        json.dumps(js(match["stats_json"]), sort_keys=True).encode()
                    ).hexdigest(),
                    "canonical_manifest_sha256": audit["canonical_manifest_sha256"],
                    "additions": additions,
                    "evidence_class": "exact_same_origin_original_native_identity",
                    "independent_provider_identity": False,
                    "source_license": "CC BY-NC-SA 4.0",
                    "attribution": "Jeff Sackmann tennis_atp / tennis_wta historical match snapshots",
                    "source_commit": SOURCE_SHA,
                    "write_authorized": False,
                }
                staged.append(row)
                count["eligible_same_origin_matches"] += 1
                count["eligible_same_origin_cells"] += len(additions)
                counts_by_year[year] = counts_by_year.get(year, 0) + len(additions)
    if found != set(wanted):
        raise ValueError("Canonical matches absent from current CDB snapshot")
    if count["eligible_same_origin_cells"] == 0:
        raise ValueError("No useful verified source-native break point rates")
    staged.sort(key=lambda r: r["match_id"])
    ledger = output / "native-breakpoint-stage-private.jsonl.gz"
    with gzip.open(ledger, "wt", encoding="utf-8") as stream:
        for row in staged:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    result = {
        "status": "RESEARCH_STAGED_EXACT_SAME_ORIGIN_NOT_PUBLISHED",
        "source_audit_manifest_sha256": audit["canonical_manifest_sha256"],
        "canonical_matches": audit["counts"]["cdb_rows"],
        "counts": dict(sorted(count.items())),
        "year_cell_counts": dict(sorted(counts_by_year.items())),
        "stage_sha256": digest(ledger),
        "production_writes": 0,
        "model_changes": 0,
        "source_rights_review": "operator stated non-commercial free project; retain attribution/share-alike",
        "independent_provider_identity_attested": False,
        "required_next_gate": "new protected writer with explicit exact-same-origin policy, immutable prewrite backup, manifest CAS and full remote readback",
    }
    (output / "stage-report.json").write_text(json.dumps(result, indent=2) + "\n")
    print("SACKMANN_NATIVE_BREAKPOINT_STAGE_ONLY", json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdb", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    stage(args.cdb, args.source, args.evidence, args.out)
