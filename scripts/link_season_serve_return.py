"""Stage ATP/WTA season CSV serve/return stats for canonical history.

These are post-match statistics. They are attached to historical matches only so
FeatureBuilder may use them for later matches during point-in-time replay.
Production history is never changed by this linker.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import (
    legacy_name_matches, norm_surface, norm_text, pair_orientation,
    round_evidence, tournament_score,
)
from tbt.models.feature_builder import FeatureBuilder

COMPLEMENT_TOLERANCE = 0.02
RATE_CONFLICT_TOLERANCE = 0.021


@dataclass(frozen=True)
class SourceMatch:
    file: str
    sha256: str
    source_id: str
    tour: str
    played_at: datetime
    tournament: str
    round_name: str
    surface: str
    home_name: str
    away_name: str
    home_id: str
    away_id: str
    winner_name: str
    home_stats: dict[str, float]
    away_stats: dict[str, float]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: object) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _percent(value: object) -> float | None:
    result = _number(value)
    return result / 100.0 if result is not None and 0 <= result <= 100 else None


def _count(value: object) -> float | None:
    result = _number(value)
    return float(result) if result is not None and result >= 0 and result.is_integer() else None


def _tour(row: dict[str, Any], path: Path) -> str | None:
    raw = str(row.get("tour_type") or "").strip()
    human = norm_text(row.get("tour_type_human"))
    name = path.name.lower()
    if raw == "1" or "atp" in human or "-atp-" in name:
        return "atp"
    if raw == "2" or "wta" in human or "-wta-" in name:
        return "wta"
    return None


def _played_at(row: dict[str, Any]) -> datetime | None:
    timestamp = _number(row.get("date_timestamp"))
    if timestamp is not None and timestamp > 0:
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    try:
        return datetime.strptime(
            str(row.get("date_human") or "").strip(), "%d %b %Y"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_row(
    row: dict[str, Any], *, path: Path, source_sha256: str
) -> tuple[SourceMatch | None, str]:
    if str(row.get("status") or "").strip().upper() != "FINISHED":
        return None, "not_finished"
    if str(row.get("status_extra") or "").strip().upper() != "FINISHED":
        return None, "non_standard_finish"

    tour = _tour(row, path)
    played_at = _played_at(row)
    raw_id = str(row.get("match_id") or "").strip()
    home = str(row.get("home_name") or "").strip()
    away = str(row.get("away_name") or "").strip()
    winner_code = str(row.get("winner_code") or "").strip()
    if (
        not tour
        or not played_at
        or not raw_id
        or not home
        or not away
        or norm_text(home) == norm_text(away)
        or winner_code not in {"1", "2"}
    ):
        return None, "invalid_identity"
    year = str(row.get("season_year") or "").strip()
    if year.isdigit() and int(year) != played_at.year:
        return None, "season_year_mismatch"

    hs = _percent(row.get("home_service_points_won_perc"))
    aws = _percent(row.get("away_service_points_won_perc"))
    hr = _percent(row.get("home_return_points_won_perc"))
    awr = _percent(row.get("away_return_points_won_perc"))
    if any(value is None for value in (hs, aws, hr, awr)):
        return None, "missing_quality_rates"
    assert hs is not None and aws is not None and hr is not None and awr is not None
    if (
        abs(hs + awr - 1.0) > COMPLEMENT_TOLERANCE
        or abs(aws + hr - 1.0) > COMPLEMENT_TOLERANCE
    ):
        return None, "inconsistent_quality_rates"

    home_stats = {"service_points_won": hs, "return_points_won": hr}
    away_stats = {"service_points_won": aws, "return_points_won": awr}
    for source_key, target in (
        ("home_aces", "aces"),
        ("home_double_faults", "double_faults"),
    ):
        value = _count(row.get(source_key))
        if value is not None:
            home_stats[target] = value
    for source_key, target in (
        ("away_aces", "aces"),
        ("away_double_faults", "double_faults"),
    ):
        value = _count(row.get(source_key))
        if value is not None:
            away_stats[target] = value

    return SourceMatch(
        file=path.name,
        sha256=source_sha256,
        source_id=f"season:{tour}:{raw_id}",
        tour=tour,
        played_at=played_at,
        tournament=str(row.get("tournament") or "").strip(),
        round_name=str(row.get("round") or "").strip(),
        surface=norm_surface(row.get("surface")),
        home_name=home,
        away_name=away,
        home_id=str(row.get("home_id") or "").strip(),
        away_id=str(row.get("away_id") or "").strip(),
        winner_name=home if winner_code == "1" else away,
        home_stats=home_stats,
        away_stats=away_stats,
    ), "ok"


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


def _winner_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id or ""):
        return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id or ""):
        return str(match.player2_name or "")
    return ""


def _candidate(source: SourceMatch, match) -> dict[str, Any]:
    if (
        str(match.tour or "").lower() != source.tour
        or match.scheduled_at.astimezone(timezone.utc).date() != source.played_at.date()
    ):
        return {"accepted": False}
    orientation = pair_orientation(
        source.home_name, source.away_name, match.player1_name, match.player2_name
    )
    if orientation is None:
        return {"accepted": False}
    winner = _winner_name(match)
    if not winner or not legacy_name_matches(source.winner_name, winner):
        return {"accepted": False}

    evidence = ["date_exact", "pair", "winner"]
    score = 7
    tscore, tevidence = tournament_score(source.tournament, match.tournament)
    if tscore <= 0:
        return {"accepted": False}
    score += tscore
    evidence.append(tevidence)

    source_surface, target_surface = norm_surface(source.surface), norm_surface(match.surface)
    if (
        source_surface not in {"", "unknown"}
        and target_surface not in {"", "unknown"}
    ):
        if source_surface != target_surface:
            return {"accepted": False}
        score += 1
        evidence.append("surface")

    rscore, revidence = round_evidence(source.round_name, match.round_name)
    if rscore < 0:
        return {"accepted": False}
    if rscore:
        score += rscore
        evidence.append(revidence)
    return {
        "accepted": score >= 9,
        "score": score,
        "evidence": evidence,
        "orientation": orientation,
    }


def _incoming(source: SourceMatch, orientation: str) -> dict[str, float]:
    first, second = (
        (source.home_stats, source.away_stats)
        if orientation == "direct"
        else (source.away_stats, source.home_stats)
    )
    result = {f"p1_{key}": float(value) for key, value in first.items()}
    result.update({f"p2_{key}": float(value) for key, value in second.items()})
    return result


def _conflicts(existing: dict[str, Any], incoming: dict[str, float]) -> list[str]:
    # Only a material disagreement in the serve/return quality fields can veto
    # the link. Ace/DF counts are secondary enrichment: if canonical already has
    # a count, the staged clean set simply leaves that count untouched.
    out = []
    for key, value in incoming.items():
        if not key.endswith(("service_points_won", "return_points_won")):
            continue
        if existing.get(key) is None:
            continue
        current = _number(existing.get(key))
        if current is None or abs(current - value) > RATE_CONFLICT_TOLERANCE:
            out.append(key)
    return out


def _quality(stats: dict[str, Any]) -> bool:
    return all(
        FeatureBuilder._extract_quality(stats or {}, side)[0] is not None
        and FeatureBuilder._extract_quality(stats or {}, side)[1] is not None
        for side in ("p1", "p2")
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--season-csv", action="append", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    matches, identity = sanitize_history_identities(load_partitions(args.history_dir))
    if identity.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    by_date, by_pair = defaultdict(list), defaultdict(list)
    for match in matches:
        tour = str(match.tour or "").lower()
        day = match.scheduled_at.astimezone(timezone.utc).date()
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        by_date[(tour, day)].append(match)
        by_pair[(tour, day, pair)].append(match)

    counts, sources, source_files, seen = Counter(), [], [], set()
    for raw_path in args.season_csv:
        path = Path(raw_path)
        sha = _sha256(path)
        source_files.append({"name": path.name, "sha256": sha})
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                counts["source_rows"] += 1
                source, reason = _parse_row(row, path=path, source_sha256=sha)
                if source is None:
                    counts[reason] += 1
                    continue
                if source.source_id in seen:
                    counts["duplicate_source_match_id"] += 1
                    continue
                seen.add(source.source_id)
                sources.append(source)
                counts["usable_source_matches"] += 1

    staged, review, staged_ids = [], [], set()
    projected_quality_added = 0
    for source in sources:
        pair = tuple(sorted((norm_text(source.home_name), norm_text(source.away_name))))
        candidates = list(by_pair.get((source.tour, source.played_at.date(), pair), []))
        if not candidates:
            candidates = by_date.get((source.tour, source.played_at.date()), [])
        accepted = []
        for match in candidates:
            linked = _candidate(source, match)
            if linked.get("accepted"):
                accepted.append((match, linked))
        if not accepted:
            counts["unmatched"] += 1
            continue
        best_score = max(int(item[1]["score"]) for item in accepted)
        best = [item for item in accepted if int(item[1]["score"]) == best_score]
        if len(best) != 1:
            counts["ambiguous"] += 1
            review.append({
                "source_match_id": source.source_id,
                "reason": "ambiguous_canonical_link",
                "candidate_match_ids": [str(x[0].match_id) for x in best],
            })
            continue

        match, linked = best[0]
        mid = str(match.match_id)
        if mid in staged_ids:
            counts["duplicate_canonical_link"] += 1
            continue
        incoming, existing = _incoming(source, str(linked["orientation"])), dict(match.stats or {})
        conflicts = _conflicts(existing, incoming)
        if conflicts:
            counts["canonical_conflict"] += 1
            review.append({
                "source_match_id": source.source_id,
                "match_id": mid,
                "reason": "canonical_conflict",
                "keys": conflicts,
            })
            continue
        clean = {key: value for key, value in incoming.items() if existing.get(key) is None}
        if not clean:
            counts["already_present"] += 1
            continue
        projected = dict(existing)
        projected.update(clean)
        if not _quality(existing) and _quality(projected):
            projected_quality_added += 1

        staged.append({
            "schema": 1,
            "match_id": mid,
            "canonical": _signature(match),
            "incoming_stats": clean,
            "source": {
                "kind": "atp_wta_season_csv",
                "source_file": source.file,
                "source_file_sha256": source.sha256,
                "source_match_id": source.source_id,
                "source_player_ids": [source.home_id, source.away_id],
                "rate_semantics": "rounded_whole_percent_post_match_event_statistics",
            },
            "link": {
                "score": linked["score"],
                "evidence": linked["evidence"],
                "orientation": linked["orientation"],
            },
            "import_ready": True,
        })
        staged_ids.add(mid)
        counts["staged_matches"] += 1

    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "identity_safety": identity,
        "source_files": source_files,
        "counts": dict(counts),
        "projected_quality_ready_added": projected_quality_added,
        "production_mutated": False,
        "api_requests": 0,
        "training_policy": {
            "same_match_feature_use": False,
            "history_role": "post_match_state_update_for_future_point_in_time_features",
            "overwrite_canonical_denominator_stats": False,
            "precomputed_elo_imported": False,
        },
    }
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_jsonl(out / "auto_linked.jsonl", staged)
    _write_jsonl(out / "review.jsonl", review)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
