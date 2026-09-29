"""Fail-closed linker for Valuebetennis historical opening/closing markets.

Read-only by design. Closing odds are retained for CLV / market-movement
validation only and are never written into MatchRecord.stats or model features.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_market_history import (
    build_market_history_marker,
    candidate_link,
    market_history_equivalent,
    parse_valuebet_row,
)
from tbt.data.offline_odds import norm_text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--source-csv", action="append", required=True)
    ap.add_argument("--source-label", default="valuebetennis_cc_by_4")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history has identity quarantine; refusing market-history linking")

    by_pair = defaultdict(list)
    for match in matches:
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        by_pair[(str(match.tour or "").lower(), pair)].append(match)

    counts = Counter()
    staged = []
    review = []
    quarantine = []
    seen_source_ids = set()

    for source_name in args.source_csv:
        source_path = Path(source_name)
        source_sha = _sha256(source_path)
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for number, row in enumerate(csv.DictReader(handle, delimiter=";"), start=2):
                counts["source_rows"] += 1
                source = parse_valuebet_row(row, row_number=number)
                if source is None:
                    counts["invalid_or_marketless_source_rows"] += 1
                    continue
                unique_source_key = (source.source_match_id, source_sha)
                if unique_source_key in seen_source_ids:
                    counts["duplicate_source_rows"] += 1
                    continue
                seen_source_ids.add(unique_source_key)
                counts["usable_source_rows"] += 1

                pair = tuple(sorted((norm_text(source.player_a), norm_text(source.player_b))))
                candidates = by_pair.get((source.tour, pair), [])
                scored = []
                for match in candidates:
                    linked = candidate_link(
                        source,
                        canonical_tour=match.tour,
                        canonical_date=match.scheduled_at.date(),
                        canonical_player1=match.player1_name,
                        canonical_player2=match.player2_name,
                        canonical_winner=_winner_name(match),
                        canonical_tournament=match.tournament,
                        canonical_surface=match.surface,
                        canonical_round=match.round_name,
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
                        "source_file": source_path.name,
                        "row_number": number,
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
                        "source_file": source_path.name,
                        "row_number": number,
                        "reason": "weak_evidence",
                        "candidate_match_id": str(match.match_id),
                        "score": linked["score"],
                        "evidence": linked["evidence"],
                    })
                    continue

                marker = build_market_history_marker(
                    source=source,
                    linked=linked,
                    source_label=args.source_label,
                    source_file_sha256=source_sha,
                )
                existing = (match.provider_payload or {}).get("_tbt_market_history")
                if existing:
                    if market_history_equivalent(existing, marker):
                        counts["already_present"] += 1
                    else:
                        counts["market_conflicts"] += 1
                        quarantine.append({
                            "match_id": str(match.match_id),
                            "source_match_id": source.source_match_id,
                            "reason": "existing_market_history_conflict",
                            "existing": existing,
                            "incoming": marker,
                        })
                    continue

                staged.append({
                    "schema": 1,
                    "match_id": str(match.match_id),
                    "canonical": _signature(match),
                    "incoming_market_history": marker,
                    "source": {
                        "source_file": source_path.name,
                        "row_number": number,
                        "source_match_id": source.source_match_id,
                        "score": linked["score"],
                        "evidence": linked["evidence"],
                        "orientation": linked["orientation"],
                    },
                    "import_ready": True,
                })
                counts["identity_linked"] += 1
                counts["staged_matches"] += 1
                if linked.get("opening") is not None:
                    counts["staged_opening_markets"] += 1
                if linked.get("closing") is not None:
                    counts["staged_closing_markets"] += 1

    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "source_files": [Path(item).name for item in args.source_csv],
        "counts": dict(counts),
        "production_mutated": False,
        "api_requests": 0,
        "model_feature_policy": "closing_validation_only",
        "note": "Read-only linker. No canonical write and no provider API call occurred.",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
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
