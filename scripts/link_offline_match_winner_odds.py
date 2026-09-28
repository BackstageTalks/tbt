"""Fail-closed offline linker for historical two-way Match Winner odds.

Read-only by design: no provider calls and no canonical writes. Legacy
Tennis-Data style CSV rows are linked to canonical history using player
identity, date, winner, tournament, surface and format evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.offline_odds import (
    build_market_marker,
    candidate_link,
    market_marker_equivalent,
    parse_legacy_row,
)


def _signature(match) -> dict[str, str]:
    return {
        "tour": str(match.tour or "").lower(),
        "scheduled_date_utc": match.scheduled_at.astimezone(timezone.utc).date().isoformat(),
        "player1_id": str(match.player1_id),
        "player1_name": str(match.player1_name),
        "player2_id": str(match.player2_id),
        "player2_name": str(match.player2_name),
        "surface": str(match.surface or ""),
        "tournament": str(match.tournament or ""),
        "round_name": str(match.round_name or ""),
        "winner_id": str(match.winner_id or ""),
    }


def _winner_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id):
        return str(match.player2_name or "")
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--source-csv", required=True)
    ap.add_argument("--tour", choices=("atp", "wta"), required=True)
    ap.add_argument("--source-label", default="operator_legacy_odds")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    source_path = Path(args.source_csv)
    source_sha = _sha256(source_path)

    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history has identity quarantine; refusing odds linking")

    by_day = defaultdict(list)
    for match in matches:
        by_day[(str(match.tour or "").lower(), match.scheduled_at.date())].append(match)

    sources = []
    counts = Counter()
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            counts["source_rows"] += 1
            parsed = parse_legacy_row(row, row_number=number, tour=args.tour)
            if parsed is None:
                counts["invalid_source_rows"] += 1
            else:
                sources.append(parsed)

    staged = []
    review = []
    quarantine = []
    for source in sources:
        candidates = []
        for delta in (-1, 0, 1):
            candidates.extend(
                by_day.get((source.tour, source.event_date + timedelta(days=delta)), [])
            )
        scored = []
        for match in {str(item.match_id): item for item in candidates}.values():
            linked = candidate_link(
                source,
                canonical_tour=str(match.tour or "").lower(),
                canonical_date=match.scheduled_at.date(),
                canonical_player1=match.player1_name,
                canonical_player2=match.player2_name,
                canonical_winner=_winner_name(match),
                canonical_tournament=match.tournament,
                canonical_surface=match.surface,
                canonical_round=match.round_name,
                canonical_best_of=match.best_of,
                canonical_rank1=match.player1_rank,
                canonical_rank2=match.player2_rank,
            )
            if linked.get("score", -100) > -100:
                scored.append((int(linked["score"]), bool(linked["accepted"]), match, linked))
        scored.sort(key=lambda item: item[0], reverse=True)

        if not scored:
            counts["unmatched"] += 1
            continue
        top_score = scored[0][0]
        top = [item for item in scored if item[0] == top_score]
        if len(top) != 1:
            counts["ambiguous"] += 1
            review.append({
                "source_match_id": source.source_match_id,
                "row_number": source.row_number,
                "reason": "ambiguous",
                "score": top_score,
                "candidate_match_ids": [str(item[2].match_id) for item in top],
            })
            continue

        _, accepted, match, linked = top[0]
        if not accepted:
            counts["weak_evidence"] += 1
            review.append({
                "source_match_id": source.source_match_id,
                "row_number": source.row_number,
                "reason": "weak_evidence",
                "candidate_match_id": str(match.match_id),
                "score": linked["score"],
                "evidence": linked["evidence"],
            })
            continue

        marker = build_market_marker(
            linked["market"],
            source=args.source_label,
            source_match_id_value=source.source_match_id,
            source_file_sha256=source_sha,
        )
        existing = (match.provider_payload or {}).get("_tbt_match_winner_odds")
        if existing:
            if market_marker_equivalent(existing, marker):
                counts["already_present"] += 1
            else:
                counts["market_conflicts"] += 1
                quarantine.append({
                    "match_id": str(match.match_id),
                    "source_match_id": source.source_match_id,
                    "reason": "existing_market_conflict",
                    "existing": existing,
                    "incoming": marker,
                })
            continue

        counts["identity_linked"] += 1
        counts["staged_matches"] += 1
        staged.append({
            "schema": 1,
            "match_id": str(match.match_id),
            "canonical": _signature(match),
            "incoming_market": marker,
            "source": {
                "row_number": source.row_number,
                "source_match_id": source.source_match_id,
                "score": linked["score"],
                "evidence": linked["evidence"],
                "orientation": linked["orientation"],
            },
            "import_ready": True,
        })

    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "source_rows": counts.get("source_rows", 0),
        "usable_source_rows": len(sources),
        "source_file_sha256": source_sha,
        "counts": dict(counts),
        "production_mutated": False,
        "api_requests": 0,
        "price_kind": "historical_two_way_unspecified_timestamp",
        "note": (
            "Read-only linker. Historical price timestamp semantics are intentionally "
            "not upgraded to opening/closing odds."
        ),
    }
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for filename, rows in (
        ("auto_linked.jsonl", staged),
        ("review.jsonl", review),
        ("quarantine.jsonl", quarantine),
    ):
        with (out / filename).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
