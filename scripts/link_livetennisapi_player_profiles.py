"""Build a research-only player profile sidecar from the Live Tennis API public sample.

The public sample contains a complete 2023-2026 match index plus player metadata.
This linker maps source players to canonical BlinQ player IDs only through
strict exact date + exact normalized player-pair match identity. No fuzzy name
matching is allowed. Conflicting profile fields are omitted field-by-field.

No raw source files are redistributed and no production model feature is changed.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import norm_text


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def _parse_time(value):
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _clean_country(value):
    text = str(value or "").strip().upper()
    return text if re.fullmatch(r"[A-Z]{3}", text) else None


def _clean_birthday(value, *, event_date: date | None = None):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        return None
    if parsed.year < 1940:
        return None
    if event_date is not None:
        if parsed >= event_date:
            return None
        age = (event_date - parsed).days / 365.2425
        if age < 12 or age > 60:
            return None
    return parsed.isoformat()


def _clean_hand(value):
    text = str(value or "").strip().upper()
    if text == "R":
        return "right"
    if text == "L":
        return "left"
    return None


def clean_profile(row: dict, *, event_date: date | None = None):
    sackmann = str(row.get("sackmann_id") or "").strip()
    if sackmann and not re.fullmatch(r"\d+", sackmann):
        sackmann = ""
    source_player_id = str(row.get("player_id") or "").strip()
    return {
        "country_alpha3": _clean_country(row.get("country")),
        "birth_date": _clean_birthday(row.get("birthday"), event_date=event_date),
        "hand": _clean_hand(row.get("hand")),
        "sackmann_id": sackmann or None,
        "livetennisapi_player_id": source_player_id or None,
    }


def _load_players(path: Path):
    players = {}
    with _open_text(path) as handle:
        for row in csv.DictReader(handle):
            pid = str(row.get("player_id") or "").strip()
            name = str(row.get("name") or "").strip()
            if not pid or not name:
                continue
            copy = dict(row)
            copy["player_id"] = pid
            copy["name"] = name
            players[pid] = copy
    return players


def _canonical_index(matches):
    index = defaultdict(list)
    for match in matches:
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        index[(match.scheduled_at.date().isoformat(), pair)].append(match)
    return index


def _resolve(candidates, row):
    if len(candidates) <= 1:
        return candidates
    surface = norm_text(row.get("surface"))
    if surface:
        exact = [m for m in candidates if norm_text(m.surface) == surface]
        if len(exact) == 1:
            return exact
        if exact:
            candidates = exact
    tournament = norm_text(row.get("tournament"))
    if tournament:
        exact = [m for m in candidates if norm_text(m.tournament) == tournament]
        if len(exact) == 1:
            return exact
        if exact:
            candidates = exact
    return candidates


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--matches", required=True)
    ap.add_argument("--players", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--source-version", default="")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    canonical, safety = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")
    index = _canonical_index(canonical)
    source_players = _load_players(Path(args.players))

    values = defaultdict(lambda: defaultdict(Counter))
    evidence = defaultdict(set)
    canonical_names = defaultdict(Counter)
    counts = Counter()
    review = []

    with _open_text(Path(args.matches)) as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            counts["source_match_rows"] += 1
            scheduled = _parse_time(row.get("scheduled_time_utc"))
            p1 = source_players.get(str(row.get("player1_id") or "").strip())
            p2 = source_players.get(str(row.get("player2_id") or "").strip())
            if scheduled is None or p1 is None or p2 is None:
                counts["invalid_source_identity"] += 1
                continue
            n1, n2 = norm_text(p1["name"]), norm_text(p2["name"])
            if not n1 or not n2 or n1 == n2:
                counts["invalid_source_identity"] += 1
                continue
            pair = tuple(sorted((n1, n2)))
            candidates = _resolve(list(index.get((scheduled.date().isoformat(), pair), [])), row)
            if not candidates:
                counts["unmatched"] += 1
                continue
            if len(candidates) != 1:
                counts["ambiguous"] += 1
                continue
            match = candidates[0]
            mp1, mp2 = norm_text(match.player1_name), norm_text(match.player2_name)
            if n1 == mp1 and n2 == mp2:
                mapping = ((p1, str(match.player1_id), str(match.player1_name)),
                           (p2, str(match.player2_id), str(match.player2_name)))
            elif n1 == mp2 and n2 == mp1:
                mapping = ((p1, str(match.player2_id), str(match.player2_name)),
                           (p2, str(match.player1_id), str(match.player1_name)))
            else:
                counts["orientation_failed"] += 1
                continue

            counts["identity_linked_matches"] += 1
            for source_player, canonical_id, canonical_name in mapping:
                profile = clean_profile(source_player, event_date=scheduled.date())
                canonical_names[canonical_id][canonical_name] += 1
                evidence[canonical_id].add(str(match.match_id))
                for field, value in profile.items():
                    if value not in (None, ""):
                        values[canonical_id][field][str(value)] += 1

    output = []
    for player_id in sorted(values):
        profile = {}
        conflicts = {}
        for field in (
            "country_alpha3",
            "birth_date",
            "hand",
            "sackmann_id",
            "livetennisapi_player_id",
        ):
            counter = values[player_id][field]
            if len(counter) == 1:
                profile[field] = next(iter(counter))
            elif len(counter) > 1:
                conflicts[field] = dict(counter)
        if conflicts:
            counts["players_with_conflicting_fields"] += 1
            review.append({
                "player_id": player_id,
                "canonical_name": canonical_names[player_id].most_common(1)[0][0],
                "conflicts": conflicts,
            })
        if not profile:
            counts["players_without_safe_profile"] += 1
            continue
        row = {
            "schema": 1,
            "player_id": player_id,
            "canonical_name": canonical_names[player_id].most_common(1)[0][0],
            "profile": profile,
            "evidence_match_count": len(evidence[player_id]),
            "source": "livetennisapi_public_sample",
            "source_version": args.source_version,
            "license": "CC BY-NC 4.0",
            "feature_policy": "research_only_candidate_after_separate_ablation",
        }
        output.append(row)
        counts["safe_players"] += 1
        for field in profile:
            counts[f"safe_{field}"] += 1

    with gzip.open(out / "player-profile-sidecar.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in output:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    with gzip.open(out / "review.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in review:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    report = {
        "schema": 1,
        "canonical_rows": len(canonical),
        "source_players": len(source_players),
        "counts": dict(counts),
        "identity_safety": safety,
        "production_mutated": False,
        "api_requests": 0,
        "raw_redistributed": False,
        "link_policy": "exact UTC calendar date + exact normalized player pair; surface/tournament only disambiguate; no fuzzy identity",
        "feature_policy": "research_only_candidate_after_separate_ablation",
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
