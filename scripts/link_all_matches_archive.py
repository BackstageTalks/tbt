"""Fail-closed linker for the large player-perspective all_matches.csv archive.

The source stores one row per player perspective, and start_date/end_date describe
the tournament window rather than the exact match day.  This linker therefore
pairs reciprocal rows first, keeps only complete singles statistics, and links
against canonical history only when identity is corroborated by:
  * exact normalized player pair from source player_id/opponent_id slugs,
  * canonical match date inside the source tournament window,
  * winner agreement,
  * surface agreement,
  * round agreement,
  * tournament exact/token agreement.

Ambiguous, incomplete, retired, doubles, junior/level-0, conflicting and
non-reciprocal rows fail closed.  Output uses the same strict stage schema as
import_offline_linked_serve_return.py.  No provider API is called and canonical
history is never written by this script.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.models.feature_builder import FeatureBuilder


def _ascii(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _norm_text(value: object) -> str:
    text = _ascii(value).lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _norm_surface(value: object) -> str:
    text = _norm_text(value)
    if "clay" in text:
        return "clay"
    if "grass" in text:
        return "grass"
    if "hard" in text:
        return "hard"
    if "carpet" in text:
        return "carpet"
    return text or "unknown"


ROUND_ALIASES = {
    "final": "f",
    "finals": "f",
    "semi finals": "sf",
    "semi final": "sf",
    "semifinals": "sf",
    "semifinal": "sf",
    "quarter finals": "qf",
    "quarter final": "qf",
    "quarterfinals": "qf",
    "quarterfinal": "qf",
    "round of 16": "r16",
    "round of 32": "r32",
    "round of 64": "r64",
    "round of 128": "r128",
    "1st round qualifying": "q1",
    "first round qualifying": "q1",
    "2nd round qualifying": "q2",
    "second round qualifying": "q2",
    "3rd round qualifying": "q3",
    "third round qualifying": "q3",
    "round robin": "rr",
    "f": "f",
    "sf": "sf",
    "qf": "qf",
    "r16": "r16",
    "r32": "r32",
    "r64": "r64",
    "r128": "r128",
    "q1": "q1",
    "q2": "q2",
    "q3": "q3",
    "rr": "rr",
}


def _norm_round(value: object) -> str:
    text = _norm_text(value)
    return ROUND_ALIASES.get(text, text)


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _num(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rate(num: object, den: object) -> float | None:
    n, d = _num(num), _num(den)
    if n is None or d is None or d <= 0 or n < 0 or n > d:
        return None
    return n / d


def _flag(value: object) -> bool:
    return str(value or "").strip().lower() in {"t", "true", "1", "yes"}


def _slug_name(value: object) -> str:
    return _norm_text(value)


def _tournament_score(a: str, b: str) -> tuple[int, str]:
    na, nb = _norm_text(a), _norm_text(b)
    if not na or not nb:
        return 0, "tournament_missing"
    if na == nb:
        return 2, "tournament_exact"
    ta, tb = set(na.split()), set(nb.split())
    overlap = len(ta & tb) / max(1, len(ta | tb))
    if overlap >= 0.6:
        return 1, "tournament_tokens"
    return 0, "tournament_mismatch"


def _canonical_winner_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return _norm_text(match.player1_name)
    if str(match.winner_id or "") == str(match.player2_id):
        return _norm_text(match.player2_name)
    return ""


def _row_stats(row: dict[str, str]) -> dict[str, float] | None:
    required = (
        "aces",
        "double_faults",
        "first_serve_points_made",
        "first_serve_points_attempted",
        "second_serve_points_made",
        "second_serve_points_attempted",
        "service_points_won",
        "service_points_attempted",
        "return_points_won",
        "return_points_attempted",
    )
    values = {key: _num(row.get(key)) for key in required}
    if any(values[key] is None for key in required):
        return None
    aces, dfs = values["aces"], values["double_faults"]
    if (
        aces is None
        or dfs is None
        or aces < 0
        or dfs < 0
        or not aces.is_integer()
        or not dfs.is_integer()
    ):
        return None
    first = _rate(values["first_serve_points_made"], values["first_serve_points_attempted"])
    second = _rate(values["second_serve_points_made"], values["second_serve_points_attempted"])
    service = _rate(values["service_points_won"], values["service_points_attempted"])
    ret = _rate(values["return_points_won"], values["return_points_attempted"])
    if any(value is None for value in (first, second, service, ret)):
        return None
    return {
        "aces": float(aces),
        "double_faults": float(dfs),
        "first_serve_win": float(first),
        "second_serve_win": float(second),
        "service_points_won": float(service),
        "return_points_won": float(ret),
    }


@dataclass(frozen=True)
class Perspective:
    line: int
    start: date
    end: date
    player: str
    opponent: str
    tournament: str
    surface: str
    round_name: str
    winner: str
    stats: dict[str, float]

    @property
    def pair(self) -> tuple[str, str]:
        return tuple(sorted((self.player, self.opponent)))

    @property
    def key(self) -> tuple:
        return (
            self.start,
            self.end,
            _norm_text(self.tournament),
            self.round_name,
            self.pair,
        )


@dataclass(frozen=True)
class SourceMatch:
    source_match_id: str
    start: date
    end: date
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


def _perspectives(path: str, counts: Counter) -> dict[tuple, list[Perspective]]:
    grouped: dict[tuple, list[Perspective]] = defaultdict(list)
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            counts["raw_rows"] += 1
            if _flag(row.get("doubles")):
                counts["filtered_doubles"] += 1
                continue
            if _flag(row.get("retirement")):
                counts["filtered_retirement"] += 1
                continue
            level = _num(row.get("masters"))
            if level is None or level <= 0:
                counts["filtered_level_zero_or_missing"] += 1
                continue
            start, end = _parse_date(row.get("start_date")), _parse_date(row.get("end_date"))
            player, opponent = _slug_name(row.get("player_id")), _slug_name(row.get("opponent_id"))
            stats = _row_stats(row)
            if not start or not end or end < start or not player or not opponent or player == opponent:
                counts["filtered_invalid_identity_or_window"] += 1
                continue
            if stats is None:
                counts["filtered_incomplete_stats"] += 1
                continue
            winner = player if _flag(row.get("player_victory")) else opponent
            perspective = Perspective(
                line=line,
                start=start,
                end=end,
                player=player,
                opponent=opponent,
                tournament=str(row.get("tournament") or ""),
                surface=_norm_surface(row.get("court_surface")),
                round_name=_norm_round(row.get("round")),
                winner=winner,
                stats=stats,
            )
            grouped[perspective.key].append(perspective)
            counts["eligible_perspectives"] += 1
    return grouped


def _pair_sources(path: str, counts: Counter, quarantine: list[dict]) -> list[SourceMatch]:
    grouped = _perspectives(path, counts)
    sources: list[SourceMatch] = []
    for key, rows in grouped.items():
        if len(rows) != 2:
            counts["nonreciprocal_groups"] += 1
            quarantine.append({
                "reason": "nonreciprocal_group",
                "source_lines": [row.line for row in rows],
                "group_size": len(rows),
            })
            continue
        a, b = rows
        reciprocal = a.player == b.opponent and a.opponent == b.player
        consistent = (
            reciprocal
            and a.winner == b.winner
            and a.surface == b.surface
            and a.round_name == b.round_name
        )
        if not consistent:
            counts["reciprocal_conflicts"] += 1
            quarantine.append({
                "reason": "reciprocal_conflict",
                "source_lines": [a.line, b.line],
            })
            continue
        source_id = f"{a.start.isoformat()}:{_norm_text(a.tournament)}:{a.round_name}:{'|'.join(a.pair)}"
        sources.append(SourceMatch(
            source_match_id=source_id,
            start=a.start,
            end=a.end,
            player_a=a.player,
            player_b=b.player,
            winner=a.winner,
            tournament=a.tournament,
            surface=a.surface,
            round_name=a.round_name,
            stats_a=a.stats,
            stats_b=b.stats,
        ))
        counts["paired_source_matches"] += 1
    return sources


def _candidate(source: SourceMatch, match) -> tuple[int, list[str], bool]:
    evidence: list[str] = []
    pair = tuple(sorted((_norm_text(match.player1_name), _norm_text(match.player2_name))))
    if pair != source.pair:
        return -100, ["pair_mismatch"], False
    day = match.scheduled_at.astimezone(timezone.utc).date()
    if not source.start <= day <= source.end:
        return -100, ["outside_tournament_window"], False
    evidence.append("date_in_tournament_window")
    score = 2

    canonical_winner = _canonical_winner_name(match)
    if not canonical_winner:
        return score, evidence + ["canonical_winner_missing"], False
    if canonical_winner != source.winner:
        return score, evidence + ["winner_conflict"], False
    score += 3
    evidence.append("winner")

    canonical_surface = _norm_surface(match.surface)
    if source.surface not in ("", "unknown") and canonical_surface not in ("", "unknown"):
        if source.surface != canonical_surface:
            return score, evidence + ["surface_conflict"], False
        score += 1
        evidence.append("surface")

    cr = _norm_round(match.round_name)
    if source.round_name and cr:
        if source.round_name != cr:
            return score, evidence + ["round_conflict"], False
        score += 2
        evidence.append("round")

    ts, te = _tournament_score(source.tournament, match.tournament)
    score += ts
    evidence.append(te)

    accepted = (
        "winner" in evidence
        and "surface" in evidence
        and "round" in evidence
        and te in {"tournament_exact", "tournament_tokens"}
        and score >= 9
    )
    return score, evidence, accepted


def _orientation(source: SourceMatch, match) -> dict[str, float] | None:
    p1, p2 = _norm_text(match.player1_name), _norm_text(match.player2_name)
    if source.player_a == p1 and source.player_b == p2:
        sides = (("p1", source.stats_a), ("p2", source.stats_b))
    elif source.player_a == p2 and source.player_b == p1:
        sides = (("p2", source.stats_a), ("p1", source.stats_b))
    else:
        return None
    incoming: dict[str, float] = {}
    for prefix, stats in sides:
        for field, value in stats.items():
            incoming[f"{prefix}_{field}"] = float(value)
    return incoming


def _quality_ready(stats: dict[str, float | None]) -> bool:
    return all(
        FeatureBuilder._extract_quality(stats, prefix)[0] is not None
        and FeatureBuilder._extract_quality(stats, prefix)[1] is not None
        for prefix in ("p1", "p2")
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--source-csv", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history has identity quarantine; refusing archive linking")

    counts = Counter()
    quarantine: list[dict] = []
    sources = _pair_sources(args.source_csv, counts, quarantine)

    by_pair: dict[tuple[str, str], list] = defaultdict(list)
    by_id = {str(match.match_id): match for match in matches}
    for match in matches:
        pair = tuple(sorted((_norm_text(match.player1_name), _norm_text(match.player2_name))))
        by_pair[pair].append(match)

    linked: dict[str, list[dict]] = defaultdict(list)
    review: list[dict] = []

    for source in sources:
        scored = []
        for match in by_pair.get(source.pair, []):
            score, evidence, accepted = _candidate(source, match)
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
            "source": "all_matches_archive",
            "source_match_id": source.source_match_id,
            "score": score,
            "evidence": evidence,
            "stats": incoming,
        })

    staged = []
    staged_field_counts = Counter()
    quality_before = sum(1 for match in matches if _quality_ready(match.stats or {}))
    quality_after = quality_before

    for mid, rows in linked.items():
        match = by_id[mid]
        existing = dict(match.stats or {})
        merged: dict[str, float] = {}
        conflicts = []
        provenance = []
        for row in rows:
            provenance.append({k: row[k] for k in ("source", "source_match_id", "score", "evidence")})
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
        was_ready, is_ready = _quality_ready(existing), _quality_ready(projected)
        if is_ready and not was_ready:
            quality_after += 1
        staged_field_counts.update(merged.keys())
        staged.append({
            "schema": 1,
            "match_id": mid,
            "canonical": {
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
            },
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
        "source_file": Path(args.source_csv).name,
        "counts": dict(counts),
        "staged_field_counts": dict(sorted(staged_field_counts.items())),
        "quality_ready_before": quality_before,
        "quality_ready_projected_after": quality_after,
        "quality_ready_projected_added": quality_after - quality_before,
        "production_mutated": False,
        "api_requests": 0,
        "link_policy": "exact_slug_pair+tournament_window+winner+surface+round+tournament_v1",
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
