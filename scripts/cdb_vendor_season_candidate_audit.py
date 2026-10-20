#!/usr/bin/env python3
"""Private read-only alias-matching diagnostics for ATP/WTA seasonal tennis data.

Season sources have *abbreviated* player display names and their own IDs.
Alias/date/event matches are ONLY RESEARCH CANDIDATES, never independently
verified canonical match IDs or approved CDB imports. This module intentionally
cannot write linker's import_ready stages or canonical data.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

ALLOWED_STATS = (
    "aces", "double_faults", "service_points_won", "return_points_won",
)
RATE_STATS = ("service_points_won", "return_points_won")
SOURCE_COLUMNS = (
    "match_id", "date_timestamp", "tour_type", "home_name", "away_name",
    "home_id", "away_id", "winner_code", "surface", "tournament",
    *(f"{side}_{field}" for side in ("home", "away")
      for field in ("aces", "double_faults", "service_points_won_perc",
                    "return_points_won_perc")),
)
MAX_ROWS = 100_000
MAX_BYTES = 32 * 1024 * 1024


def _norm(s: object) -> str:
    text = unicodedata.normalize("NFKD", str(s or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _alias(name: object, *, source: bool) -> tuple[str, str] | None:
    words = _norm(name).split()
    if len(words) < 2:
        return None
    if source:
        # "Davidovich Fokina A." -> ("davidovich fokina","a"),
        # "Keys M." -> ("keys","m"). An initial is never an exact identity.
        if len(words[-1]) != 1 or any(len(w) < 2 for w in words[:-1]):
            return None
        return " ".join(words[:-1]), words[-1]
    if len(words[0]) == 1 or len(words[-1]) < 2:
        return None
    return " ".join(words[1:]), words[0][:1]


def _surface(s: object) -> str:
    value = _norm(s)
    for surface in ("hard", "clay", "grass", "carpet"):
        if surface in value.split():
            return surface
    return value


def _tourney(s: object) -> str:
    words = _norm(s).split()
    # Tour labels alone are never identity evidence.
    return " ".join(w for w in words if w not in {"atp", "wta"})


def _stats(row: dict[str, str]) -> dict[str, float] | None:
    vals = {}
    for side in ("home", "away"):
        for field in ALLOWED_STATS:
            key = f"{side}_{field}"
            raw = row.get(key + ("_perc" if field in RATE_STATS else ""))
            if raw in (None, ""):
                continue
            try:
                number = float(raw)
            except (ValueError, TypeError):
                return None
            if not math.isfinite(number):
                return None
            if field in RATE_STATS:
                if not 0 <= number <= 100:
                    return None
                number /= 100
            elif number < 0 or not number.is_integer():
                return None
            vals[key] = number
    return vals


def audit(matches, sources: list[tuple[Path, str, str]]) -> dict:
    """Sources are (file path, tour, expected full-source SHA256)."""
    by_day = defaultdict(list)
    for m in matches:
        day = m.scheduled_at.astimezone(timezone.utc).date()
        tour = str(m.tour or "").lower()
        if tour not in ("atp", "wta"):
            continue
        aliases = (_alias(m.player1_name, source=False), _alias(m.player2_name, source=False))
        if None in aliases or aliases[0] == aliases[1]:
            continue
        by_day[(tour, day, tuple(sorted(aliases)))].append(m)

    counts = Counter()
    year_tour = Counter()
    gaps = Counter()
    sources_report = []
    for path, tour, expected_sha in sources:
        if tour not in {"atp", "wta"} or not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValueError("Unbounded source size or unknown tour")
        if not re.fullmatch("[a-f0-9]{64}", expected_sha):
            raise ValueError("Missing immutable SHA-256")
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        if h.hexdigest() != expected_sha:
            raise ValueError("Source SHA-256 changed")
        seen_source_ids = set()
        before = counts.copy()
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames or []
            if len(fields) > 100 or len(fields) != len(set(fields)) or not set(SOURCE_COLUMNS).issubset(fields):
                raise ValueError("Unexpected season source fields")
            for i, row in enumerate(reader, 1):
                if i > MAX_ROWS or None in row or any(v is None for v in row.values()):
                    raise ValueError("Invalid season CSV row count/shape")
                counts["source_rows"] += 1
                mid = str(row.get("match_id") or "").strip()
                if not mid or mid in seen_source_ids:
                    counts["no_unique_source_match_id"] += 1
                    continue
                seen_source_ids.add(mid)
                if row.get("tour_type", "").casefold() not in {tour, "0", "1", "2", "atp men", "wta women"}:
                    counts["tour_type_unverified"] += 1
                    continue
                a = _alias(row.get("home_name"), source=True)
                b = _alias(row.get("away_name"), source=True)
                if not a or not b or a == b:
                    counts["source_alias_missing"] += 1
                    continue
                code = str(row.get("winner_code") or "")
                if code not in {"1", "2"}:
                    counts["winner_unverified"] += 1
                    continue
                try:
                    timestamp = int(row["date_timestamp"])
                    day = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
                except (ValueError, OverflowError, OSError, TypeError):
                    counts["invalid_timestamp"] += 1
                    continue
                stat = _stats(row)
                if not stat:
                    counts["no_valid_match_stats"] += 1
                    continue
                keys = tuple(sorted((a, b)))
                candidates = {}
                for delta in (-1, 0, 1):
                    for m in by_day.get((tour, day + timedelta(days=delta), keys), ()):
                        candidates[str(m.match_id)] = m
                if not candidates:
                    counts["no_canonical_alias_date_candidate"] += 1
                    continue
                # Canonical alias names are explicitly not independently verified.
                # Avoid certifying identity from a single/multiple fuzzy matches.
                if len(candidates) != 1:
                    counts["ambiguous_canonical_alias_date"] += 1
                    continue
                match = next(iter(candidates.values()))
                pa, pb = _alias(match.player1_name, source=False), _alias(match.player2_name, source=False)
                home_id = match.player1_id if pa == a else match.player2_id
                away_id = match.player1_id if pa == b else match.player2_id
                if str(home_id) == str(away_id):
                    counts["alias_orientation_conflict"] += 1
                    continue
                winner_id = home_id if code == "1" else away_id
                if str(match.winner_id or "") != str(winner_id):
                    counts["canonical_winner_conflict"] += 1
                    continue
                if _surface(row.get("surface")) != _surface(match.surface):
                    counts["surface_conflict"] += 1
                    continue
                event_a, event_b = _tourney(row.get("tournament")), _tourney(match.tournament)
                if not event_a or not event_b or event_a != event_b:
                    counts["event_not_exact"] += 1
                    continue
                counts["research_candidates_same_day_pair_winner_surface_tournament"] += 1
                year_tour[f"{day.year}_{tour}"] += 1
                mapping = {"home": "p1" if str(home_id) == str(match.player1_id) else "p2",
                           "away": "p1" if str(away_id) == str(match.player1_id) else "p2"}
                for key in stat:
                    side, field = key.split("_", 1)
                    canonical_key = mapping[side] + "_" + field
                    if (match.stats or {}).get(canonical_key) is None:
                        gaps[field] += 1
                        counts["candidate_missing_cells_UNVERIFIED"] += 1
                # Intentionally does NOT emit IDs or a write-ready stage.
        sources_report.append({"tour": tour, "source_sha256": expected_sha,
                               "total_rows": counts["source_rows"]-before["source_rows"]})
    return {
        "schema": 1, "state": "UNVERIFIED_SEASON_ALIAS_CANDIDATES_FOR_RESEARCH_ONLY",
        "production_mutated": False, "api_requests": 0,
        "source_report": sources_report,
        "counts": dict(sorted(counts.items())),
        "potential_missing_fields_UNVERIFIED": dict(sorted(gaps.items())),
        "research_candidates_by_year_tour": dict(sorted(year_tour.items())),
        "canonical_matches_confirmed": 0,
        "import_ready": False,
        "license_review_required": True,
        "warning": "Initial+surname aliases and event names are not proof of canonical identity. Independent player/event identity evidence and applicable license are required.",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", type=Path, required=True)
    ap.add_argument("--source", nargs=3, action="append", required=True,
                    metavar=("PATH", "TOUR", "SHA256"))
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        raise ValueError("Audit output exists")
    from _bootstrap import ROOT  # noqa: F401
    from tbt.data.history_snapshot import load_partitions
    from tbt.data.history_safety import sanitize_history_identities
    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows") or safety.get("merged_rows_removed"):
        raise ValueError("Canonical identity quarantine; refusing candidate audit")
    report = audit(matches, [(Path(p),t,s) for p,t,s in args.source])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
