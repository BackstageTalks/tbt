"""Fail-closed linker for the Tennis Abstract-style all_matches.csv export.

The source is player-perspective: a normal singles match is represented twice,
once per player. This linker requires the reciprocal pair before attempting any
canonical match. It never mutates canonical history and never calls a provider.

Identity policy:
- singles only;
- exact normalized player pair derived from stable player_id slugs;
- canonical match date must fall inside source tournament start/end window;
- winner, surface and round must agree;
- tournament must have exact or strong token agreement;
- the top canonical candidate must be unique.

Output is schema-compatible with import_offline_linked_serve_return.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from link_offline_serve_return import _norm_name, _norm_surface, _norm_text, _quality_ready
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities


SUPPORTED_FIELDS = {
    "aces",
    "double_faults",
    "first_serve_win",
    "second_serve_win",
    "service_points_won",
    "return_points_won",
}

ROUND_ALIASES = {
    "final": "f",
    "finals": "f",
    "semi final": "sf",
    "semi finals": "sf",
    "semifinal": "sf",
    "semifinals": "sf",
    "quarter final": "qf",
    "quarter finals": "qf",
    "quarterfinal": "qf",
    "quarterfinals": "qf",
    "round of 16": "r16",
    "round of 32": "r32",
    "round of 64": "r64",
    "round of 128": "r128",
    "1st round qualifying": "q1",
    "2nd round qualifying": "q2",
    "3rd round qualifying": "q3",
    "first round qualifying": "q1",
    "second round qualifying": "q2",
    "third round qualifying": "q3",
    "round robin": "rr",
}


def _bool(value: object) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"t", "true", "1", "yes", "y"}:
        return True
    if text in {"f", "false", "0", "no", "n"}:
        return False
    return None


def _num(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: object) -> float | None:
    number = _num(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return float(number)


def _rate(numerator: object, denominator: object) -> float | None:
    num, den = _num(numerator), _num(denominator)
    if num is None or den is None or den <= 0 or num < 0 or num > den:
        return None
    return num / den


def _day(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _slug_name(value: object) -> str:
    return _norm_name(str(value or "").replace("-", " "))


def _round(value: object) -> str:
    text = _norm_text(value)
    return ROUND_ALIASES.get(text, text)


GENERIC_TOURNAMENT_TOKENS = {
    "atp", "wta", "itf", "tennis", "open", "championship", "championships",
    "challenger", "international", "presented", "by", "the", "cup",
}


def _tournament_score(source: str, canonical: str) -> tuple[int, str]:
    left, right = _norm_text(source), _norm_text(canonical)
    if not left or not right:
        return 0, "tournament_missing"
    if left == right:
        return 2, "tournament_exact"

    def tokens(value: str) -> set[str]:
        return {token for token in value.split() if token not in GENERIC_TOURNAMENT_TOKENS}

    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0, "tournament_mismatch"
    overlap = len(a & b) / max(1, min(len(a), len(b)))
    if overlap >= 0.75:
        return 1, "tournament_tokens"
    return 0, "tournament_mismatch"


def _perspective_stats(row: dict[str, str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for field, column in (("aces", "aces"), ("double_faults", "double_faults")):
        value = _integer(row.get(column))
        if value is not None:
            result[field] = value

    for field, numerator, denominator in (
        ("first_serve_win", "first_serve_points_made", "first_serve_points_attempted"),
        ("second_serve_win", "second_serve_points_made", "second_serve_points_attempted"),
        ("service_points_won", "service_points_won", "service_points_attempted"),
        ("return_points_won", "return_points_won", "return_points_attempted"),
    ):
        value = _rate(row.get(numerator), row.get(denominator))
        if value is not None:
            result[field] = value
    return result


@dataclass(frozen=True)
class Perspective:
    line_number: int
    start_date: date
    end_date: date
    player: str
    opponent: str
    tournament: str
    surface: str
    round_name: str
    victory: bool
    retirement: bool
    stats: dict[str, float]
    service_points_attempted: int | None
    return_points_attempted: int | None
    service_points_won_count: int | None
    return_points_won_count: int | None
    games_won: int | None
    games_against: int | None
    sets_won: int | None

    @property
    def pair(self) -> tuple[str, str]:
        return tuple(sorted((self.player, self.opponent)))

    @property
    def group_key(self) -> tuple:
        return (
            self.start_date,
            self.end_date,
            _norm_text(self.tournament),
            self.round_name,
            self.pair,
        )


@dataclass(frozen=True)
class SourceMatch:
    source_match_id: str
    start_date: date
    end_date: date
    player_a: str
    player_b: str
    winner: str
    tournament: str
    surface: str
    round_name: str
    stats_a: dict[str, float]
    stats_b: dict[str, float]

    @property
    def pair(self) -> tuple[str, str]:
        return tuple(sorted((self.player_a, self.player_b)))


def _int_or_none(value: object) -> int | None:
    number = _num(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _read_source(path: Path) -> tuple[list[SourceMatch], Counter, list[dict]]:
    counts = Counter()
    grouped: dict[tuple, list[Perspective]] = defaultdict(list)
    quarantine: list[dict] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            counts["raw_rows"] += 1
            if _bool(row.get("doubles")) is True:
                counts["doubles_rows"] += 1
                continue

            player = _slug_name(row.get("player_id"))
            opponent = _slug_name(row.get("opponent_id"))
            if not player or not opponent or player == opponent:
                counts["invalid_identity_rows"] += 1
                continue
            if "_" in str(row.get("player_id") or "") or "_" in str(row.get("opponent_id") or ""):
                counts["pair_identity_rows"] += 1
                continue

            start, end = _day(row.get("start_date")), _day(row.get("end_date"))
            if not start or not end or end < start or (end - start).days > 21:
                counts["invalid_window_rows"] += 1
                continue

            victory = _bool(row.get("player_victory"))
            if victory is None:
                counts["invalid_winner_rows"] += 1
                continue

            stats = _perspective_stats(row)
            if not stats:
                counts["no_supported_stats_rows"] += 1
                continue

            perspective = Perspective(
                line_number=line_number,
                start_date=start,
                end_date=end,
                player=player,
                opponent=opponent,
                tournament=str(row.get("tournament") or ""),
                surface=_norm_surface(row.get("court_surface")),
                round_name=_round(row.get("round")),
                victory=victory,
                retirement=_bool(row.get("retirement")) is True,
                stats=stats,
                service_points_attempted=_int_or_none(row.get("service_points_attempted")),
                return_points_attempted=_int_or_none(row.get("return_points_attempted")),
                service_points_won_count=_int_or_none(row.get("service_points_won")),
                return_points_won_count=_int_or_none(row.get("return_points_won")),
                games_won=_int_or_none(row.get("games_won")),
                games_against=_int_or_none(row.get("games_against")),
                sets_won=_int_or_none(row.get("sets_won")),
            )
            grouped[perspective.group_key].append(perspective)
            counts["eligible_perspective_rows"] += 1

    source_matches: list[SourceMatch] = []
    for key, rows in grouped.items():
        if len(rows) != 2:
            counts["non_reciprocal_groups"] += 1
            quarantine.append({
                "reason": "non_reciprocal_group",
                "source_lines": [row.line_number for row in rows],
                "group_size": len(rows),
            })
            continue
        a, b = rows
        if a.player != b.opponent or a.opponent != b.player:
            counts["reciprocity_conflicts"] += 1
            quarantine.append({
                "reason": "reciprocity_conflict",
                "source_lines": [a.line_number, b.line_number],
            })
            continue
        if a.victory == b.victory:
            counts["winner_pair_conflicts"] += 1
            quarantine.append({
                "reason": "winner_pair_conflict",
                "source_lines": [a.line_number, b.line_number],
            })
            continue
        if a.surface != b.surface or a.round_name != b.round_name:
            counts["metadata_pair_conflicts"] += 1
            quarantine.append({
                "reason": "metadata_pair_conflict",
                "source_lines": [a.line_number, b.line_number],
            })
            continue

        consistency_errors = []
        if a.service_points_attempted is not None and b.return_points_attempted is not None:
            if a.service_points_attempted != b.return_points_attempted:
                consistency_errors.append("a_service_vs_b_return_attempts")
        if b.service_points_attempted is not None and a.return_points_attempted is not None:
            if b.service_points_attempted != a.return_points_attempted:
                consistency_errors.append("b_service_vs_a_return_attempts")
        if a.games_won is not None and b.games_against is not None and a.games_won != b.games_against:
            consistency_errors.append("a_games_won_vs_b_against")
        if b.games_won is not None and a.games_against is not None and b.games_won != a.games_against:
            consistency_errors.append("b_games_won_vs_a_against")
        if consistency_errors:
            counts["perspective_consistency_conflicts"] += 1
            quarantine.append({
                "reason": "perspective_consistency_conflict",
                "source_lines": [a.line_number, b.line_number],
                "checks": consistency_errors,
            })
            continue

        winner = a.player if a.victory else b.player
        source_id = "|".join([
            a.start_date.isoformat(),
            a.end_date.isoformat(),
            _norm_text(a.tournament),
            a.round_name,
            a.pair[0],
            a.pair[1],
        ])
        source_matches.append(SourceMatch(
            source_match_id=source_id,
            start_date=a.start_date,
            end_date=a.end_date,
            player_a=a.player,
            player_b=a.opponent,
            winner=winner,
            tournament=a.tournament,
            surface=a.surface,
            round_name=a.round_name,
            stats_a=a.stats,
            stats_b=b.stats,
        ))
        counts["paired_source_matches"] += 1

    return source_matches, counts, quarantine


def _canonical_winner_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return _norm_name(match.player1_name)
    if str(match.winner_id or "") == str(match.player2_id):
        return _norm_name(match.player2_name)
    return ""


def _score(source: SourceMatch, match) -> tuple[int, list[str], bool]:
    evidence: list[str] = []
    canonical_pair = tuple(sorted((_norm_name(match.player1_name), _norm_name(match.player2_name))))
    if source.pair != canonical_pair:
        return -100, ["pair_mismatch"], False

    day = match.scheduled_at.date()
    if not source.start_date <= day <= source.end_date:
        return -100, ["outside_tournament_window"], False
    score = 3
    evidence.append("date_in_tournament_window")

    canonical_surface = _norm_surface(match.surface)
    if source.surface not in {"", "unknown"} and canonical_surface not in {"", "unknown"}:
        if source.surface != canonical_surface:
            return score, evidence + ["surface_conflict"], False
        score += 1
        evidence.append("surface")

    tournament_points, tournament_evidence = _tournament_score(source.tournament, match.tournament)
    evidence.append(tournament_evidence)
    if tournament_points <= 0:
        return score, evidence, False
    score += tournament_points

    source_round, canonical_round = source.round_name, _round(match.round_name)
    if source_round and canonical_round:
        if source_round != canonical_round:
            return score, evidence + ["round_conflict"], False
        score += 2
        evidence.append("round")
    else:
        return score, evidence + ["round_missing"], False

    canonical_winner = _canonical_winner_name(match)
    if not canonical_winner:
        return score, evidence + ["canonical_winner_missing"], False
    if source.winner != canonical_winner:
        return score, evidence + ["winner_conflict"], False
    score += 3
    evidence.append("winner")

    accepted = (
        "surface" in evidence
        and "round" in evidence
        and "winner" in evidence
        and tournament_points > 0
        and score >= 10
    )
    return score, evidence, accepted


def _orientation(source: SourceMatch, match) -> dict[str, float] | None:
    p1, p2 = _norm_name(match.player1_name), _norm_name(match.player2_name)
    if source.player_a == p1 and source.player_b == p2:
        sides = (("p1", source.stats_a), ("p2", source.stats_b))
    elif source.player_a == p2 and source.player_b == p1:
        sides = (("p2", source.stats_a), ("p1", source.stats_b))
    else:
        return None
    incoming: dict[str, float] = {}
    for prefix, stats in sides:
        for field, value in stats.items():
            if field in SUPPORTED_FIELDS:
                incoming[f"{prefix}_{field}"] = float(value)
    return incoming


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--all-matches-csv", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history has identity quarantine; refusing all_matches linking")

    sources, source_counts, source_quarantine = _read_source(Path(args.all_matches_csv))
    by_pair: dict[tuple[str, str], list] = defaultdict(list)
    by_id = {str(match.match_id): match for match in matches}
    for match in matches:
        pair = tuple(sorted((_norm_name(match.player1_name), _norm_name(match.player2_name))))
        by_pair[pair].append(match)

    counts = Counter(source_counts)
    linked: dict[str, list[dict]] = defaultdict(list)
    review: list[dict] = []

    for source in sources:
        scored = []
        for match in by_pair.get(source.pair, []):
            score, evidence, accepted = _score(source, match)
            if score > -100:
                scored.append((score, accepted, match, evidence))
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
                "reason": "ambiguous",
                "candidate_match_ids": [str(item[2].match_id) for item in top],
                "score": top_score,
            })
            continue

        score, accepted, match, evidence = top[0]
        if not accepted:
            counts["weak_evidence"] += 1
            review.append({
                "source_match_id": source.source_match_id,
                "reason": "weak_evidence",
                "candidate_match_id": str(match.match_id),
                "score": score,
                "evidence": evidence,
            })
            continue

        incoming = _orientation(source, match)
        if not incoming:
            counts["orientation_unverified"] += 1
            continue
        counts["identity_linked"] += 1
        linked[str(match.match_id)].append({
            "source": f"all_matches:{Path(args.all_matches_csv).name}",
            "source_match_id": source.source_match_id,
            "score": score,
            "evidence": evidence,
            "stats": incoming,
        })

    staged: list[dict] = []
    quarantine = list(source_quarantine)
    staged_field_counts = Counter()
    quality_before = sum(1 for match in matches if _quality_ready(match.stats or {}))
    projected_quality = quality_before

    for mid, rows in linked.items():
        match = by_id[mid]
        existing = dict(match.stats or {})
        merged: dict[str, float] = {}
        conflicts = []
        provenance = []

        for row in rows:
            provenance.append({key: row[key] for key in ("source", "source_match_id", "score", "evidence")})
            for key, value in row["stats"].items():
                old, prior = existing.get(key), merged.get(key)
                if old is not None and abs(float(old) - float(value)) > 1e-6:
                    conflicts.append({"key": key, "reason": "canonical_conflict", "existing": old, "incoming": value})
                elif prior is not None and abs(float(prior) - float(value)) > 1e-6:
                    conflicts.append({"key": key, "reason": "source_conflict", "existing": prior, "incoming": value})
                elif old is None:
                    merged[key] = float(value)

        if conflicts:
            counts["stat_conflict_matches"] += 1
            quarantine.append({"match_id": mid, "reason": "stat_conflict", "conflicts": conflicts, "sources": provenance})
            continue
        if not merged:
            counts["already_present"] += 1
            continue

        projected = dict(existing)
        projected.update(merged)
        was_ready = _quality_ready(existing)
        is_ready = _quality_ready(projected)
        if is_ready and not was_ready:
            projected_quality += 1

        staged_field_counts.update(merged)
        staged.append({
            "schema": 1,
            "match_id": mid,
            "canonical": _signature(match),
            "incoming_stats": merged,
            "sources": provenance,
            "quality_ready_before": was_ready,
            "quality_ready_after": is_ready,
            "import_ready": True,
        })
        counts["staged_matches"] += 1

    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "raw_source_rows": int(counts.get("raw_rows", 0)),
        "paired_source_matches": int(counts.get("paired_source_matches", 0)),
        "counts": dict(counts),
        "staged_field_counts": dict(sorted(staged_field_counts.items())),
        "quality_ready_before": quality_before,
        "quality_ready_projected_after": projected_quality,
        "quality_ready_projected_added": projected_quality - quality_before,
        "production_mutated": False,
        "api_requests": 0,
        "identity_policy": "exact_pair+tournament_window+tournament+surface+round+winner+unique_candidate",
        "note": "Read-only all_matches linker. No canonical history write and no provider call occurred.",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, rows in (
        ("auto_linked.jsonl", staged),
        ("review.jsonl", review),
        ("quarantine.jsonl", quarantine),
    ):
        with (out / name).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
