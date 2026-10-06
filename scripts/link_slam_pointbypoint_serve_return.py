"""Strict Grand Slam point-table -> canonical serve/return linker.

Input is Jeff Sackmann's tennis_slam_pointbypoint format: one *-matches.csv
metadata file and one *-points.csv point table per Slam/year. Singles only;
files explicitly labelled doubles or mixed are excluded.

Because the source match table has no reliable match date, linking is deliberately
fail-closed: exact calendar year + exact normalized player pair + exact Slam
identity must resolve to exactly one canonical BlinQ match. No fuzzy names,
cross-year matching, or inferred identities are allowed.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import norm_text
from tbt.models.feature_builder import FeatureBuilder


SLAM_TOKENS = {
    "ausopen": ("australian open",),
    "frenchopen": ("roland garros", "french open"),
    "wimbledon": ("wimbledon",),
    "usopen": ("us open", "usopen"),
}


def _quality(stats: dict) -> bool:
    return all(
        FeatureBuilder._extract_quality(stats or {}, side)[0] is not None
        and FeatureBuilder._extract_quality(stats or {}, side)[1] is not None
        for side in ("p1", "p2")
    )


def _signature(match) -> dict[str, str]:
    return {
        "tour": str(match.tour or "").lower(),
        "scheduled_date_utc": match.scheduled_at.date().isoformat(),
        "player1_id": str(match.player1_id),
        "player1_name": str(match.player1_name),
        "player2_id": str(match.player2_id),
        "player2_name": str(match.player2_name),
        "surface": str(match.surface or ""),
        "tournament": str(match.tournament or ""),
        "round_name": str(match.round_name or ""),
        "winner_id": str(match.winner_id or ""),
    }


def _source_pair(p1: object, p2: object) -> tuple[str, str]:
    return tuple(sorted((norm_text(str(p1 or "")), norm_text(str(p2 or "")))))


def _slam_key_from_name(name: str) -> str:
    lower = name.lower()
    for key in SLAM_TOKENS:
        if f"-{key}-" in lower or lower.endswith(f"-{key}-matches.csv"):
            return key
    return ""


def _canonical_is_slam(match, slam: str) -> bool:
    tournament = norm_text(match.tournament)
    return any(token in tournament for token in SLAM_TOKENS.get(slam, ()))


def _canonical_index(matches):
    index: dict[tuple[int, str, tuple[str, str]], list] = defaultdict(list)
    for match in matches:
        year = int(match.scheduled_at.year)
        pair = _source_pair(match.player1_name, match.player2_name)
        for slam in SLAM_TOKENS:
            if _canonical_is_slam(match, slam):
                index[(year, slam, pair)].append(match)
    return index


def _winner_name(match) -> str:
    wid = str(match.winner_id or "")
    if wid == str(match.player1_id):
        return norm_text(match.player1_name)
    if wid == str(match.player2_id):
        return norm_text(match.player2_name)
    return ""


def _aggregate_points(path: Path) -> tuple[dict[str, dict[int, Counter]], Counter]:
    by_match: dict[str, dict[int, Counter]] = defaultdict(
        lambda: {1: Counter(), 2: Counter()}
    )
    counts = Counter()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        required = {"match_id", "PointServer", "PointWinner"}
        if not required.issubset(fields):
            raise SystemExit(f"{path}: missing point columns {sorted(required-fields)}")
        for row in reader:
            counts["point_rows"] += 1
            mid = str(row.get("match_id") or "").strip()
            try:
                server = int(float(str(row.get("PointServer") or "")))
                winner = int(float(str(row.get("PointWinner") or "")))
            except ValueError:
                counts["invalid_point"] += 1
                continue
            if not mid or server not in (1, 2) or winner not in (1, 2):
                counts["invalid_point"] += 1
                continue
            receiver = 3 - server
            by_match[mid][server]["service_points"] += 1
            by_match[mid][receiver]["return_points"] += 1
            if winner == server:
                by_match[mid][server]["service_won"] += 1
            else:
                by_match[mid][receiver]["return_won"] += 1
            counts["usable_point"] += 1
    return by_match, counts


def _rates(side_counts: dict[int, Counter]) -> dict[int, dict[str, float]] | None:
    out = {}
    for side in (1, 2):
        service_points = int(side_counts[side]["service_points"])
        return_points = int(side_counts[side]["return_points"])
        if service_points <= 0 or return_points <= 0:
            return None
        out[side] = {
            "service_points_won": side_counts[side]["service_won"] / service_points,
            "return_points_won": side_counts[side]["return_won"] / return_points,
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--source-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    matches, safety = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical identity quarantine is non-empty")
    index = _canonical_index(matches)
    before = sum(1 for match in matches if _quality(dict(match.stats or {})))

    counts = Counter()
    file_counts = {}
    staged_by_match = {}
    review = []

    source_dir = Path(args.source_dir)
    match_files = [
        path for path in sorted(source_dir.glob("*-matches.csv"))
        if "-doubles" not in path.name and "-mixed" not in path.name
    ]
    if not match_files:
        raise SystemExit(f"No Grand Slam singles *-matches.csv files under {source_dir}")

    for matches_path in match_files:
        slam = _slam_key_from_name(matches_path.name)
        if not slam:
            counts["unknown_slam_file"] += 1
            continue
        points_path = matches_path.with_name(matches_path.name.replace("-matches.csv", "-points.csv"))
        if not points_path.is_file():
            counts["missing_points_pair"] += 1
            review.append({"source_file": matches_path.name, "reason": "missing_points_pair"})
            continue

        point_data, point_counts = _aggregate_points(points_path)
        local = Counter(point_counts)
        with matches_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or [])
            required = {"match_id", "year", "slam", "player1", "player2"}
            if not required.issubset(fields):
                raise SystemExit(f"{matches_path}: missing match columns {sorted(required-fields)}")

            for row_number, row in enumerate(reader, start=2):
                counts["source_match_rows"] += 1
                local["source_match_rows"] += 1
                source_mid = str(row.get("match_id") or "").strip()
                p1 = str(row.get("player1") or "").strip()
                p2 = str(row.get("player2") or "").strip()
                try:
                    year = int(float(str(row.get("year") or "")))
                except ValueError:
                    counts["source_identity_unusable"] += 1
                    local["source_identity_unusable"] += 1
                    continue
                if not source_mid or not p1 or not p2 or not (2011 <= year <= 2100):
                    counts["source_identity_unusable"] += 1
                    local["source_identity_unusable"] += 1
                    continue

                aggregated = point_data.get(source_mid)
                rates = _rates(aggregated) if aggregated is not None else None
                if rates is None:
                    counts["points_unusable_for_match"] += 1
                    local["points_unusable_for_match"] += 1
                    continue

                key = (year, slam, _source_pair(p1, p2))
                candidates = list(index.get(key, []))
                if len(candidates) != 1:
                    reason = "unmatched" if not candidates else "ambiguous"
                    counts[reason] += 1
                    local[reason] += 1
                    if candidates:
                        review.append({
                            "source_file": matches_path.name,
                            "source_row": row_number,
                            "source_match_id": source_mid,
                            "reason": reason,
                            "candidate_match_ids": [str(m.match_id) for m in candidates],
                        })
                    continue

                match = candidates[0]
                mp1 = norm_text(match.player1_name)
                mp2 = norm_text(match.player2_name)
                sp1 = norm_text(p1)
                sp2 = norm_text(p2)
                if sp1 == mp1 and sp2 == mp2:
                    mapping = ((1, "p1"), (2, "p2"))
                elif sp1 == mp2 and sp2 == mp1:
                    mapping = ((1, "p2"), (2, "p1"))
                else:
                    counts["orientation_failed"] += 1
                    local["orientation_failed"] += 1
                    continue

                source_winner = norm_text(str(row.get("winner") or ""))
                canonical_winner = _winner_name(match)
                if source_winner and canonical_winner and source_winner != canonical_winner:
                    counts["winner_mismatch"] += 1
                    local["winner_mismatch"] += 1
                    review.append({
                        "source_file": matches_path.name,
                        "source_row": row_number,
                        "source_match_id": source_mid,
                        "match_id": str(match.match_id),
                        "reason": "winner_mismatch",
                    })
                    continue

                incoming = {}
                for source_side, prefix in mapping:
                    incoming[f"{prefix}_service_points_won"] = rates[source_side]["service_points_won"]
                    incoming[f"{prefix}_return_points_won"] = rates[source_side]["return_points_won"]

                existing = dict(match.stats or {})
                if _quality(existing):
                    counts["already_quality_ready"] += 1
                    local["already_quality_ready"] += 1
                    continue

                conflicts = [
                    name for name, value in incoming.items()
                    if existing.get(name) is not None
                    and abs(float(existing[name]) - float(value)) > 0.02
                ]
                if conflicts:
                    counts["stat_conflict_matches"] += 1
                    local["stat_conflict_matches"] += 1
                    review.append({
                        "source_file": matches_path.name,
                        "source_row": row_number,
                        "source_match_id": source_mid,
                        "match_id": str(match.match_id),
                        "reason": "stat_conflicts",
                        "keys": conflicts,
                    })
                    continue

                clean = {
                    name: value for name, value in incoming.items()
                    if existing.get(name) is None
                }
                if not clean:
                    counts["already_present"] += 1
                    local["already_present"] += 1
                    continue
                projected = dict(existing)
                projected.update(clean)
                if not _quality(projected):
                    counts["partial_only_no_quality_gain"] += 1
                    local["partial_only_no_quality_gain"] += 1
                    continue

                match_id = str(match.match_id)
                stage = {
                    "schema": 1,
                    "match_id": match_id,
                    "canonical": _signature(match),
                    "incoming_stats": clean,
                    "provenance": [{
                        "source": "jeff_sackmann_tennis_slam_pointbypoint",
                        "source_file": matches_path.name,
                        "source_match_id": source_mid,
                        "evidence": [
                            "calendar_year_exact",
                            "grand_slam_identity_exact",
                            "player_pair_exact",
                            "canonical_candidate_unique",
                            "point_server_and_winner_explicit",
                        ],
                    }],
                    "import_ready": True,
                }
                previous = staged_by_match.get(match_id)
                if previous is not None:
                    if previous["incoming_stats"] == stage["incoming_stats"]:
                        counts["source_duplicate_same"] += 1
                    else:
                        counts["source_duplicate_conflict"] += 1
                        staged_by_match.pop(match_id, None)
                        review.append({
                            "source_file": matches_path.name,
                            "source_match_id": source_mid,
                            "match_id": match_id,
                            "reason": "source_duplicate_conflict",
                        })
                    continue

                staged_by_match[match_id] = stage
                counts["staged_matches"] += 1
                local["staged_matches"] += 1

        for name, value in local.items():
            counts[f"points_{name}"] += value if name in {"point_rows", "usable_point", "invalid_point"} else 0
        file_counts[matches_path.name] = dict(local)

    staged = list(staged_by_match.values())
    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "quality_ready_before": before,
        "quality_ready_projected_after": before + len(staged),
        "quality_ready_projected_added": len(staged),
        "counts": dict(counts),
        "file_counts": file_counts,
        "production_mutated": False,
        "api_requests": 0,
        "source_policy": "Pinned Jeff Sackmann Grand Slam point-by-point archive; CC BY-NC-SA 4.0; private research integration.",
        "link_policy": (
            "exact year + exact Grand Slam identity + exact normalized player pair; "
            "canonical candidate must be unique; no fuzzy or cross-year matching"
        ),
    }
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name, rows in (("auto_linked.jsonl", staged), ("review.jsonl", review)):
        with (out / name).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
