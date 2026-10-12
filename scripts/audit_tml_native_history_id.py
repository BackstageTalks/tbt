#!/usr/bin/env python3
"""Read-only exact historical import ID comparison for TML ATP source rows.

The original BlinQ historical importer hashes its full native match key. A
match to an existing proposed canonical ID supports lineage review ONLY;
it is never independent provider-event proof or canonical write approval.
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

SHA = re.compile(r"^[0-9a-f]{64}$")
ROUNDS = {
    "f": "f", "final": "f", "the final": "f",
    "sf": "sf", "semifinal": "sf", "semifinals": "sf",
    "qf": "qf", "quarterfinal": "qf", "quarterfinals": "qf",
    "r16": "r16", "round of 16": "r16", "r32": "r32",
    "round of 32": "r32", "r64": "r64", "round of 64": "r64",
    "r128": "r128", "round of 128": "r128",
    "q1": "q1", "q2": "q2", "q3": "q3", "q4": "q4",
    "rr": "rr", "round robin": "rr", "br": "br",
}


def norm(s):
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t.lower().replace("_", " ")).split())


def history_id(row):
    raw = row.get("raw_columns") or {}
    key = row.get("source_native_event_key")
    if (row.get("tour") != "atp" or not isinstance(raw, dict)
            or not re.fullmatch(r"tml-atp-202[2-5]", str(row.get("source_namespace") or ""))
            or not isinstance(key, list) or len(key) != 3 or key[0] != "tournament-match"
            or row.get("linkage_status") != "SOURCE_UNLINKED_ORIGINAL_IDS_PRESENT"):
        return None
    tournament = str(row.get("source_tourney_id") or "").strip()
    number = str(row.get("source_match_num") or "").strip()
    players = sorted((norm(raw.get("winner_name")), norm(raw.get("loser_name"))))
    rnd = norm(row.get("source_round"))
    rnd = ROUNDS.get(rnd, rnd)
    if (not tournament or not number or any(not p for p in players)
            or players[0] == players[1] or not rnd
            or key[1:] != [tournament, number]
            or str(raw.get("tourney_id") or "").strip() != tournament
            or str(raw.get("match_num") or "").strip() != number):
        return None
    composite = "|".join(("atp", "main", tournament, number, rnd, "|".join(players)))
    return "hist-js:atp:" + hashlib.sha256(composite.encode("utf-8")).hexdigest()[:24]


def checked(path, sha, max_size):
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError("Pinned SHA-256 required")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_size:
        raise ValueError("Untrusted input path or size")
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        for part in iter(lambda: file.read(1024*1024), b""):
            hasher.update(part)
    if hasher.hexdigest() != sha:
        raise ValueError("Original input digest mismatch")


def jsonl(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as source:
        for index, line in enumerate(source, 1):
            if index > 100000:
                raise ValueError("Excessive original source observations")
            if line.strip():
                x = json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
                if not isinstance(x, dict):
                    raise ValueError("Unexpected source row")
                yield x


def probe(source, source_sha, context, context_sha, out):
    checked(source, source_sha, 32*1024*1024)
    checked(context, context_sha, 8*1024*1024)
    refs = defaultdict(list)
    stats = Counter()
    for row in jsonl(source):
        if (row.get("write_authorized") is not False
                or row.get("import_ready") is not False
                or row.get("canonical_match_id") is not None):
            raise ValueError("Premature original source authorization")
        key = row.get("source_native_event_key")
        if not isinstance(key, list) or len(key) != 3:
            stats["unkeyed_or_ambiguous_original"] += 1
            continue
        if not all(isinstance(x, str) for x in key):
            stats["bad_source_key"] += 1
            continue
        refs[(row.get("source_namespace"), tuple(key))].append(row)
    private = []
    seen = set()
    for candidate in jsonl(context):
        if (candidate.get("import_ready") is not False
                or candidate.get("write_authorized") is not False
                or candidate.get("independent_event_id_attested") is not False
                or candidate.get("candidate_new_null_fields") is not None):
            raise ValueError("Unsafe review candidate")
        key = candidate.get("source_native_event_key")
        if not isinstance(key, list) or len(key) != 3:
            raise ValueError("No source native candidate key")
        identifier = (candidate.get("source_namespace"), tuple(key))
        if identifier in seen:
            raise ValueError("Duplicate native source candidate")
        seen.add(identifier)
        matches = refs.get(identifier, [])
        if len(matches) != 1:
            stats["missing_or_ambiguous_original"] += 1
            continue
        native = history_id(matches[0])
        if not native:
            stats["history_fingerprint_unavailable"] += 1
            continue
        if candidate.get("candidate_canonical_match_id") != native:
            stats["historical_native_id_not_equal"] += 1
            continue
        stats["equal_deterministic_history_id_review_only"] += 1
        private.append({
            "source_namespace": identifier[0],
            "source_native_event_key": list(key),
            "candidate_canonical_match_id": native,
            "historical_fingerprint_equal": True,
            "independent_event_id_attested": False,
            "canonical_provider_provenance_verified": False,
            "import_ready": False, "write_authorized": False,
        })
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "native-history-fingerprint-private.jsonl"
    dest.write_text("".join(json.dumps(x, sort_keys=True)+"\n" for x in private),
                    encoding="utf-8")
    report = {
        "status": "TML_HIST_JS_FINGERPRINT_READ_ONLY",
        "source_sha256": source_sha, "context_sha256": context_sha,
        "counts": dict(sorted(stats.items())),
        "private_sidecar_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        "ready_for_cdb_write": 0, "cdb_writes": 0, "provider_api_requests": 0,
        "model_trained": False,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--source-sha256", required=True)
    p.add_argument("--context", type=Path, required=True)
    p.add_argument("--context-sha256", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    result = probe(a.source, a.source_sha256, a.context, a.context_sha256, a.out)
    print(json.dumps({"status": result["status"], "counts": result["counts"],
                      "cdb_writes": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
