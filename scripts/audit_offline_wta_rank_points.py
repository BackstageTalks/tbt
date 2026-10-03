"""Read-only WTA rank/points audit for the pinned 2006-2026 source."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import candidate_link, int_or_none, parse_legacy_row


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _winner_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id):
        return str(match.player2_name or "")
    return ""


def _positive_int(value):
    value = int_or_none(value)
    return value if value is not None and value > 0 else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--source-csv", required=True)
    ap.add_argument("--source-label", default="operator_wta_txt_2006_2026_rank")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    source_path = Path(args.source_csv)
    source_sha = _sha256(source_path)

    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    by_day = defaultdict(list)
    for match in matches:
        if str(match.tour or "").lower() == "wta":
            by_day[match.scheduled_at.astimezone(timezone.utc).date()].append(match)

    counts = Counter()
    sidecar = []
    rank_fill_candidates = []
    review = []

    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            counts["source_rows"] += 1
            parsed = parse_legacy_row(row, row_number=number, tour="wta")
            if parsed is None:
                counts["invalid_source_rows"] += 1
                continue
            if parsed.rank_a is None or parsed.rank_b is None:
                counts["source_missing_rank_pair"] += 1
                continue
            counts["usable_rank_rows"] += 1
            points_a = _positive_int(row.get("Pts_1"))
            points_b = _positive_int(row.get("Pts_2"))

            candidates = []
            for delta in (-1, 0, 1):
                candidates.extend(by_day.get(parsed.event_date + timedelta(days=delta), []))

            scored = []
            for match in {str(item.match_id): item for item in candidates}.values():
                linked = candidate_link(
                    parsed,
                    canonical_tour=match.tour,
                    canonical_date=match.scheduled_at.astimezone(timezone.utc).date(),
                    canonical_player1=match.player1_name,
                    canonical_player2=match.player2_name,
                    canonical_winner=_winner_name(match),
                    canonical_tournament=match.tournament,
                    canonical_surface=match.surface,
                    canonical_round=match.round_name,
                    canonical_best_of=match.best_of,
                    canonical_rank1=None,
                    canonical_rank2=None,
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
                continue

            _, accepted, match, linked = top[0]
            if not accepted:
                counts["weak_evidence"] += 1
                continue

            if linked["orientation"] == "direct":
                rank1, rank2 = parsed.rank_a, parsed.rank_b
                pts1, pts2 = points_a, points_b
            else:
                rank1, rank2 = parsed.rank_b, parsed.rank_a
                pts1, pts2 = points_b, points_a

            counts["identity_linked"] += 1
            exact_day = match.scheduled_at.astimezone(timezone.utc).date() == parsed.event_date
            if exact_day:
                counts["identity_linked_exact_day"] += 1
            else:
                counts["identity_linked_plusminus_1"] += 1

            existing = (match.player1_rank, match.player2_rank)
            if existing[0] is None and existing[1] is None:
                counts["canonical_both_rank_missing"] += 1
                if exact_day:
                    counts["strict_fill_candidate"] += 1
                    rank_fill_candidates.append({
                        "schema": 1,
                        "match_id": str(match.match_id),
                        "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                        "player1_id": str(match.player1_id),
                        "player1_name": str(match.player1_name),
                        "player2_id": str(match.player2_id),
                        "player2_name": str(match.player2_name),
                        "incoming_player1_rank": int(rank1),
                        "incoming_player2_rank": int(rank2),
                        "source_match_date": parsed.event_date.isoformat(),
                        "source_match_id": parsed.source_match_id,
                        "source_file_sha256": source_sha,
                        "link_score": linked["score"],
                        "link_evidence": linked["evidence"],
                        "orientation": linked["orientation"],
                    })
            elif existing[0] is None or existing[1] is None:
                counts["canonical_one_rank_missing"] += 1
                # Safe one-sided fill: exact match date and the already-present
                # canonical rank must exactly agree with the pinned source.
                present_rank_matches = (
                    (existing[0] is None and int(existing[1]) == int(rank2))
                    or (existing[1] is None and int(existing[0]) == int(rank1))
                )
                if exact_day and present_rank_matches:
                    counts["strict_fill_candidate_one_missing"] += 1
                    rank_fill_candidates.append({
                        "schema": 1,
                        "match_id": str(match.match_id),
                        "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                        "player1_id": str(match.player1_id),
                        "player1_name": str(match.player1_name),
                        "player2_id": str(match.player2_id),
                        "player2_name": str(match.player2_name),
                        "incoming_player1_rank": int(rank1),
                        "incoming_player2_rank": int(rank2),
                        "existing_player1_rank": existing[0],
                        "existing_player2_rank": existing[1],
                        "source_match_date": parsed.event_date.isoformat(),
                        "source_match_id": parsed.source_match_id,
                        "source_file_sha256": source_sha,
                        "link_score": linked["score"],
                        "link_evidence": linked["evidence"],
                        "orientation": linked["orientation"],
                    })
                elif exact_day:
                    counts["one_missing_existing_rank_mismatch"] += 1
            else:
                counts["canonical_both_rank_present"] += 1
                d1 = abs(int(existing[0]) - int(rank1))
                d2 = abs(int(existing[1]) - int(rank2))
                if d1 == 0 and d2 == 0:
                    counts["existing_rank_exact_pair"] += 1
                elif d1 <= 2 and d2 <= 2:
                    counts["existing_rank_within2_pair"] += 1
                else:
                    counts["existing_rank_difference_gt2"] += 1

            if exact_day:
                sidecar.append({
                    "schema": 1,
                    "match_id": str(match.match_id),
                    "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                    "player1_rank": int(rank1),
                    "player2_rank": int(rank2),
                    "player1_rank_points": pts1,
                    "player2_rank_points": pts2,
                    "source": args.source_label,
                    "source_match_id": parsed.source_match_id,
                    "source_file_sha256": source_sha,
                    "source_match_date": parsed.event_date.isoformat(),
                    "model_feature_policy": "ranks_point_in_time_candidate; rank_points_sidecar_only",
                })

    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "source_file": source_path.name,
        "source_file_sha256": source_sha,
        "counts": dict(counts),
        "api_requests": 0,
        "production_mutated": False,
        "rank_fill_policy": "exact_date_both_missing_or_one_missing_with_exact_existing_rank_match",
        "rank_points_policy": "sidecar_only_no_model_feature",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for filename, rows in (
        ("rank-points-sidecar.jsonl", sidecar),
        ("rank-fill-candidates.jsonl", rank_fill_candidates),
        ("review.jsonl", review),
    ):
        with (out / filename).open("w", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
