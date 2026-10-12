#!/usr/bin/env python3
"""Offline coverage and priority queue for verified ATP ID-to-canonical crosswalk gaps.

Consumes only a PRIVATE, SHA-pinned source-native observation lake and an
independently verified source player ID link file. Never declares an event
identical to a CDB match and never allows a canonical write.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

from prepare_tml_atp_cdb import verified_links


def digest(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def audit(observations: Path, private_links: Path, links_sha: str, out: Path):
    if not observations.is_file() or not private_links.is_file():
        raise ValueError("Missing private evidence or authoritative source crosswalk")
    links, crosswalk_quality = verified_links(private_links, links_sha)
    source_counts, missing = Counter(), defaultdict(Counter)
    name_aliases = defaultdict(set)
    rows = 0
    with gzip.open(observations, "rt", encoding="utf-8") as src:
        for line in src:
            row = json.loads(line)
            if (row.get("schema") != 1 or row.get("canonical_match_id") is not None
                    or row.get("write_authorized") is not False
                    or row.get("import_ready") is not False):
                raise ValueError("Untrusted source-only evidence schema")
            if not str(row.get("source_namespace", "")).startswith("tml-atp-"):
                raise ValueError("Unexpected ID namespace; do not mix providers")
            rows += 1
            ids = [str(row.get("source_winner_id") or ""),
                   str(row.get("source_loser_id") or "")]
            if not ids[0] or not ids[1] or ids[0]==ids[1]:
                source_counts["incomplete_source_players"] += 1
                continue
            mapped = [v in links for v in ids]
            if all(mapped):
                source_counts["both_player_ids_have_independent_crosswalk"] += 1
            elif any(mapped):
                source_counts["exactly_one_player_id_has_independent_crosswalk"] += 1
            else:
                source_counts["neither_player_id_has_independent_crosswalk"] += 1
            if row.get("linkage_status") != "SOURCE_UNLINKED_ORIGINAL_IDS_PRESENT":
                source_counts["rows_quarantined_or_missing_event_key"] += 1
                continue
            side_names = [row.get("raw_columns", {}).get("winner_name"),
                          row.get("raw_columns", {}).get("loser_name")]
            for index, sid in enumerate(ids):
                if sid in links:
                    continue
                missing[sid]["all_rows_needing_id"] += 1
                missing[sid]["rows_with_other_id_verified"] += int(mapped[1-index])
                missing[sid]["rows_with_both_ids_missing"] += int(not mapped[1-index])
                if len(row.get("source_stats_nonempty") or {}) >= 12:
                    missing[sid]["rich_boxscore_rows"] += 1
                alias = side_names[index]
                if isinstance(alias, str) and alias:
                    name_aliases[sid].add(alias[:96])
    # A one-sided solved bridge unlocks more 2-player candidates. Names below
    # remain review hints, never standalone identity proof.
    priority = []
    for sid, c in missing.items():
        priority.append({
            "source_player_id": sid,
            "review_only": True, "canonical_player_id": None,
            "evidence_required": "independent_official_ATP_ID_to_canonical_player",
            "priority_score": c["rows_with_other_id_verified"] * 5 +
                              c["rows_with_both_ids_missing"] +
                              c["rich_boxscore_rows"],
            **dict(c),
            "source_display_aliases_review_only": sorted(name_aliases[sid])[:4],
        })
    priority.sort(key=lambda x: (-x["priority_score"],-x["rows_with_other_id_verified"],
                                 -x["all_rows_needing_id"],x["source_player_id"]))
    out.mkdir(parents=True, exist_ok=True)
    queue=out/"identity-crosswalk-priority-private.jsonl"
    with queue.open("w",encoding="utf-8") as file:
        for row in priority:
            file.write(json.dumps(row,sort_keys=True,ensure_ascii=False)+"\n")
    report = {
        "schema":1,"status":"OFFLINE_PLAYER_ID_BRIDGE_PRIORITIZED_NO_MATCH_IMPORT",
        "source_observations_sha256":digest(observations),
        "trusted_crosswalk_sha256":links_sha,
        "rows_checked":rows,
        "source_player_id_gaps":len(missing),
        "source_row_identity_coverage":dict(sorted(source_counts.items())),
        "verified_player_links":len(links),
        "verified_crosswalk_quality":crosswalk_quality,
        "private_ranked_queue_sha256":digest(queue),
        "canonical_match_identity_attested":False,
        "ready_for_canonical_write":0,
        "sports_api_requests":0,
        "purpose":"Prioritize independent identifier crosswalk work, never names-as-identity",
    }
    (out/"identity-gap-report.json").write_text(
        json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--observations",type=Path,required=True)
    p.add_argument("--private-links",type=Path,required=True)
    p.add_argument("--links-sha256",required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    r=audit(a.observations,a.private_links,a.links_sha256,a.out)
    print(json.dumps({k:r[k] for k in (
        "rows_checked","source_player_id_gaps","source_row_identity_coverage",
        "ready_for_canonical_write","sports_api_requests")},sort_keys=True))


if __name__=="__main__":
    main()
