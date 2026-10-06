"""Audit and stage Jeff Sackmann tennis_pointbypoint serve/return enrichment.

Source format: legacy tennis_pointbypoint single-row PBP CSVs (ATP/WTA/
Challenger/Futures/ITF, main draw and qualifying). The PBP string records point
outcomes relative to the current server and service changes in tiebreaks.

This script is read-only against canonical history. It derives only
service_points_won and return_points_won and emits the strict offline
serve-return stage schema.

Link policy: exact calendar date + exact normalized player pair. The canonical
candidate must be unique; exact tournament and winner are used only to
disambiguate duplicate same-day pair candidates. No fuzzy player/date matching.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.offline_odds import norm_text
from tbt.models.feature_builder import FeatureBuilder


def _quality(stats: dict) -> bool:
    for side in ("p1", "p2"):
        serve, ret = FeatureBuilder._extract_quality(stats or {}, side)
        if serve is None or ret is None:
            return False
    return True


def _signature(match):
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


def _field(row: dict, names: tuple[str, ...]):
    for name in names:
        if name in row and str(row.get(name) or "").strip():
            return row.get(name)
    return None


def _parse_date(value: object):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %y", "%d %b %Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _winner_side(value: object, *, zero_based: bool = False) -> int | None:
    text = str(value or "").strip()
    try:
        side = int(float(text))
    except (TypeError, ValueError):
        return None
    if zero_based:
        return side + 1 if side in (0, 1) else None
    return side if side in (1, 2) else None


def _source_tour(row: dict, path: Path) -> str:
    label = norm_text(row.get("tour"))
    if label in {"atp", "challenger", "itf men", "davis cup", "boys"}:
        return "atp"
    if label in {"wta", "wta 125k", "itf women", "federation cup", "girls"}:
        return "wta"
    name = path.name.lower()
    if "atp" in name:
        return "atp"
    if "wta" in name:
        return "wta"
    return ""


def _source_files(source: Path) -> list[Path]:
    files = set(source.glob("pbp_matches_*.csv"))
    # TennisVisuals validated corpus: prefer all singles files. The richer pbpx
    # files overlap a subset of pbp rows; duplicate-identical staging is handled
    # below and never double-writes canonical matches.
    files.update(source.glob("*_Singles_pbp.csv"))
    files.update(source.glob("*_Singles_pbpx.csv"))
    return sorted(files)


def _winner_name(match) -> str:
    wid = str(match.winner_id or "")
    if wid and wid == str(match.player1_id):
        return norm_text(match.player1_name)
    if wid and wid == str(match.player2_id):
        return norm_text(match.player2_name)
    return ""


def _parse_pbp(value: object):
    """Return side-relative service/return rates from one validated PBP string.

    server1 is side 1 and serves the first game. S/A mean current server won,
    R/D mean current receiver won. ';' and '.' end a game. '/' changes server
    inside a tiebreak. At the next game boundary service order is based on the
    player who started the game, not whoever served the final tiebreak point.
    """
    text = str(value or "").strip()
    if not text:
        return None

    sides = {
        1: {"service_points": 0, "service_won": 0, "return_points": 0, "return_won": 0},
        2: {"service_points": 0, "service_won": 0, "return_points": 0, "return_won": 0},
    }
    game_server = 1
    current_server = 1
    game_has_points = False
    valid_points = 0

    for raw in text:
        if raw.isspace():
            continue
        ch = raw.upper()
        if ch in {"S", "R", "A", "D"}:
            receiver = 3 - current_server
            sides[current_server]["service_points"] += 1
            sides[receiver]["return_points"] += 1
            if ch in {"S", "A"}:
                sides[current_server]["service_won"] += 1
            else:
                sides[receiver]["return_won"] += 1
            game_has_points = True
            valid_points += 1
            continue

        if ch == "/":
            if not game_has_points:
                return None
            current_server = 3 - current_server
            continue

        if ch in {";", "."}:
            if game_has_points:
                game_server = 3 - game_server
                current_server = game_server
                game_has_points = False
            continue

        return None

    if valid_points <= 0:
        return None
    if any(
        sides[side]["service_points"] <= 0 or sides[side]["return_points"] <= 0
        for side in (1, 2)
    ):
        return None

    return {
        1: {
            "service_points_won": sides[1]["service_won"] / sides[1]["service_points"],
            "return_points_won": sides[1]["return_won"] / sides[1]["return_points"],
        },
        2: {
            "service_points_won": sides[2]["service_won"] / sides[2]["service_points"],
            "return_points_won": sides[2]["return_won"] / sides[2]["return_points"],
        },
        "point_count": valid_points,
    }


def _resolve_candidate(candidates, source_tournament: str, source_winner: str):
    if len(candidates) <= 1:
        return candidates

    tournament = norm_text(source_tournament)
    if tournament:
        exact = [m for m in candidates if norm_text(m.tournament) == tournament]
        if len(exact) == 1:
            return exact
        if exact:
            candidates = exact

    if source_winner:
        winner = [m for m in candidates if _winner_name(m) == source_winner]
        if len(winner) == 1:
            return winner
        if winner:
            candidates = winner

    return candidates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--source-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    index = defaultdict(list)
    for match in matches:
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        index[(str(match.tour or "").lower(), match.scheduled_at.date().isoformat(), pair)].append(match)

    before = sum(1 for match in matches if _quality(dict(match.stats or {})))
    counts = Counter()
    file_counts = {}
    staged_by_match = {}
    review = []

    source = Path(args.source_dir)
    files = _source_files(source)
    counts["source_files"] = len(files)
    if not files:
        raise SystemExit(f"No tennis_pointbypoint CSV files found under {source}")

    for path in files:
        local = Counter()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or [])
            required_groups = (
                ("date",),
                ("server1",),
                ("server2",),
                ("pbp",),
            )
            tennisvisuals_format = {"type", "tour", "draw"}.issubset(fields)
            if any(not any(name in fields for name in group) for group in required_groups):
                raise SystemExit(f"{path}: unexpected fields={sorted(fields)}")

            for row_number, row in enumerate(reader, start=2):
                counts["source_match_rows"] += 1
                local["source_match_rows"] += 1

                source_date = _parse_date(_field(row, ("date", "match_date")))
                server1 = str(_field(row, ("server1", "player1")) or "").strip()
                server2 = str(_field(row, ("server2", "player2")) or "").strip()
                tournament = str(_field(row, ("tny_name", "tournament", "tournament_name")) or "").strip()
                winner_side = _winner_side(
                    _field(row, ("winner",)),
                    zero_based=tennisvisuals_format,
                )
                winner_name = ""
                if winner_side == 1:
                    winner_name = norm_text(server1)
                elif winner_side == 2:
                    winner_name = norm_text(server2)

                if source_date is None or not server1 or not server2:
                    counts["source_identity_unusable"] += 1
                    local["source_identity_unusable"] += 1
                    continue

                parsed = _parse_pbp(_field(row, ("pbp", "points")))
                if parsed is None:
                    counts["pbp_unusable"] += 1
                    local["pbp_unusable"] += 1
                    continue
                counts["pbp_usable"] += 1
                local["pbp_usable"] += 1
                counts["point_rows_derived"] += int(parsed["point_count"])

                pair = tuple(sorted((norm_text(server1), norm_text(server2))))
                source_tour = _source_tour(row, path)
                if not source_tour:
                    counts["source_tour_unusable"] += 1
                    local["source_tour_unusable"] += 1
                    continue
                key = (source_tour, source_date.isoformat(), pair)
                candidates = _resolve_candidate(list(index.get(key, [])), tournament, winner_name)
                if len(candidates) != 1:
                    reason = "unmatched" if not candidates else "ambiguous"
                    counts[reason] += 1
                    local[reason] += 1
                    if candidates:
                        review.append({
                            "source_file": path.name,
                            "source_row": row_number,
                            "reason": reason,
                            "candidate_match_ids": [str(m.match_id) for m in candidates],
                        })
                    continue

                match = candidates[0]
                mp1 = norm_text(match.player1_name)
                mp2 = norm_text(match.player2_name)
                if norm_text(server1) == mp1 and norm_text(server2) == mp2:
                    mapping = ((1, "p1"), (2, "p2"))
                elif norm_text(server1) == mp2 and norm_text(server2) == mp1:
                    mapping = ((1, "p2"), (2, "p1"))
                else:
                    counts["orientation_failed"] += 1
                    local["orientation_failed"] += 1
                    continue

                if winner_name and _winner_name(match) and winner_name != _winner_name(match):
                    counts["winner_mismatch"] += 1
                    local["winner_mismatch"] += 1
                    review.append({
                        "source_file": path.name,
                        "source_row": row_number,
                        "reason": "winner_mismatch",
                        "match_id": str(match.match_id),
                    })
                    continue

                incoming = {}
                for source_side, prefix in mapping:
                    incoming[f"{prefix}_service_points_won"] = parsed[source_side]["service_points_won"]
                    incoming[f"{prefix}_return_points_won"] = parsed[source_side]["return_points_won"]

                existing = dict(match.stats or {})
                if _quality(existing):
                    counts["already_quality_ready"] += 1
                    local["already_quality_ready"] += 1
                    continue

                conflicts = [
                    key_name
                    for key_name, value in incoming.items()
                    if existing.get(key_name) is not None
                    and abs(float(existing[key_name]) - float(value)) > 0.02
                ]
                if conflicts:
                    counts["stat_conflict_matches"] += 1
                    local["stat_conflict_matches"] += 1
                    review.append({
                        "source_file": path.name,
                        "source_row": row_number,
                        "reason": "stat_conflicts",
                        "match_id": str(match.match_id),
                        "keys": conflicts,
                    })
                    continue

                clean = {key_name: value for key_name, value in incoming.items() if existing.get(key_name) is None}
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
                        "source": (
                            "tennisvisuals_validated_pointbypoint"
                            if tennisvisuals_format
                            else "jeff_sackmann_tennis_pointbypoint"
                        ),
                        "source_file": path.name,
                        "source_row": row_number,
                        "evidence": [
                            "calendar_date_exact",
                            "player_pair_exact",
                            "canonical_candidate_unique",
                            "explicit_pbp_server_relative_outcomes",
                        ],
                    }],
                    "import_ready": True,
                }

                previous = staged_by_match.get(match_id)
                if previous is not None:
                    if previous["incoming_stats"] == stage["incoming_stats"]:
                        counts["source_duplicate_same"] += 1
                        local["source_duplicate_same"] += 1
                    else:
                        counts["source_duplicate_conflict"] += 1
                        local["source_duplicate_conflict"] += 1
                        review.append({
                            "source_file": path.name,
                            "source_row": row_number,
                            "reason": "source_duplicate_conflict",
                            "match_id": match_id,
                        })
                        staged_by_match.pop(match_id, None)
                    continue

                staged_by_match[match_id] = stage
                counts["staged_matches"] += 1
                local["staged_matches"] += 1

        file_counts[path.name] = dict(local)

    staged = list(staged_by_match.values())
    projected_added = len(staged)
    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "quality_ready_before": before,
        "quality_ready_projected_after": before + projected_added,
        "quality_ready_projected_added": projected_added,
        "counts": dict(counts),
        "file_counts": file_counts,
        "production_mutated": False,
        "api_requests": 0,
        "source_policy": (
            "Legacy Jeff Sackmann tennis_pointbypoint plus the operator-supplied TennisVisuals "
            "validated single-row PBP corpus. Only derived service/return rates are staged; "
            "raw point tapes are not redistributed by this workflow."
        ),
        "link_policy": (
            "exact calendar date + exact normalized player pair; canonical candidate must be unique; "
            "exact tournament/winner may only disambiguate same-day duplicate candidates"
        ),
    }

    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for name, rows in (("auto_linked.jsonl", staged), ("review.jsonl", review)):
        with (out / name).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
