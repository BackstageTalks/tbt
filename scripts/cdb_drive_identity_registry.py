#!/usr/bin/env python3
"""Private SHA-bound Drive-native ID evidence: NEVER a verified crosswalk."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA = "BLINQ_PRIVATE_CDB_DRIVE_SOURCE_ID_REVIEW_V1"
BAD_ID = {"", "nan", "none", "null", "unknown", "n/a", "-"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_id(v: object) -> str:
    token = str(v or "").strip()
    return token if token.lower() not in BAD_ID and len(token) <= 128 else ""


def require_report(path: Path, *, schema: int, state: str) -> dict:
    item = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(item, dict) or item.get("schema") != schema
            or item.get("state") != state or item.get("production_mutated") is not False
            or item.get("api_requests") != 0):
        raise ValueError("Unsafe source/stage report for review registry")
    return item


def build(normalized_report: Path, stage_dir: Path, drive_manifest: Path, out: Path) -> dict:
    nr = require_report(normalized_report, schema=1, state="SOURCE_ONLY")
    sr = require_report(stage_dir / "report.json", schema=1, state="READ_ONLY_STAGE")
    dm = json.loads(drive_manifest.read_text(encoding="utf-8"))
    if (dm.get("schema") != 2 or dm.get("state") != "DRIVE_SOURCE_FETCH_ONLY"
            or dm.get("production_mutated") is not False or not isinstance(dm.get("files"), list)):
        raise ValueError("Invalid Drive source manifest")
    raw_by_sha = defaultdict(list)
    for item in dm["files"]:
        if item.get("status") != "fetched":
            continue
        sha, fid = item.get("sha256"), item.get("id")
        raw_path = Path(item.get("local_file") or "")
        if (not isinstance(sha, str) or len(sha) != 64
                or not isinstance(fid, str) or not fid or not raw_path.is_file()
                or digest(raw_path) != sha):
            raise ValueError("Unverified raw Drive provenance")
        raw_by_sha[sha].append(fid)
    files = {}
    # Read-only, SHA-bound source row metadata for PRIVATE rejected-match QA.
    # Duplicate native match keys are deliberately not resolved by guessing.
    source_match_rows = {}
    duplicate_source_match_keys = set()
    observations = defaultdict(lambda: {
        "names": set(), "source_rows": 0, "candidates": defaultdict(set), "evidence": set()
    })
    count = Counter()
    for item in nr.get("normalized", []):
        path = Path(item["path"])
        sha, tour = item.get("source_sha256"), item.get("tour")
        if (not path.is_file() or not isinstance(sha, str) or len(sha) != 64
                or sha not in raw_by_sha or len(set(raw_by_sha[sha])) != 1
                or tour not in {"atp", "wta"}):
            raise ValueError("Normalized source has no unique SHA-bound Drive origin")
        ref = "sackmann:" + path.name
        if ref in files:
            raise ValueError("Duplicate normalized file provenance")
        files[ref] = (sha, tour, raw_by_sha[sha][0])
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for line_number, row in enumerate(csv.DictReader(handle), start=2):
                count["normalized_rows_seen"] += 1
                if count["normalized_rows_seen"] > 250_000:
                    raise ValueError("Review registry row cap exceeded")
                if row.get("league") != tour:
                    raise ValueError("Tour changed in normalized CSV")
                source_match_id = str(row.get("source_record_id") or "").strip() or (
                    str(row.get("tourney_id") or "") + ":" +
                    str(row.get("match_num") or line_number)
                )
                match_key = (ref, source_match_id)
                raw_metadata = {
                    "tournament": str(row.get("tourney_name") or ""),
                    "date": str(row.get("tourney_date") or ""),
                    "date_kind": str(row.get("source_date_kind") or "unverified"),
                    "round": str(row.get("round") or ""),
                    "surface": str(row.get("surface") or ""),
                    "best_of": str(row.get("best_of") or ""),
                    "winner_name": str(row.get("winner_name") or ""),
                    "loser_name": str(row.get("loser_name") or ""),
                }
                if match_key in source_match_rows:
                    duplicate_source_match_keys.add(match_key)
                    source_match_rows[match_key] = None
                else:
                    source_match_rows[match_key] = raw_metadata
                for side in ("winner", "loser"):
                    sid = native_id(row.get(f"source_{side}_id"))
                    if not sid:
                        count["missing_source_side_ids"] += 1
                        continue
                    key = (sha, tour, sid)
                    ob = observations[key]
                    ob["names"].add(str(row.get(f"{side}_name") or "").strip())
                    ob["source_rows"] += 1
    # Metadata evidence remains review-only even after the stats-only stage
    # accepts a match. Neither names nor dates attest provider-native IDs.
    auto_path = stage_dir / "link" / "auto_linked.jsonl"
    if not auto_path.is_file():
        raise ValueError("Missing real offline-linker evidence")
    eligible_ids = set()
    with (stage_dir / "eligible.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                if item.get("import_ready") is not True:
                    raise ValueError("Invalid approved stage item")
                if item["match_id"] in eligible_ids:
                    raise ValueError("Duplicate eligible canonical ID")
                eligible_ids.add(item["match_id"])
    all_candidate_matches = set()
    candidate_match_reviews = []
    with auto_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            candidate = json.loads(line)
            match_id, canon = candidate.get("match_id"), candidate.get("canonical") or {}
            cids = {
                "p1": str(canon.get("player1_id") or ""),
                "p2": str(canon.get("player2_id") or ""),
            }
            if not match_id or not all(cids.values()) or cids["p1"] == cids["p2"]:
                raise ValueError("Missing canonical candidate identity")
            if match_id in all_candidate_matches:
                raise ValueError("Duplicate canonical candidate match in linker evidence")
            all_candidate_matches.add(match_id)
            if len(all_candidate_matches) > 25_000:
                raise ValueError("Unbounded private candidate review")
            source_proofs = []
            for source in candidate.get("sources") or []:
                ref = source.get("source")
                if ref not in files:
                    raise ValueError("Unrecognized source in linker evidence")
                sha, tour, drive_id = files[ref]
                source_key = (ref, str(source.get("source_match_id") or ""))
                source_metadata = source_match_rows.get(source_key)
                source_proofs.append({
                    "source": ref,
                    "source_match_id": source_key[1],
                    "source_sha256": sha,
                    "source_drive_id": drive_id,
                    "evidence": sorted(set(source.get("evidence") or [])),
                    "metadata_status": ("AMBIGUOUS_SOURCE_KEY" if source_key in duplicate_source_match_keys
                                        else "SOURCE_ROW_MISSING" if source_metadata is None
                                        else "UNIQUE_SHA_BOUND_NORMALIZED_ROW"),
                    "source_metadata": source_metadata,
                })
                mapping = source.get("mapping") or {}
                if set(mapping) != {"a", "b"} or set(mapping.values()) != {"p1", "p2"}:
                    raise ValueError("Invalid candidate player orientation")
                if source.get("source_id_namespace") != "drive-unverified":
                    raise ValueError("Provider-source IDs promoted to wrong namespace")
                for side in ("a", "b"):
                    sid = native_id(source.get(f"source_player_{side}_id"))
                    if not sid:
                        continue
                    key = (sha, tour, sid)
                    if key not in observations:
                        raise ValueError("Candidate ID absent from verified normalized source")
                    cid = cids[mapping[side]]
                    observations[key]["candidates"][cid].add(match_id)
                    observations[key]["evidence"].update(source.get("evidence") or [])
            candidate_match_reviews.append({
                "match_id": match_id,
                "canonical": {
                    key: str(canon.get(key) or "")
                    for key in ("tour", "scheduled_date_utc", "tournament",
                                "round_name", "surface", "winner_id")
                },
                "source_proofs": source_proofs,
                "strict_stage_eligible_not_written": match_id in eligible_ids,
                "state": "PRIVATE_METADATA_REVIEW_ONLY",
                "independently_verified": False,
                "write_authorized": False,
            })
    rows = []
    for (sha, tour, sid), ob in sorted(observations.items()):
        matches = sorted({mid for mids in ob["candidates"].values() for mid in mids})
        if len(ob["candidates"]) > 1:
            status = "QUARANTINE_CONFLICTING_CANONICAL_CANDIDATES"
        elif matches:
            status = "METADATA_CANDIDATE_NOT_INDEPENDENTLY_VERIFIED"
        else:
            status = "SOURCE_ONLY_UNLINKED"
        count[status] += 1
        rows.append({
            "tour": tour, "source_sha256": sha,
            "source_drive_id": raw_by_sha[sha][0],
            "source_id_namespace": "drive-file-sha256:" + sha,
            "source_player_id": sid, "source_observed_names": sorted(ob["names"]),
            "source_row_appearances": ob["source_rows"],
            "candidate_canonical_player_ids": sorted(ob["candidates"]),
            "candidate_canonical_match_ids": matches,
            "linker_metadata_evidence": sorted(ob["evidence"]),
            "status": status, "independently_verified": False,
            "write_authorized": False,
        })
    document = {
        "schema": SCHEMA, "state": "PRIVATE_REVIEW_ONLY",
        "production_mutated": False, "canonical_write_authorized": False,
        "crosswalk_promotion_authorized": False, "api_requests": 0,
        "normalized_report_sha256": digest(normalized_report),
        "stage_report_sha256": digest(stage_dir / "report.json"),
        "linker_stage_sha256": digest(auto_path),
        "drive_manifest_sha256": digest(drive_manifest),
        "source_ids_count": len(rows),
        "candidate_match_count": len(all_candidate_matches),
        "strict_eligible_match_count": len(eligible_ids),
        "counts": dict(sorted(count.items())), "players": rows,
        "candidate_match_reviews": sorted(candidate_match_reviews,
                                          key=lambda item: str(item["match_id"])),
        "duplicate_source_match_keys_count": len(duplicate_source_match_keys),
        "warning": "Metadata candidates only. Independent primary-source ID attestation and reuse rights are required before crosswalk promotion.",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return document


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--normalized-report", type=Path, required=True)
    p.add_argument("--stage-dir", type=Path, required=True)
    p.add_argument("--drive-manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = build(a.normalized_report, a.stage_dir, a.drive_manifest, a.output)
    print(json.dumps({
        "state": result["state"], "source_ids_count": result["source_ids_count"],
        "candidate_match_count": result["candidate_match_count"], "counts": result["counts"]
    }))


if __name__ == "__main__":
    main()
