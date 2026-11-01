#!/usr/bin/env python3
"""Deterministically extract provider-native CDB linkage candidates from Drive JSON.

Read-only. The output is NOT the canonical writer's \`import_ready\` stage:
identity, winner, canonical player side and field precedence still require the
existing supervised linker and CDB review. No CDB modifications are possible.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from moviodds_cdb_format import verify_cdb_archive


def extract(archive_path: Path, out_dir: Path) -> dict:
    source = archive_path.read_bytes()
    import hashlib
    source_sha = hashlib.sha256(source).hexdigest()
    data = json.loads(source)
    verify_cdb_archive(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates, review = [], []
    reasons = Counter()
    for row in data["records"]:
        candidate = row["cdb_candidate"]
        if candidate["cdb_link"]["import_ready"] is not False:
            raise ValueError("Unexpected import-ready claim in source archive")
        result = {
            **candidate,
            "source_archive_sha256": source_sha,
            "source_archive_date_utc": data["days"][0],
        }
        why = set(candidate["cdb_link"]["review_reasons"])
        if "doubles_not_in_scope" in why or "canonical_tour_unconfirmed" in why:
            review.append(result)
            if "doubles_not_in_scope" in why:
                reasons["doubles_not_in_scope"] += 1
            else:
                reasons["canonical_tour_unconfirmed"] += 1
        else:
            candidates.append(result)
            if "kickoff_utc_missing" in why:
                reasons["kickoff_utc_missing"] += 1
        if candidate["cdb_link"]["match_id"] is not None:
            raise ValueError("Source archive forged canonical CDB ID")
    for name, items in (("link_candidates.jsonl", candidates),
                        ("review.jsonl", review)):
        (out_dir / name).write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                    for item in items),
            encoding="utf-8",
        )
    report = {
        "schema": 1, "archive_format": data["format"], "source_archive_sha256": source_sha,
        "date_utc": data["days"][0], "raw": len(data["records"]),
        "linked": 0, "net_new": 0, "enriched": 0, "cdb_values_written": 0,
        "link_candidates": len(candidates), "review": len(review),
        "reasons": dict(sorted(reasons.items())),
        "import_ready": False, "cdb_mutated": False,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(extract(args.archive, args.out_dir), sort_keys=True))


if __name__ == "__main__":
    main()
