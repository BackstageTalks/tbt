#!/usr/bin/env python3
"""Recheck an EXISTING paid first-party event-ID sample against immutable CDB.

Strictly read-only and offline. Does not call the provider, spend RapidAPI
quota, grant cross-provider IDs, license any statistics, or authorize a writer.

Original evidence provenance:
  GitHub Actions 38458939812, private release
  blinq-licensed-api50-native-id-review-38458939812-1.
  This file replays the *previously stored provider result classifications*
  and rechecks both native player IDs against the pinned canonical Parquet;
  it does NOT independently fetch the original API responses again.

Attribution/third-party crosswalk from e.g. Sackmann, TML, TennisData or
Sofascore remains completely unproven by same-provider native ID equality.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

from scripts.research.audit_api50_match_ids import canonical_candidate

CDB_SHA = "3a929b356803af6b0f704d4d3066a053ecf995124ec8f4228487c54c0f534c58"
DETAIL_SHA = "f8cf817321ea9a411df7bc21acd5f15a897e6ad100ef195c90f285d0de60df70"
REPORT_SCHEMA = "BLINQ_API50_RECODEX_VS_CANONICAL_ID_RECHECK_V1"
EXACT = "SAME_PROVIDER_EVENT_PARTICIPANTS_TIME_WINNER_RECHECK_ONLY"
MAX_BYTES = 1_048_576
SHA = re.compile(r"^[a-f0-9]{64}$")


def sha256_file(path: Path) -> str:
    hash_ = sha256()
    with path.open("rb") as file:
        for part in iter(lambda: file.read(1024 * 1024), b""):
            hash_.update(part)
    return hash_.hexdigest()


def check_file(path: Path, expected: str, max_bytes: int | None = None) -> None:
    if not SHA.fullmatch(expected) or path.is_symlink() or not path.is_file():
        raise ValueError("Invalid pinned file or SHA-256")
    if not path.stat().st_size or (max_bytes and path.stat().st_size > max_bytes):
        raise ValueError("Empty or oversized original evidence file")
    if sha256_file(path) != expected:
        raise ValueError("Immutable source SHA-256 mismatch")


def strict_json(data: str) -> dict:
    value = json.loads(
        data, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token))
    )
    if not isinstance(value, dict):
        raise ValueError("Evidence JSON requires object")
    return value


def load_evidence(detail: Path, report: Path) -> list[dict]:
    check_file(detail, DETAIL_SHA, MAX_BYTES)
    if report.is_symlink() or not report.is_file() or report.stat().st_size > MAX_BYTES:
        raise ValueError("Invalid original provider report")
    summary = strict_json(report.read_text("utf-8"))
    if (summary.get("schema") != REPORT_SCHEMA
            or summary.get("cdb_partition_sha256") != CDB_SHA
            or summary.get("detail_sha256") != DETAIL_SHA
            or summary.get("selected_events") != 50
            or summary.get("requests_attempted") != 50
            or summary.get("CDB_writes") != 0
            or summary.get("model_modified") is not False
            or summary.get("verified_third_party_source_to_cdb_crosswalk") != 0):
        raise ValueError("Provider original report contract is inconsistent")
    data = [
        strict_json(line) for line in detail.read_text("utf-8").splitlines()
        if line.strip()
    ]
    if len(data) != 50:
        raise ValueError("Original first-party record count changed")
    if summary.get("counts", {}).get(EXACT) != 50:
        raise ValueError("The original provider challenge did not confirm 50")
    return data


def canonical_by_id(rows, wanted: set[tuple[str, str]] | None = None
                    ) -> dict[tuple[str, str], dict]:
    """Only index the pinned 50 sample; fail closed on duplicates within it."""
    result = {}
    native_seen = set()
    for row in rows:
        if wanted is not None and (
                str(row.get("tour") or "").lower(), str(row.get("match_id") or "")
                ) not in wanted:
            continue
        event = canonical_candidate(row)
        if event is None:
            continue
        key = (event["tour"], event["canonical_match_id"])
        native = (event["tour"], event["event_id"])
        if key in result or native in native_seen:
            raise ValueError("Canonical native provider ID collision")
        result[key] = event
        native_seen.add(native)
    return result


def verify_details(details: list[dict], canonical: dict) -> dict:
    if len(details) != 50:
        raise ValueError("Exactly 50 independently stored result records needed")
    seen_events, seen_matches = set(), set()
    counts = Counter()
    for row in details:
        if (row.get("result") != EXACT
                or row.get("writes_authorized") is not False
                or row.get("independently_verified_sofascore_ID") is not False):
            raise ValueError("An unverified or preauthorized source result appeared")
        tour = row.get("tour")
        event_id = str(row.get("provider_event_id") or "")
        canonical_id = str(row.get("canonical_match_id") or "")
        if tour not in ("atp", "wta") or not event_id or not canonical_id:
            raise ValueError("Original ID/tour missing")
        native = (tour, event_id)
        target = (tour, canonical_id)
        if native in seen_events or target in seen_matches:
            raise ValueError("Duplicate source/provider event mapping")
        seen_events.add(native)
        seen_matches.add(target)
        source = canonical.get(target)
        if source is None:
            raise ValueError("Original reference absent from pinned 2025 CDB")
        if (source["event_id"] != event_id
                or source["home_id"] != row.get("source_native_home_id")
                or source["away_id"] != row.get("source_native_away_id")
                or source["home_id"] == source["away_id"]
                or source["winner_id"] not in
                    (source["home_id"], source["away_id"])):
            raise ValueError("Actual first-party ID/participant/winner conflict")
        counts[tour] += 1
    if counts != {"atp": 25, "wta": 25}:
        raise ValueError("Changed ATP/WTA allocation in independent prior sample")
    return {
        "schema": "BLINQ_IDENTITY_V2_REAL_FIRST_PARTY_50_REPLAY_V1",
        "frozen_cdb_2025_sha256": CDB_SHA,
        "independent_prior_run": 38458939812,
        "sample_source_detail_sha256": DETAIL_SHA,
        "same_provider_native_match_rechecks": 50,
        "atp_count": counts["atp"],
        "wta_count": counts["wta"],
        "exact_event_id_and_both_player_IDs": 50,
        "stored_original_provider_winner_verdicts": 50,
        "provider_winner_responses_freshly_rechecked": 0,
        "provider_start_times_freshly_rechecked": 0,
        "external_provider_crosswalks_proven": 0,
        "independent_sackmann_to_cdb_events_proven": 0,
        "third_party_stats_authorized_for_CDB": 0,
        "identity_v2_CDB_writes": 0,
        "rapidapi_requests": 0,
        "note": "Replay of prior provider response verdicts against frozen CDB, not a fresh provider API challenge.",
    }


def run(cdb: Path, detail: Path, report: Path) -> dict:
    check_file(cdb, CDB_SHA)
    details = load_evidence(detail, report)
    import pyarrow.parquet as pq
    fields = [
        "match_id", "tour", "scheduled_at", "status", "winner_id",
        "player1_id", "player2_id", "provider_context_json",
    ]
    reader = pq.ParquetFile(cdb)
    if not set(fields).issubset(reader.schema.names):
        raise ValueError("Canonical snapshot missing provider ID fields")
    def canonical_rows():
        for batch in reader.iter_batches(batch_size=2048, columns=fields):
            yield from batch.to_pylist()
    wanted = {(row["tour"], str(row["canonical_match_id"])) for row in details}
    return verify_details(details, canonical_by_id(canonical_rows(), wanted))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdb", type=Path, required=True)
    parser.add_argument("--detail", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.cdb, args.detail, args.report)
    print("BLINQ_IDENTITY_V2_REAL_PROVIDER50 " +
          json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
