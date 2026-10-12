#!/usr/bin/env python3
"""Offline, SHA-pinned *review-only* ATP identifier bridge for BlinQ CDB gaps.

Joins the PRIVATE source gap queue to already archived CC0 Wikidata/canonical
identity links via an EXACT ATP Tour ID, QID and a unique canonical owner.
Never treats names, profiles or an ATP ID as proof of a canonical MATCH.
No CDB mutation, model training, network calls or background/scheduled jobs.
Keep per-player output PRIVATE.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import unicodedata

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
QID = re.compile(r"Q[1-9][0-9]*\Z")
ATP = re.compile(r"[A-Za-z0-9]{2,32}\Z")
MAX_ROWS = 200_000
MAX_FILE_BYTES = 40 * 1024 * 1024


def digest(path: Path, expected: str) -> str:
    if not isinstance(expected, str) or not SHA256.fullmatch(expected):
        raise ValueError("Required complete expected source SHA-256")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Missing, symlinked or oversized source input")
    h = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            h.update(block)
    actual = h.hexdigest()
    if actual != expected:
        raise ValueError("Original evidence SHA-256 mismatch")
    return actual


def rows(path: Path):
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as file:
        for n, line in enumerate(file, 1):
            if n > MAX_ROWS:
                raise ValueError("Too many private identity observations")
            if not line.strip():
                continue
            item = json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
            if not isinstance(item, dict):
                raise ValueError("Expected JSON object in source")
            yield item


def normalize(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value or "").casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", s))


def build(priority: Path, priority_sha: str, canonical_links: Path,
          canonical_sha: str, output: Path) -> dict:
    digest(priority, priority_sha)
    digest(canonical_links, canonical_sha)
    gap_rows = list(rows(priority))
    if not gap_rows:
        raise ValueError("Empty source identity gap queue")

    # Keep all conflicting canonical owners, QID reuse and aliases visible
    # to the collision check before producing even a review candidate.
    owners: dict[str, set[tuple[str, str]]] = defaultdict(set)
    by_qid: dict[str, set[tuple[str, str]]] = defaultdict(set)
    by_canonical: dict[str, set[tuple[str, str]]] = defaultdict(set)
    label_by_edge: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for link in rows(canonical_links):
        if (link.get("tour") != "atp" or link.get("source") != "Wikidata"
                or link.get("license") != "CC0-1.0"
                or link.get("evidence") != "unique_exact_name_both_sides_plus_tour_specific_id"):
            continue
        qid, cid = link.get("wikidata_qid"), link.get("player_id")
        profile = link.get("external_ids")
        if (not isinstance(qid, str) or not QID.fullmatch(qid)
                or not isinstance(cid, str) or not cid
                or not isinstance(profile, dict)
                or not isinstance(profile.get("atp"), list)):
            continue
        codes = {str(k).upper() for k in profile["atp"]
                 if isinstance(k, str) and ATP.fullmatch(k)}
        for code in codes:
            owners[code].add((qid, cid))
            by_qid[qid].add((code, cid))
            by_canonical[cid].add((code, qid))
            label_by_edge[(code, qid, cid)].add(normalize(link.get("canonical_name")))

    seen = set()
    counts = Counter()
    proposals = []
    for gap in gap_rows:
        sid = gap.get("source_player_id")
        if not isinstance(sid, str) or not ATP.fullmatch(sid):
            raise ValueError("Malformed ATP source gap ID")
        code = sid.upper()
        if code in seen:
            raise ValueError("Duplicate source gap player ID")
        seen.add(code)
        if (gap.get("review_only") is not True
                or gap.get("canonical_player_id") is not None
                or gap.get("evidence_required") != "independent_official_ATP_ID_to_canonical_player"):
            raise ValueError("Source gap already authorized or untrusted")
        edges = owners.get(code, set())
        if not edges:
            counts["no_existing_cc0_canonical_reference"] += 1
            continue
        if len(edges) != 1:
            counts["ambiguous_atp_id"] += 1
            continue
        qid, cid = next(iter(edges))
        if len(by_qid[qid]) != 1 or len(by_canonical[cid]) != 1:
            counts["ambiguous_qid_or_canonical_owner"] += 1
            continue
        aliases = gap.get("source_display_aliases_review_only")
        if not isinstance(aliases, list) or not all(isinstance(v, str) for v in aliases):
            raise ValueError("Malformed source name hints")
        canonical_names = label_by_edge[(code, qid, cid)] - {""}
        same = {normalize(v) for v in aliases} & canonical_names
        if not same:
            counts["name_disagreement_requires_manual_review"] += 1
            continue
        proposals.append({
            "source_atp_player_id": sid,
            "candidate_canonical_player_id": cid,
            "wikidata_qid": qid,
            "proof": "exact_ATP_ID_plus_unique_QID_canonical_link_plus_name_corroboration",
            "source_gap_file_sha256": priority_sha,
            "canonical_link_file_sha256": canonical_sha,
            "source_rows_with_other_id_verified": gap.get("rows_with_other_id_verified", 0),
            "priority_score": gap.get("priority_score", 0),
            "status": "REVIEW_ONLY_EVENT_AND_BOTH_SIDES_NOT_YET_ATTESTED",
            "canonical_match_id": None,
            "import_ready": False,
            "write_authorized": False,
            "source_name_is_not_independent_event_proof": True,
        })
        counts["existing_cc0_evidence_review_candidates"] += 1
    proposals.sort(key=lambda x: (-int(x["source_rows_with_other_id_verified"]),
                                  -int(x["priority_score"]),
                                  x["source_atp_player_id"]))
    output.mkdir(parents=True, exist_ok=True)
    target = output / "atp-gap-cc0-review-private.jsonl"
    with target.open("w", encoding="utf-8") as f:
        for row in proposals:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    report = {
        "schema": 1,
        "status": "ATP_OFFLINE_IDENTITY_REVIEW_NO_CDB_WRITE",
        "input_gap_sha256": priority_sha,
        "input_canonical_cc0_sha256": canonical_sha,
        "gap_player_ids_scanned": len(gap_rows),
        "counts": dict(sorted(counts.items())),
        "private_proposals_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "event_identity_attested": False,
        "canonical_source_snapshot_reverified": False,
        "ready_for_canonical_match_link": 0,
        "ready_for_cdb_write": 0,
        "sports_api_requests": 0,
        "cdb_writes": 0,
        "model_trained": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gaps", type=Path, required=True)
    parser.add_argument("--gaps-sha256", required=True)
    parser.add_argument("--canonical-wikidata", type=Path, required=True)
    parser.add_argument("--canonical-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    a = parser.parse_args()
    report = build(a.gaps, a.gaps_sha256, a.canonical_wikidata, a.canonical_sha256, a.out)
    # Only counts. Player IDs, names and QIDs must remain in private output.
    print(json.dumps({"status": report["status"], "counts": report["counts"],
                      "ready_for_cdb_write": 0, "sports_api_requests": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
