"""Fail-closed linker for Sackmann-style point-by-point tennis archives.

This module is intentionally read-only. It reconstructs only two match-level
quality signals that are directly identifiable from the PBP stream:
service_points_won and return_points_won for both players.

PBP encoding:
  S server won, R returner won, A ace, D double fault,
  ';' game boundary, '.' set boundary, '/' service change in a tiebreak.

Output follows import_offline_linked_serve_return.py stage schema. The linker
never writes canonical history and never uses a provider API.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import norm_text, tournament_score
from tbt.models.feature_builder import FeatureBuilder


TOUR_MAP = {
    "atp": "atp",
    "ch": "atp",
    "challenger": "atp",
    "fu": "atp",
    "futures": "atp",
    "wta": "wta",
    "itf": "wta",
}


def _date(value: object):
    text = str(value or "").strip()
    for fmt in ("%d %b %y", "%d %b %Y", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _tour(value: object) -> str:
    return TOUR_MAP.get(norm_text(value), "")


def _source_id(row: dict[str, str]) -> str:
    existing = str(row.get("pbp_id") or "").strip()
    if existing:
        return existing
    payload = "|".join(
        str(row.get(k) or "").strip()
        for k in ("date", "tny_name", "tour", "draw", "server1", "server2", "score", "pbp")
    )
    return "pbp:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _parse_pbp(value: object):
    text = str(value or "").strip()
    if not text:
        return None, "empty_pbp"

    players = [
        {"service_points": 0, "service_won": 0, "return_points": 0, "return_won": 0},
        {"service_points": 0, "service_won": 0, "return_points": 0, "return_won": 0},
    ]
    server = 0
    game_has_points = False
    point_count = 0

    for char in text:
        if char in "SRAD":
            receiver = 1 - server
            players[server]["service_points"] += 1
            players[receiver]["return_points"] += 1
            if char in "SA":
                players[server]["service_won"] += 1
            else:
                players[receiver]["return_won"] += 1
            point_count += 1
            game_has_points = True
            continue

        if char == "/":
            if not game_has_points:
                return None, "serve_change_without_point"
            server = 1 - server
            continue

        if char in ";.":
            if game_has_points:
                server = 1 - server
                game_has_points = False
            continue

        if char.isspace():
            continue
        return None, f"unsupported_pbp_char:{char}"

    if point_count < 8:
        return None, "too_few_points"
    if any(p["service_points"] <= 0 or p["return_points"] <= 0 for p in players):
        return None, "missing_player_denominator"

    result = []
    for p in players:
        service = p["service_won"] / p["service_points"]
        ret = p["return_won"] / p["return_points"]
        if not (0.0 <= service <= 1.0 and 0.0 <= ret <= 1.0):
            return None, "rate_out_of_range"
        result.append(
            {
                "service_points_won": service,
                "return_points_won": ret,
                "service_points": p["service_points"],
                "return_points": p["return_points"],
            }
        )
    return result, ""


@dataclass(frozen=True)
class PbpMatch:
    source: str
    source_match_id: str
    tour: str
    event_date: object
    tournament: str
    player_a: str
    player_b: str
    winner: str
    stats_a: dict[str, float]
    stats_b: dict[str, float]

    @property
    def pair(self):
        return tuple(sorted((norm_text(self.player_a), norm_text(self.player_b))))


def _rows(paths: list[str], counts: Counter):
    seen = set()
    for path_text in paths:
        path = Path(path_text)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for number, row in enumerate(csv.DictReader(handle), start=2):
                counts["source_rows"] += 1
                day = _date(row.get("date"))
                tour = _tour(row.get("tour"))
                a = str(row.get("server1") or "").strip()
                b = str(row.get("server2") or "").strip()
                winner_raw = str(row.get("winner") or "").strip()
                if day is None or not tour or not a or not b or norm_text(a) == norm_text(b):
                    counts["invalid_identity"] += 1
                    continue
                parsed, error = _parse_pbp(row.get("pbp"))
                if parsed is None:
                    counts["invalid_pbp"] += 1
                    counts[f"invalid_pbp_{error}"] += 1
                    continue
                if winner_raw == "1":
                    winner = a
                elif winner_raw == "2":
                    winner = b
                else:
                    counts["invalid_winner"] += 1
                    continue
                sid = _source_id(row)
                if sid in seen:
                    counts["duplicate_source_id"] += 1
                    continue
                seen.add(sid)
                counts["usable_source_rows"] += 1
                yield PbpMatch(
                    source=f"sackmann_pbp:{path.name}",
                    source_match_id=sid,
                    tour=tour,
                    event_date=day,
                    tournament=str(row.get("tny_name") or "").strip(),
                    player_a=a,
                    player_b=b,
                    winner=winner,
                    stats_a={
                        "service_points_won": float(parsed[0]["service_points_won"]),
                        "return_points_won": float(parsed[0]["return_points_won"]),
                    },
                    stats_b={
                        "service_points_won": float(parsed[1]["service_points_won"]),
                        "return_points_won": float(parsed[1]["return_points_won"]),
                    },
                )


def _canonical_winner(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id):
        return str(match.player2_name or "")
    return ""


def _signature(match):
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


def _orientation(source: PbpMatch, match):
    a, b = norm_text(source.player_a), norm_text(source.player_b)
    p1, p2 = norm_text(match.player1_name), norm_text(match.player2_name)
    if a == p1 and b == p2:
        sides = (("p1", source.stats_a), ("p2", source.stats_b))
    elif a == p2 and b == p1:
        sides = (("p2", source.stats_a), ("p1", source.stats_b))
    else:
        return None
    incoming = {}
    for prefix, stats in sides:
        for key, value in stats.items():
            incoming[f"{prefix}_{key}"] = float(value)
    return incoming


def _quality(stats):
    return all(
        FeatureBuilder._extract_quality(stats or {}, side)[0] is not None
        and FeatureBuilder._extract_quality(stats or {}, side)[1] is not None
        for side in ("p1", "p2")
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--pbp-csv", action="append", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history has identity quarantine; refusing PBP linking")

    by_key = defaultdict(list)
    by_id = {str(m.match_id): m for m in matches}
    for match in matches:
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        by_key[(str(match.tour or "").lower(), match.scheduled_at.date(), pair)].append(match)

    counts = Counter()
    staged = []
    review = []
    linked = {}
    quality_before = sum(1 for m in matches if _quality(m.stats or {}))
    quality_after = quality_before

    for source in _rows(args.pbp_csv, counts):
        candidates = by_key.get((source.tour, source.event_date, source.pair), [])
        scored = []
        for match in candidates:
            canonical_winner = _canonical_winner(match)
            if not canonical_winner or norm_text(canonical_winner) != norm_text(source.winner):
                continue
            tscore, tev = tournament_score(source.tournament, match.tournament)
            if tscore <= 0:
                continue
            scored.append((tscore, match, tev))
        if not scored:
            counts["unmatched"] += 1
            continue
        best = max(score for score, _, _ in scored)
        top = [(m, ev) for score, m, ev in scored if score == best]
        if len(top) != 1:
            counts["ambiguous"] += 1
            review.append({
                "source_match_id": source.source_match_id,
                "reason": "ambiguous",
                "candidate_match_ids": [str(m.match_id) for m, _ in top],
            })
            continue

        match, tev = top[0]
        incoming = _orientation(source, match)
        if incoming is None:
            counts["orientation_unverified"] += 1
            continue

        mid = str(match.match_id)
        if mid in linked:
            counts["canonical_duplicate_link"] += 1
            review.append({"source_match_id": source.source_match_id, "reason": "canonical_duplicate_link", "match_id": mid})
            continue
        linked[mid] = source.source_match_id

        existing = dict(match.stats or {})
        conflicts = [
            key for key, value in incoming.items()
            if existing.get(key) is not None and abs(float(existing[key]) - float(value)) > 0.02
        ]
        if conflicts:
            counts["stat_conflict_matches"] += 1
            review.append({
                "source_match_id": source.source_match_id,
                "reason": "stat_conflicts",
                "match_id": mid,
                "keys": conflicts,
            })
            continue

        clean = {key: value for key, value in incoming.items() if existing.get(key) is None}
        if not clean:
            counts["already_present"] += 1
            continue

        projected = dict(existing)
        projected.update(clean)
        before_ready = _quality(existing)
        after_ready = _quality(projected)
        quality_after += int(after_ready and not before_ready)

        staged.append({
            "schema": 1,
            "match_id": mid,
            "canonical": _signature(match),
            "incoming_stats": clean,
            "provenance": [{
                "source": source.source,
                "source_match_id": source.source_match_id,
                "evidence": ["date_exact", "player_pair_exact", "winner_exact", tev],
            }],
            "import_ready": True,
        })
        counts["staged_matches"] += 1

    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "counts": dict(counts),
        "quality_ready_before": quality_before,
        "quality_ready_projected_after": quality_after,
        "quality_ready_projected_added": quality_after - quality_before,
        "production_mutated": False,
        "api_requests": 0,
        "source_policy": "Sackmann-style PBP; S/R/A/D only; no imputation",
        "link_policy": "exact date+pair+winner plus positive tournament evidence; ambiguous links rejected",
        "note": "Read-only linker. Stage must pass import_offline_linked_serve_return.py before any write.",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for filename, rows in (("auto_linked.jsonl", staged), ("review.jsonl", review)):
        with (out / filename).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
