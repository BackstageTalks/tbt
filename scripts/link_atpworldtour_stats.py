"""Fail-closed linker for ATP World Tour score/stat archives.

The serve-and-volley archive exposes tournament windows, score identities and
match-stat rows in separate headerless CSVs.  Stats are first joined to scores
through the canonical stats URL key (year/tournament/match-code), then linked
against BlinQ history using exact player pair plus tournament window, winner,
surface, round and tournament evidence.

Output follows import_offline_linked_serve_return.py stage schema.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import legacy_name_matches, norm_surface, norm_text, tournament_score
from tbt.models.feature_builder import FeatureBuilder


SCORE_COLUMNS = [
    "tourney_year_id", "tourney_order", "tourney_name", "tourney_slug",
    "tourney_url_suffix", "start_date", "start_year", "start_month", "start_day",
    "end_date", "end_year", "end_month", "end_day", "currency", "prize_money",
    "match_index", "tourney_round_name", "round_order", "match_order",
    "winner_name", "winner_player_id", "winner_slug", "loser_name",
    "loser_player_id", "loser_slug", "winner_seed", "loser_seed",
    "match_score_tiebreaks", "winner_sets_won", "loser_sets_won",
    "winner_games_won", "loser_games_won", "winner_tiebreaks_won",
    "loser_tiebreaks_won", "match_id", "match_stats_url_suffix",
]

TOURNAMENT_COLUMNS = [
    "tourney_year_id", "tourney_order", "tourney_type", "tourney_name",
    "tourney_id", "tourney_slug", "tourney_location", "tourney_date",
    "tourney_year", "tourney_month", "tourney_day", "tourney_singles_draw",
    "tourney_doubles_draw", "tourney_conditions", "tourney_surface",
    "tourney_fin_commit_raw", "currency", "tourney_fin_commit",
    "tourney_url_suffix", "singles_winner_name", "singles_winner_url",
    "singles_winner_player_slug", "singles_winner_player_id",
    "doubles_winner_1_name", "doubles_winner_1_url",
    "doubles_winner_1_player_slug", "doubles_winner_1_player_id",
    "doubles_winner_2_name", "doubles_winner_2_url",
    "doubles_winner_2_player_slug", "doubles_winner_2_player_id",
]

STAT_COLUMNS = [
    "match_id", "tourney_slug", "match_stats_url_suffix", "match_time",
    "match_duration", "winner_slug", "winner_serve_rating", "winner_aces",
    "winner_double_faults", "winner_first_serves_in", "winner_first_serves_total",
    "winner_first_serve_points_won", "winner_first_serve_points_total",
    "winner_second_serve_points_won", "winner_second_serve_points_total",
    "winner_break_points_saved", "winner_break_points_serve_total",
    "winner_service_games_played", "winner_return_rating",
    "winner_first_serve_return_won", "winner_first_serve_return_total",
    "winner_second_serve_return_won", "winner_second_serve_return_total",
    "winner_break_points_converted", "winner_break_points_return_total",
    "winner_return_games_played", "winner_service_points_won",
    "winner_service_points_total", "winner_return_points_won",
    "winner_return_points_total", "winner_total_points_won",
    "winner_total_points_total", "loser_slug", "loser_serve_rating",
    "loser_aces", "loser_double_faults", "loser_first_serves_in",
    "loser_first_serves_total", "loser_first_serve_points_won",
    "loser_first_serve_points_total", "loser_second_serve_points_won",
    "loser_second_serve_points_total", "loser_break_points_saved",
    "loser_break_points_serve_total", "loser_service_games_played",
    "loser_return_rating", "loser_first_serve_return_won",
    "loser_first_serve_return_total", "loser_second_serve_return_won",
    "loser_second_serve_return_total", "loser_break_points_converted",
    "loser_break_points_return_total", "loser_return_games_played",
    "loser_service_points_won", "loser_service_points_total",
    "loser_return_points_won", "loser_return_points_total",
    "loser_total_points_won", "loser_total_points_total",
]


ROUND_ALIASES = {
    "final": "f", "finals": "f", "f": "f",
    "semi finals": "sf", "semi final": "sf", "semifinals": "sf",
    "semifinal": "sf", "sf": "sf",
    "quarter finals": "qf", "quarter final": "qf",
    "quarterfinals": "qf", "quarterfinal": "qf", "qf": "qf",
    "round of 16": "r16", "r16": "r16",
    "round of 32": "r32", "r32": "r32",
    "round of 64": "r64", "r64": "r64",
    "round of 128": "r128", "r128": "r128",
    "1st round qualifying": "q1", "first round qualifying": "q1", "q1": "q1",
    "2nd round qualifying": "q2", "second round qualifying": "q2", "q2": "q2",
    "3rd round qualifying": "q3", "third round qualifying": "q3", "q3": "q3",
    "round robin": "rr", "rr": "rr",
}


def _norm_round(value: object) -> str:
    return ROUND_ALIASES.get(norm_text(value), norm_text(value))


def _parse_dot_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _num(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rate(numerator: object, denominator: object) -> float | None:
    n, d = _num(numerator), _num(denominator)
    if n is None or d is None or d <= 0 or n < 0 or n > d:
        return None
    return n / d


def _player_stats(prefix: str, row: dict[str, str]) -> dict[str, float] | None:
    aces = _num(row.get(f"{prefix}_aces"))
    dfs = _num(row.get(f"{prefix}_double_faults"))
    if (
        aces is None or dfs is None or aces < 0 or dfs < 0
        or not aces.is_integer() or not dfs.is_integer()
    ):
        return None
    first = _rate(
        row.get(f"{prefix}_first_serve_points_won"),
        row.get(f"{prefix}_first_serve_points_total"),
    )
    second = _rate(
        row.get(f"{prefix}_second_serve_points_won"),
        row.get(f"{prefix}_second_serve_points_total"),
    )
    service = _rate(
        row.get(f"{prefix}_service_points_won"),
        row.get(f"{prefix}_service_points_total"),
    )
    ret = _rate(
        row.get(f"{prefix}_return_points_won"),
        row.get(f"{prefix}_return_points_total"),
    )
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


def _url_key(value: object) -> tuple[str, str, str] | None:
    text = str(value or "").split("?", 1)[0].rstrip("/")
    match = re.search(r"/(\d{4})/(\d+)/([A-Za-z0-9]+)(?:/|$)", text)
    if not match:
        return None
    return tuple(part.lower() for part in match.groups())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_headerless(path: str, columns: list[str], counts: Counter, prefix: str):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for line, values in enumerate(csv.reader(handle), start=1):
            counts[f"{prefix}_rows"] += 1
            if len(values) != len(columns):
                counts[f"{prefix}_bad_width"] += 1
                continue
            yield line, dict(zip(columns, values))


@dataclass(frozen=True)
class SourceMatch:
    source_match_id: str
    start: date
    end: date
    tournament: str
    tournament_id: str
    surface: str
    round_name: str
    winner_name: str
    loser_name: str
    winner_stats: dict[str, float]
    loser_stats: dict[str, float]
    stats_source_file: str
    stats_source_sha256: str

    @property
    def pair(self) -> tuple[str, str]:
        return tuple(sorted((norm_text(self.winner_name), norm_text(self.loser_name))))


def _load_sources(
    tournament_paths: list[str],
    score_paths: list[str],
    stats_paths: list[str],
    counts: Counter,
    min_year: int,
    max_year: int,
) -> list[SourceMatch]:
    tournaments: dict[str, dict[str, str]] = {}
    for path in tournament_paths:
        for _, row in _read_headerless(path, TOURNAMENT_COLUMNS, counts, "tournament"):
            tid = str(row.get("tourney_year_id") or "").strip().lower()
            if tid:
                tournaments[tid] = row

    scores: dict[tuple[str, str, str], dict[str, str]] = {}
    for path in score_paths:
        for _, row in _read_headerless(path, SCORE_COLUMNS, counts, "score"):
            key = _url_key(row.get("match_stats_url_suffix"))
            if not key:
                counts["score_missing_url_key"] += 1
                continue
            if key in scores:
                counts["score_duplicate_url_key"] += 1
                scores[key] = {}
            else:
                scores[key] = row

    sources = []
    seen_source_ids = set()
    for path in stats_paths:
        path_obj = Path(path)
        source_sha = _sha256(path_obj)
        for _, row in _read_headerless(path, STAT_COLUMNS, counts, "stat"):
            key = _url_key(row.get("match_stats_url_suffix"))
            score = scores.get(key) if key else None
            if not score:
                counts["stat_without_unique_score"] += 1
                continue
            try:
                year = int(score.get("start_year") or 0)
            except ValueError:
                year = 0
            if year < min_year or year > max_year:
                counts["filtered_outside_requested_years"] += 1
                continue

            start = _parse_dot_date(score.get("start_date"))
            end = _parse_dot_date(score.get("end_date"))
            if start is None or end is None or end < start:
                counts["invalid_tournament_window"] += 1
                continue

            winner_stats = _player_stats("winner", row)
            loser_stats = _player_stats("loser", row)
            if winner_stats is None or loser_stats is None:
                counts["incomplete_quality_stats"] += 1
                continue

            tournament_id = str(score.get("tourney_year_id") or "").strip().lower()
            tournament = tournaments.get(tournament_id, {})
            surface = norm_surface(tournament.get("tourney_surface"))
            source_id = str(score.get("match_id") or row.get("match_id") or "").strip()
            if not source_id:
                counts["missing_source_match_id"] += 1
                continue
            source_key = source_id.lower()
            if source_key in seen_source_ids:
                counts["duplicate_source_match_id"] += 1
                continue
            seen_source_ids.add(source_key)

            sources.append(SourceMatch(
                source_match_id=source_id,
                start=start,
                end=end,
                tournament=str(score.get("tourney_name") or tournament.get("tourney_name") or ""),
                tournament_id=tournament_id,
                surface=surface,
                round_name=_norm_round(score.get("tourney_round_name")),
                winner_name=str(score.get("winner_name") or "").strip(),
                loser_name=str(score.get("loser_name") or "").strip(),
                winner_stats=winner_stats,
                loser_stats=loser_stats,
                stats_source_file=path_obj.name,
                stats_source_sha256=source_sha,
            ))
            counts["usable_source_matches"] += 1
    return sources


def _canonical_winner_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id):
        return str(match.player2_name or "")
    return ""


def _candidate(source: SourceMatch, match) -> tuple[int, list[str], bool]:
    pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
    if pair != source.pair:
        return -100, ["pair_mismatch"], False

    day = match.scheduled_at.astimezone(timezone.utc).date()
    if not source.start <= day <= source.end:
        return -100, ["outside_tournament_window"], False
    score = 2
    evidence = ["date_in_tournament_window"]

    canonical_winner = _canonical_winner_name(match)
    if not canonical_winner or not legacy_name_matches(source.winner_name, canonical_winner):
        return score, evidence + ["winner_conflict"], False
    score += 3
    evidence.append("winner")

    source_surface = norm_surface(source.surface)
    canonical_surface = norm_surface(match.surface)
    if source_surface not in {"", "unknown"} and canonical_surface not in {"", "unknown"}:
        if source_surface != canonical_surface:
            return score, evidence + ["surface_conflict"], False
        score += 1
        evidence.append("surface")

    sr, cr = source.round_name, _norm_round(match.round_name)
    if sr and cr:
        if sr != cr:
            return score, evidence + ["round_conflict"], False
        score += 2
        evidence.append("round")

    tscore, tevidence = tournament_score(source.tournament, match.tournament)
    if tscore <= 0:
        return score, evidence + [tevidence], False
    score += tscore
    evidence.append(tevidence)

    accepted = (
        score >= 9
        and "winner" in evidence
        and "surface" in evidence
        and "round" in evidence
        and tevidence in {"tournament_exact", "tournament_tokens"}
    )
    return score, evidence, accepted


def _orientation(source: SourceMatch, match) -> dict[str, float] | None:
    p1 = norm_text(match.player1_name)
    p2 = norm_text(match.player2_name)
    winner = norm_text(source.winner_name)
    loser = norm_text(source.loser_name)
    if winner == p1 and loser == p2:
        sides = (("p1", source.winner_stats), ("p2", source.loser_stats))
    elif winner == p2 and loser == p1:
        sides = (("p2", source.winner_stats), ("p1", source.loser_stats))
    else:
        return None
    incoming = {}
    for prefix, stats in sides:
        for key, value in stats.items():
            incoming[f"{prefix}_{key}"] = float(value)
    return incoming


def _quality_ready(stats: dict[str, float | None]) -> bool:
    return all(
        FeatureBuilder._extract_quality(stats, prefix)[0] is not None
        and FeatureBuilder._extract_quality(stats, prefix)[1] is not None
        for prefix in ("p1", "p2")
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--tournaments-csv", action="append", required=True)
    ap.add_argument("--scores-csv", action="append", required=True)
    ap.add_argument("--stats-csv", action="append", required=True)
    ap.add_argument("--min-year", type=int, default=2019)
    ap.add_argument("--max-year", type=int, default=2022)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    if args.min_year > args.max_year:
        ap.error("--min-year must be <= --max-year")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history has identity quarantine; refusing ATP archive linking")

    counts = Counter()
    sources = _load_sources(
        args.tournaments_csv,
        args.scores_csv,
        args.stats_csv,
        counts,
        args.min_year,
        args.max_year,
    )

    by_pair = defaultdict(list)
    by_id = {str(match.match_id): match for match in matches}
    for match in matches:
        if str(match.tour or "").lower() != "atp":
            continue
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        by_pair[pair].append(match)

    linked = defaultdict(list)
    review = []
    quarantine = []

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
                "score": top_score,
                "candidate_match_ids": [str(item[2].match_id) for item in top],
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
        if incoming is None:
            counts["orientation_unverified"] += 1
            continue

        linked[str(match.match_id)].append({
            "source": "serve_and_volley_atp_world_tour",
            "source_match_id": source.source_match_id,
            "source_file": source.stats_source_file,
            "source_file_sha256": source.stats_source_sha256,
            "score": score,
            "evidence": evidence,
            "stats": incoming,
        })
        counts["identity_linked"] += 1

    staged = []
    staged_field_counts = Counter()
    quality_before = sum(1 for match in matches if _quality_ready(match.stats or {}))
    quality_after = quality_before

    for mid, rows in linked.items():
        match = by_id[mid]
        existing = dict(match.stats or {})
        merged = {}
        conflicts = []
        provenance = []
        for row in rows:
            provenance.append({
                key: row[key]
                for key in (
                    "source", "source_match_id", "source_file",
                    "source_file_sha256", "score", "evidence",
                )
            })
            for key, value in row["stats"].items():
                old = existing.get(key)
                prior = merged.get(key)
                if old is not None and abs(float(old) - float(value)) > 1e-6:
                    conflicts.append({
                        "key": key,
                        "reason": "canonical_conflict",
                        "existing": old,
                        "incoming": value,
                    })
                elif prior is not None and abs(float(prior) - float(value)) > 1e-6:
                    conflicts.append({
                        "key": key,
                        "reason": "source_conflict",
                        "existing": prior,
                        "incoming": value,
                    })
                elif old is None:
                    merged[key] = float(value)

        if conflicts:
            counts["stat_conflict_matches"] += 1
            quarantine.append({
                "match_id": mid,
                "reason": "stat_conflict",
                "conflicts": conflicts,
                "sources": provenance,
            })
            continue
        if not merged:
            counts["already_present"] += 1
            continue

        projected = dict(existing)
        projected.update(merged)
        was_ready = _quality_ready(existing)
        is_ready = _quality_ready(projected)
        if is_ready and not was_ready:
            quality_after += 1
        staged_field_counts.update(merged.keys())

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
        "counts": dict(counts),
        "staged_field_counts": dict(sorted(staged_field_counts.items())),
        "quality_ready_before": quality_before,
        "quality_ready_projected_after": quality_after,
        "quality_ready_projected_added": quality_after - quality_before,
        "production_mutated": False,
        "api_requests": 0,
        "source_policy": f"serve-and-volley pinned archive {args.min_year}-{args.max_year}",
        "link_policy": "pair+tournament_window+winner+surface+round+tournament",
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
