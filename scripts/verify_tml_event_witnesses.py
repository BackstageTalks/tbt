#!/usr/bin/env python3
"""Fail-closed independent event witness triage; NEVER authorizes a CDB write.

Two SHA-pinned private JSONL inputs:
- current CDB context-only TML event review
- independent official event witness ledger, NOT generated from the TML CSV
Output is only PRIVATE read-only evidence and counts, with canonical checks
deferred until an immutable current CDB snapshot is verified.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

SHA = re.compile(r"^[a-f0-9]{64}$")
MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 100000


def verify(path: Path, expected: str) -> None:
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise ValueError("Missing full source digest")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Invalid evidence file")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Evidence digest mismatch")


def read(path: Path):
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if n > MAX_ROWS:
                raise ValueError("Evidence row limit reached")
            if line.strip():
                item = json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
                if not isinstance(item, dict):
                    raise ValueError("Invalid evidence row")
                yield item


def triage(context: Path, context_sha: str, witnesses: Path, witnesses_sha: str,
           out: Path):
    verify(context, context_sha)
    verify(witnesses, witnesses_sha)
    canonical_owners = defaultdict(list)
    source_owners = defaultdict(list)
    provider_owners = defaultdict(set)
    for row in read(witnesses):
        if (row.get("schema") != 1 or row.get("kind") != "independent_original_event_witness"
                or row.get("from_tml_source") is not False
                or not isinstance(row.get("provider_event_id"), str)
                or not row["provider_event_id"]
                or row.get("provider_namespace") in (None, "", "tml")
                or row.get("source_namespace") in (None, "")
                or not isinstance(row.get("source_native_event_key"), list)
                or not row["source_native_event_key"]
                or not isinstance(row.get("canonical_match_id"), str)
                or not row["canonical_match_id"]
                or not SHA.fullmatch(str(row.get("independent_original_sha256")))
                or row.get("write_authorized") is not False):
            raise ValueError("Unsupported or preauthorized event witness")
        key = (row["source_namespace"], tuple(row["source_native_event_key"]))
        canonical_owners[row["canonical_match_id"]].append(row)
        provider_owners[(row["provider_namespace"], row["provider_event_id"])].add(row["canonical_match_id"])
        source_owners[key].append(row)
    counts = Counter()
    accepted = []
    seen_context = set()
    for row in read(context):
        if (row.get("import_ready") is not False
                or row.get("write_authorized") is not False
                or row.get("independent_event_id_attested") is not False):
            raise ValueError("Unsafe preapproved context")
        key = (row.get("source_namespace"), tuple(row.get("source_native_event_key") or ()))
        canonical = row.get("candidate_canonical_match_id")
        if not key[0] or not key[1] or not canonical:
            raise ValueError("Incomplete review context")
        if key in seen_context:
            raise ValueError("Duplicate source context")
        seen_context.add(key)
        matched = source_owners.get(key, [])
        if not matched:
            counts["without_independent_event_witness"] += 1
            continue
        if len(matched) != 1 or len(canonical_owners[canonical]) != 1:
            counts["ambiguous_event_witness"] += 1
            continue
        witness = matched[0]
        if len(provider_owners[(witness["provider_namespace"], witness["provider_event_id"])]) != 1:
            counts["ambiguous_provider_event_reuse"] += 1
            continue
        if witness["canonical_match_id"] != canonical:
            counts["canonical_target_conflict"] += 1
            continue
        if row.get("score_attested") is not True:
            counts["no_independent_full_score_corroboration"] += 1
            continue
        # Still only a REVIEW record. Official event identity equivalence must
        # be freshly verified against the canonical provider namespace, sides,
        # current snapshot SHA and current NULL before any writer can run.
        accepted.append({
            "source_namespace": key[0],
            "source_native_event_key": list(key[1]),
            "candidate_canonical_match_id": canonical,
            "witness_provider_namespace": witness["provider_namespace"],
            "witness_provider_event_id": witness["provider_event_id"],
            "original_witness_sha256": witness["independent_original_sha256"],
            "status": "OFFLINE_EVENT_WITNESS_REVIEW_ONLY",
            "current_cdb_snapshot_verified": False,
            "independent_provider_event_id_attested": False,
            "import_ready": False,
            "write_authorized": False,
        })
        counts["source_event_with_independent_witness_for_review"] += 1
    out.mkdir(parents=True, exist_ok=True)
    target = out / "independent-event-witness-review-private.jsonl"
    with target.open("w", encoding="utf-8") as file:
        for row in accepted:
            file.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    report = {
        "status": "READ_ONLY_EVENT_WITNESS_TRIAGE",
        "source_context_sha256": context_sha,
        "source_witness_sha256": witnesses_sha,
        "counts": dict(sorted(counts.items())),
        "ready_for_cdb_write": 0,
        "cdb_mutated": False,
        "provider_api_requests": 0,
        "model_trained": False,
        "private_review_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--context", type=Path, required=True)
    p.add_argument("--context-sha256", required=True)
    p.add_argument("--witnesses", type=Path, required=True)
    p.add_argument("--witnesses-sha256", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    result = triage(a.context, a.context_sha256, a.witnesses, a.witnesses_sha256, a.out)
    print(json.dumps({"status": result["status"], "counts": result["counts"],
                      "ready_for_cdb_write": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
