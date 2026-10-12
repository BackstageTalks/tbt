#!/usr/bin/env python3
"""Close out one Charting -> canonical CDB candidate without unsafe writes.

This is an evidence gate, NOT a canonical writer. Exact source identifiers,
provider IDs, source field gaps, latest canonical Parquet bytes and independent
whole-match statistics must all be inspected. Conflicts remain quarantined.
"""
from __future__ import annotations
import argparse, gzip, hashlib, json, math
from pathlib import Path

SOURCE = "20250812-W-ITF_Saskatoon-R32-Gabriella_Mikaul-Olivia_Gadecki"
MATCH = "668e94dc3987367e25ecabb4"
EVENT = "14401726"
EXTERNAL = {
    "p1_aces": 3, "p1_double_faults": 2, "p1_first_serve_win": 19 / 21,
    "p1_second_serve_win": 5 / 11, "p1_service_points_won": 24 / 32,
    "p1_return_points_won": 26 / 36, "p2_aces": 1,
    "p2_double_faults": 3, "p2_first_serve_win": 10 / 24,
    "p2_second_serve_win": 0, "p2_service_points_won": 10 / 36,
    "p2_return_points_won": 8 / 32,
}
EVIDENCE_URLS = [
    "https://www.stevegtennis.com/head-to-head/women/Olivia_Gadecki/Gabriella_Mikaul/",
    "https://www.sofascore.com/tennis/match/gabriella-mikaul-olivia-gadecki/bdTbsHTri",
    "https://www.flashscore.com/tennis/itf-women-singles/w50-saskatoon/results",
]


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decide(witness, report, observations, canonical, current_sha, research_sha):
    require(witness.get("source_match_id") == SOURCE and
            witness.get("canonical_candidate_id") == MATCH, "Incorrect source/canonical ID")
    require(witness.get("event_identity_proven") is False and witness.get("cdb_writes") == 0,
            "Missing independent event proof or unexpected claimed write")
    require(witness.get("context_link_type") == "RESEARCH_TOURNAMENT_ALIAS_ONLY",
            "Changed charting link type")
    require(witness.get("source_match", {}).get("players") ==
            ["Gabriella Mikaul", "Olivia Gadecki"], "Source competitors changed")
    require(str(witness.get("source_match", {}).get("date")) == "20250812",
            "Source date changed")
    counts = report.get("counts", {})
    require(counts.get("missing_candidate_cells_not_approved") == 13 and
            counts.get("context_review_candidate_rows") == len(observations) and
            counts.get("RESEARCH_FIELD_GAPS_PENDING_EVENT_ID_PROOF") == 1,
            "Unexpected scope of outstanding research NULL proposals")
    waiting = [x for x in observations if
               x.get("status") == "RESEARCH_FIELD_GAPS_PENDING_EVENT_ID_PROOF"]
    require(len(waiting) == 1, "Multiple outstanding proposals")
    item = waiting[0]
    proposed = item.get("missing_cells")
    require(item.get("source_match_id") == SOURCE and
            item.get("canonical_match_id_candidate") == MATCH and
            item.get("write_authorized") is False, "Research proposal trust boundary changed")
    require(isinstance(proposed, dict) and len(proposed) == 13 and
            proposed == witness.get("missing_cells"), "Witness and 13 cells disagree")
    require(not item.get("matching_existing_cells") and
            not item.get("conflicting_existing_cells"), "Unexpected comparison state")
    require(str(canonical.get("match_id")) == MATCH and
            str(canonical.get("player1_id")) == "232651" and
            str(canonical.get("player2_id")) == "1044682" and
            str(canonical.get("winner_id")) == "232651", "Current canonical identity changed")
    ctx = canonical.get("provider_context_json")
    if isinstance(ctx, str):
        ctx = json.loads(ctx)
    require(isinstance(ctx, dict) and str(ctx.get("_tbt_provider_event_id") or
            ctx.get("provider_event_id") or "") == EVENT, "Provider event ID changed")
    current = canonical.get("stats_json")
    if isinstance(current, str):
        current = json.loads(current)
    require(isinstance(current, dict), "Invalid canonical stats")
    nonnull = sorted(k for k in proposed if current.get(k) is not None)
    conflicts, agreements = [], []
    for key, observed in EXTERNAL.items():
        candidate = proposed.get(key)
        require(isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
                and math.isfinite(candidate), "Missing/invalid compared metric " + key)
        delta = abs(float(candidate) - float(observed))
        if delta > (0 if key.endswith(("aces", "double_faults")) else 0.000001):
            conflicts.append({"field": key, "charting": candidate,
                              "independent": round(float(observed), 12)})
        else:
            agreements.append(key)
    require(any(x["field"] == "p1_aces" for x in conflicts),
            "Independent whole-match aces mismatch not confirmed")
    require(len(current_sha) == len(research_sha) == 64, "Missing checksums")
    return {
        "schema": 1,
        "result": "NO_SAFE_CANONICAL_ADDITIONS_FROM_CHARTING",
        "source_match_id": SOURCE,
        "canonical_match_id": MATCH,
        "canonical_provider_event_id": EVENT,
        "canonical_partition_2025_sha256": current_sha,
        "research_sha256": research_sha,
        "context_candidates_reviewed": len(observations),
        "unapproved_candidate_cells": 13,
        "independent_conflicts": conflicts,
        "matching_independent_metrics": sorted(agreements),
        "current_canonical_nonnull_candidate_fields": nonnull,
        "charted_serve_points": {"olivia_gadecki": 28, "gabriella_mikaul": 29},
        "independent_whole_match_serve_points": {"olivia_gadecki": 32, "gabriella_mikaul": 36},
        "reason": "Charted point subset is not equivalent to whole-match statistics, and charting event ID lacks independent canonical provider-event bridge",
        "evidence_urls": EVIDENCE_URLS,
        "cells_authorized": 0,
        "cells_written": 0,
        "canonical_assets_modified": False,
        "model_trained": False,
        "disposition": "Quarantine 13 proposed source-derived cells; preserve all research sources",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--witness", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--observations", type=Path, required=True)
    ap.add_argument("--partition", type=Path, required=True)
    ap.add_argument("--sha256", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    report = json.loads(a.report.read_text())
    research_sha = sha(a.observations)
    require(report.get("field_gap_output_sha256") == research_sha,
            "Crosswalk source SHA mismatch")
    require(sha(a.partition) == a.sha256, "Current canonical year SHA mismatch")
    with gzip.open(a.observations, "rt", encoding="utf8") as stream:
        observations = [json.loads(line) for line in stream if line.strip()]
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(a.partition)
    cols = ["match_id", "player1_id", "player2_id", "winner_id",
            "provider_context_json", "stats_json"]
    require(set(cols).issubset(pf.schema.names), "Missing canonical columns")
    matched = [r for chunk in pf.iter_batches(columns=cols, batch_size=8192)
               for r in chunk.to_pylist() if str(r.get("match_id")) == MATCH]
    require(len(matched) == 1, "Canonical event not unique in current year")
    witness = json.loads(a.witness.read_text())
    decision = decide(witness, report, observations, matched[0], a.sha256, research_sha)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(decision, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"result": decision["result"], "conflicts": len(decision["independent_conflicts"]),
                      "authorized": 0, "production_writes": 0}))


if __name__ == "__main__":
    main()
