"""Resolve useful static ATP player metadata from the operator Tennis-Data file.

The source is Winner/Loser oriented. Rows are first linked to canonical matches with
the same fail-closed identity evidence used by historical odds. Only then are
source Winner/Loser profiles mapped to canonical player IDs. Implausible values
are discarded field-by-field; conflicting values for a canonical player are not
published. Output is research-only and is not a production model feature.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import LegacyOddsRow, candidate_link, norm_text, source_match_id


HAND_MAP = {
    "right-handed": "right",
    "right handed": "right",
    "right": "right",
    "left-handed": "left",
    "left handed": "left",
    "left": "left",
    "ambidextrous": "ambidextrous",
}


def _winner_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id):
        return str(match.player2_name or "")
    return ""


def _float(value):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number


def clean_profile(row: dict, prefix: str, *, match_year: int) -> dict:
    flag = str(row.get(f"{prefix}_flag") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", flag):
        flag = ""

    year = _float(row.get(f"{prefix}_year_pro"))
    year_pro = int(year) if year is not None and 1980 <= year <= match_year else None

    weight = _float(row.get(f"{prefix}_weight"))
    weight_kg = int(round(weight)) if weight is not None and 45 <= weight <= 130 else None

    height = _float(row.get(f"{prefix}_height"))
    height_cm = int(round(height)) if height is not None and 150 <= height <= 220 else None

    hand_raw = " ".join(str(row.get(f"{prefix}_hand") or "").strip().lower().split())
    hand = HAND_MAP.get(hand_raw)

    return {
        "country_alpha3": flag or None,
        "year_pro": year_pro,
        "weight_kg": weight_kg,
        "height_cm": height_cm,
        "hand": hand,
    }


def _legacy(row: dict, number: int) -> LegacyOddsRow | None:
    from tbt.data.offline_odds import parse_date, norm_surface, int_or_none

    day = parse_date(row.get("Date"))
    winner = str(row.get("Winner") or "").strip()
    loser = str(row.get("Loser") or "").strip()
    if day is None or not winner or not loser:
        return None
    best_of = int_or_none(row.get("Best of"))
    if best_of not in {3, 5}:
        best_of = None
    sid = source_match_id(
        "atp", day.isoformat(), row.get("Tournament"), winner, loser, winner, "profile"
    )
    return LegacyOddsRow(
        row_number=number,
        tour="atp",
        event_date=day,
        tournament=str(row.get("Tournament") or "").strip(),
        surface=norm_surface(row.get("Surface")),
        round_name=str(row.get("Round") or "").strip(),
        best_of=best_of,
        player_a=winner,
        player_b=loser,
        winner=winner,
        rank_a=int_or_none(row.get("WRank")),
        rank_b=int_or_none(row.get("LRank")),
        odds_a=2.0,
        odds_b=2.0,
        source_match_id=sid,
    )


def _signature(match) -> dict:
    return {
        "tour": str(match.tour or "").lower(),
        "scheduled_date_utc": match.scheduled_at.date().isoformat(),
        "player1_id": str(match.player1_id),
        "player1_name": str(match.player1_name),
        "player2_id": str(match.player2_id),
        "player2_name": str(match.player2_name),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--source-csv", required=True)
    ap.add_argument("--source-label", default="operator_supplied_tennis_data")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    matches, identity = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if identity.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    by_day = defaultdict(list)
    for match in matches:
        if str(match.tour or "").lower() == "atp":
            by_day[match.scheduled_at.date()].append(match)

    values: dict[str, dict[str, Counter]] = defaultdict(
        lambda: {
            "country_alpha3": Counter(),
            "year_pro": Counter(),
            "weight_kg": Counter(),
            "height_cm": Counter(),
            "hand": Counter(),
            "source_alias": Counter(),
            "canonical_name": Counter(),
        }
    )
    evidence_matches: dict[str, set[str]] = defaultdict(set)
    counts = Counter()
    review = []

    with Path(args.source_csv).open("r", encoding="utf-8-sig", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            counts["source_rows"] += 1
            source = _legacy(row, number)
            if source is None:
                counts["invalid_identity_rows"] += 1
                continue

            candidates = []
            for delta in (-1, 0, 1):
                candidates.extend(by_day.get(source.event_date + timedelta(days=delta), []))
            scored = []
            for match in {str(item.match_id): item for item in candidates}.values():
                linked = candidate_link(
                    source,
                    canonical_tour="atp",
                    canonical_date=match.scheduled_at.date(),
                    canonical_player1=match.player1_name,
                    canonical_player2=match.player2_name,
                    canonical_winner=_winner_name(match),
                    canonical_tournament=match.tournament,
                    canonical_surface=match.surface,
                    canonical_round=match.round_name,
                    canonical_best_of=match.best_of,
                    canonical_rank1=match.player1_rank,
                    canonical_rank2=match.player2_rank,
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

            orientation = str(linked["orientation"])
            winner_profile = clean_profile(row, "pl1", match_year=source.event_date.year)
            loser_profile = clean_profile(row, "pl2", match_year=source.event_date.year)
            if orientation == "direct":
                mapped = (
                    (str(match.player1_id), str(match.player1_name), source.player_a, winner_profile),
                    (str(match.player2_id), str(match.player2_name), source.player_b, loser_profile),
                )
            else:
                mapped = (
                    (str(match.player2_id), str(match.player2_name), source.player_a, winner_profile),
                    (str(match.player1_id), str(match.player1_name), source.player_b, loser_profile),
                )

            for player_id, canonical_name, alias, profile in mapped:
                values[player_id]["source_alias"][norm_text(alias)] += 1
                values[player_id]["canonical_name"][canonical_name] += 1
                evidence_matches[player_id].add(str(match.match_id))
                for field, value in profile.items():
                    if value not in (None, ""):
                        values[player_id][field][str(value)] += 1
            counts["linked_matches"] += 1

    output = []
    for player_id, fields in sorted(values.items()):
        conflicts = {}
        profile = {}
        for field in ("country_alpha3", "year_pro", "weight_kg", "height_cm", "hand"):
            counter = fields[field]
            if len(counter) == 1:
                raw = next(iter(counter))
                if field in {"year_pro", "weight_kg", "height_cm"}:
                    profile[field] = int(raw)
                else:
                    profile[field] = raw
            elif len(counter) > 1:
                conflicts[field] = dict(counter)

        aliases = [name for name, _ in fields["source_alias"].most_common()]
        canonical_name = fields["canonical_name"].most_common(1)[0][0]
        if conflicts:
            counts["players_with_conflicting_fields"] += 1
            review.append(
                {
                    "player_id": player_id,
                    "canonical_name": canonical_name,
                    "conflicts": conflicts,
                }
            )
        if not profile:
            counts["players_without_safe_profile"] += 1
            continue
        output.append(
            {
                "schema": 1,
                "player_id": player_id,
                "canonical_name": canonical_name,
                "profile": profile,
                "source_aliases": aliases[:12],
                "evidence_match_count": len(evidence_matches[player_id]),
                "source": args.source_label,
                "feature_policy": "research_only_candidate_after_separate_ablation",
            }
        )
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
        "canonical_rows": len(matches),
        "identity_safety": identity,
        "counts": dict(counts),
        "production_mutated": False,
        "api_requests": 0,
        "feature_policy": "research_only_candidate_after_separate_ablation",
        "validation": {
            "country_alpha3": "exact 3 uppercase letters",
            "year_pro": "1980..match_year",
            "weight_kg": "45..130",
            "height_cm": "150..220",
            "hand": sorted(set(HAND_MAP.values())),
            "conflicts": "field omitted when canonical player has >1 distinct validated value",
        },
    }
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
