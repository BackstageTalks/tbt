"""Link the CC BY 4.0 CVPRW 2026 tennis serve metadata to BlinQ history.

The source is metadata.parquet (5,966 serves / 113 US Open 2024 matches)
from jasnwag/tennis_serve_dataset. This linker is built against the REAL
published parquet schema, not the earlier README example schema.

Output is a private research sidecar only. Same-match serve outcomes are
post-match observations and are never promoted directly to pre-match model
features. Future feature use must be chronological and strictly lagged.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import norm_text

SOURCE = "jasnwag/tennis_serve_dataset"
LICENSE = "CC BY 4.0"
SOURCE_EVENT = "US Open 2024"

REQUIRED_COLUMNS = {
    "match_id",
    "server",
    "returner",
    "gender",
    "height_cm",
    "point_number",
    "point_winner",
    "serve_number",
    "speed_kmh",
    "serve_width",
    "serve_depth",
    "return_depth",
    "n_frames",
    "duration_sec",
    "quality_label",
    "ace",
    "rally_count",
    "set_no",
    "game_no",
}


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _counter(series: pd.Series) -> dict[str, int]:
    values = [norm_text(x) for x in series.dropna().tolist()]
    return dict(Counter(x for x in values if x))


def _canonical_index(matches):
    by_pair = defaultdict(list)
    for match in matches:
        if int(match.scheduled_at.year) != 2024:
            continue
        tournament = norm_text(match.tournament)
        if "us open" not in tournament:
            continue
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        if not all(pair):
            continue
        by_pair[pair].append(match)
    return by_pair


def _source_matches(frame: pd.DataFrame):
    missing = sorted(REQUIRED_COLUMNS - set(map(str, frame.columns)))
    if missing:
        raise ValueError(f"Missing serve metadata columns: {missing}")

    for source_match_id, group in frame.groupby("match_id", dropna=False, sort=False):
        if pd.isna(source_match_id):
            continue

        participants = {
            norm_text(value): str(value).strip()
            for column in ("server", "returner")
            for value in group[column].dropna().tolist()
            if str(value).strip()
        }
        if len(participants) != 2:
            yield {
                "source_match_id": str(source_match_id),
                "invalid_identity": True,
                "participants": sorted(participants.values()),
                "rows": group,
            }
            continue

        genders = {
            str(value).strip().upper()
            for value in group["gender"].dropna().tolist()
            if str(value).strip()
        }
        source_tour = ""
        if genders == {"M"}:
            source_tour = "atp"
        elif genders == {"F"}:
            source_tour = "wta"

        players = sorted(participants.items())
        yield {
            "source_match_id": str(source_match_id),
            "player_a": players[0][1],
            "player_b": players[1][1],
            "source_tour": source_tour,
            "rows": group,
        }


def _aggregate_player(rows: pd.DataFrame, player_name: str) -> dict[str, Any]:
    target = norm_text(player_name)
    selected = rows[rows["server"].map(norm_text) == target]

    speeds = [
        value
        for value in (_num(x) for x in selected["speed_kmh"].tolist())
        if value is not None and 40 <= value <= 280
    ]
    first = [
        value
        for speed, serve_no in zip(selected["speed_kmh"], selected["serve_number"])
        if _int(serve_no) == 1
        for value in [_num(speed)]
        if value is not None and 40 <= value <= 280
    ]
    second = [
        value
        for speed, serve_no in zip(selected["speed_kmh"], selected["serve_number"])
        if _int(serve_no) == 2
        for value in [_num(speed)]
        if value is not None and 40 <= value <= 280
    ]
    quality = [
        value
        for value in (_num(x) for x in selected["quality_label"].tolist())
        if value is not None
    ]
    rallies = [
        value
        for value in (_num(x) for x in selected["rally_count"].tolist())
        if value is not None and value >= 0
    ]
    durations = [
        value
        for value in (_num(x) for x in selected["duration_sec"].tolist())
        if value is not None and value >= 0
    ]
    heights = {
        value
        for value in (_int(x) for x in selected["height_cm"].tolist())
        if value is not None and 130 <= value <= 230
    }
    sets = {
        value
        for value in (_int(x) for x in selected["set_no"].dropna().tolist())
        if value is not None
    }
    games = {
        (_int(s), _int(g))
        for s, g in zip(selected["set_no"], selected["game_no"])
        if _int(s) is not None and _int(g) is not None
    }
    ace_count = int(sum((_int(x) or 0) == 1 for x in selected["ace"]))

    return {
        "serve_rows": int(len(selected)),
        "height_cm": next(iter(heights)) if len(heights) == 1 else None,
        "speed_observations": len(speeds),
        "speed_kmh_mean": _mean(speeds),
        "speed_kmh_median": median(speeds) if speeds else None,
        "speed_kmh_max": max(speeds) if speeds else None,
        "first_serve_speed_kmh_mean": _mean(first),
        "second_serve_speed_kmh_mean": _mean(second),
        "serve_number_1_rows": int(sum(_int(x) == 1 for x in selected["serve_number"])),
        "serve_number_2_rows": int(sum(_int(x) == 2 for x in selected["serve_number"])),
        "ace_count": ace_count,
        "ace_rate_per_serve_row": (ace_count / len(selected)) if len(selected) else None,
        "quality_label_mean": _mean(quality),
        "rally_count_mean": _mean(rallies),
        "rally_count_median": median(rallies) if rallies else None,
        "serve_duration_sec_mean": _mean(durations),
        "serve_width_counts": _counter(selected["serve_width"]),
        "serve_depth_counts": _counter(selected["serve_depth"]),
        "opponent_return_depth_counts": _counter(selected["return_depth"]),
        "sets_observed": len(sets),
        "service_games_observed": len(games),
    }


def link(frame: pd.DataFrame, matches) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    safe, identity_safety = sanitize_history_identities(matches)
    if identity_safety.get("quarantined_rows"):
        raise RuntimeError("Canonical history identity quarantine is non-empty")
    index = _canonical_index(safe)

    output = []
    review = []
    counts = Counter()

    for source in _source_matches(frame):
        counts["source_matches"] += 1
        rows = source["rows"]
        counts["source_serve_rows"] += int(len(rows))
        if source.get("invalid_identity"):
            counts["invalid_source_identity"] += 1
            review.append({
                "source_match_id": source["source_match_id"],
                "reason": "invalid_source_identity",
                "participants": source.get("participants", []),
            })
            continue

        player_a = source["player_a"]
        player_b = source["player_b"]
        pair = tuple(sorted((norm_text(player_a), norm_text(player_b))))
        candidates = list(index.get(pair, []))

        source_tour = source.get("source_tour") or ""
        if source_tour:
            candidates = [
                match for match in candidates
                if str(match.tour or "").lower() == source_tour
            ]

        if not candidates:
            counts["unmatched"] += 1
            review.append({
                "source_match_id": source["source_match_id"],
                "reason": "unmatched",
                "player_a": player_a,
                "player_b": player_b,
                "source_tour": source_tour,
            })
            continue
        if len(candidates) != 1:
            counts["ambiguous"] += 1
            review.append({
                "source_match_id": source["source_match_id"],
                "reason": "ambiguous",
                "candidate_match_ids": [str(m.match_id) for m in candidates],
            })
            continue

        match = candidates[0]
        mp1, mp2 = norm_text(match.player1_name), norm_text(match.player2_name)
        source_names = {norm_text(player_a): player_a, norm_text(player_b): player_b}
        if mp1 not in source_names or mp2 not in source_names:
            counts["orientation_failed"] += 1
            continue

        player1_agg = _aggregate_player(rows, source_names[mp1])
        player2_agg = _aggregate_player(rows, source_names[mp2])
        if not player1_agg["serve_rows"] or not player2_agg["serve_rows"]:
            counts["missing_player_serve_rows"] += 1
            review.append({
                "source_match_id": source["source_match_id"],
                "reason": "missing_player_serve_rows",
                "match_id": str(match.match_id),
            })
            continue

        row = {
            "schema": 2,
            "match_id": str(match.match_id),
            "source_match_id": source["source_match_id"],
            "tour": str(match.tour or "").lower(),
            "scheduled_date_utc": match.scheduled_at.date().isoformat(),
            "tournament": str(match.tournament or ""),
            "round": str(match.round_name or ""),
            "player1_id": str(match.player1_id),
            "player1_name": str(match.player1_name),
            "player2_id": str(match.player2_id),
            "player2_name": str(match.player2_name),
            "player1_serve": player1_agg,
            "player2_serve": player2_agg,
            "source": SOURCE,
            "source_event": SOURCE_EVENT,
            "license": LICENSE,
            "evidence": (
                "exact normalized participant pair reconstructed from server+returner; "
                "US Open 2024; gender->tour consistency when available; unique canonical match"
            ),
            "feature_policy": (
                "research_post_match_only; same-match fields forbidden as pre-match features; "
                "eligible only for strictly lagged chronological player-state experiments"
            ),
        }
        output.append(row)
        counts["linked_matches"] += 1
        if player1_agg["speed_observations"] and player2_agg["speed_observations"]:
            counts["both_players_speed"] += 1

    seen = set()
    duplicates = []
    for row in output:
        if row["match_id"] in seen:
            duplicates.append(row["match_id"])
        seen.add(row["match_id"])
    if duplicates:
        raise RuntimeError(f"Duplicate canonical links: {duplicates[:10]}")

    report = {
        "schema": 2,
        "status": "verified",
        "source": SOURCE,
        "license": LICENSE,
        "source_rows": int(len(frame)),
        "actual_source_columns": list(map(str, frame.columns)),
        "counts": dict(counts),
        "identity_safety": identity_safety,
        "production_mutated": False,
        "canonical_history_mutated": False,
        "model_promoted": False,
        "feature_policy": (
            "same-match serve metadata is post-match; sidecar only; "
            "future model use must be chronological and strictly lagged"
        ),
        "review": review[:500],
    }
    return output, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--history-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    frame = pd.read_parquet(args.metadata)
    matches = load_partitions(Path(args.history_dir))
    rows, report = link(frame, matches)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(out / "usopen-2024-serve-metadata.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "source_rows": report["source_rows"],
        "linked_matches": (report["counts"] or {}).get("linked_matches", 0),
        "both_players_speed": (report["counts"] or {}).get("both_players_speed", 0),
    }, indent=2))


if __name__ == "__main__":
    main()
