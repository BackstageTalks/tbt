"""Link the CC BY 4.0 CVPRW 2026 tennis serve metadata to BlinQ history.

The source is the small metadata.parquet (5,966 serves / 113 US Open 2024
matches) from jasnwag/tennis_serve_dataset. Output is a private research
sidecar only. Same-match serve outcomes are post-match observations and are
never promoted directly to pre-match model features.
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


def _round(value: Any) -> str:
    text = norm_text(value)
    aliases = {
        "final": "f", "f": "f",
        "semifinal": "sf", "semifinals": "sf", "semi final": "sf", "sf": "sf",
        "quarterfinal": "qf", "quarterfinals": "qf", "quarter final": "qf", "qf": "qf",
        "round of 16": "r16", "r16": "r16",
        "round of 32": "r32", "r32": "r32",
        "round of 64": "r64", "r64": "r64",
        "round of 128": "r128", "r128": "r128",
        "first round": "r128", "second round": "r64", "third round": "r32",
        "fourth round": "r16",
    }
    return aliases.get(text, text)


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
    required = {
        "match_id", "server", "player1", "player2", "Speed_KMH",
        "SetNo", "GameNo", "PointNumber", "ServeNumber", "ServeResult",
        "round", "ElapsedTime",
    }
    missing = sorted(required - set(map(str, frame.columns)))
    if missing:
        raise ValueError(f"Missing serve metadata columns: {missing}")

    for source_match_id, group in frame.groupby("match_id", dropna=False, sort=False):
        if pd.isna(source_match_id):
            continue
        p1_values = [str(x).strip() for x in group["player1"].dropna().unique() if str(x).strip()]
        p2_values = [str(x).strip() for x in group["player2"].dropna().unique() if str(x).strip()]
        if len(p1_values) != 1 or len(p2_values) != 1:
            yield {
                "source_match_id": str(source_match_id),
                "invalid_identity": True,
                "rows": group,
            }
            continue
        rounds = [str(x).strip() for x in group["round"].dropna().unique() if str(x).strip()]
        yield {
            "source_match_id": str(source_match_id),
            "player1": p1_values[0],
            "player2": p2_values[0],
            "round": rounds[0] if len(rounds) == 1 else "",
            "rows": group,
        }


def _aggregate_player(rows: pd.DataFrame, player_name: str) -> dict[str, Any]:
    target = norm_text(player_name)
    selected = rows[rows["server"].map(norm_text) == target]
    speeds = [
        value for value in (_num(x) for x in selected["Speed_KMH"].tolist())
        if value is not None and 40 <= value <= 280
    ]
    first = [
        _num(speed)
        for speed, serve_no in zip(selected["Speed_KMH"], selected["ServeNumber"])
        if _int(serve_no) == 1 and _num(speed) is not None
    ]
    first = [x for x in first if x is not None and 40 <= x <= 280]
    second = [
        _num(speed)
        for speed, serve_no in zip(selected["Speed_KMH"], selected["ServeNumber"])
        if _int(serve_no) == 2 and _num(speed) is not None
    ]
    second = [x for x in second if x is not None and 40 <= x <= 280]

    results = Counter(norm_text(x) for x in selected["ServeResult"].dropna().tolist())
    sets = {_int(x) for x in selected["SetNo"].dropna().tolist()}
    games = {
        (_int(s), _int(g))
        for s, g in zip(selected["SetNo"], selected["GameNo"])
        if _int(s) is not None and _int(g) is not None
    }

    def mean(values):
        return (sum(values) / len(values)) if values else None

    return {
        "serve_rows": int(len(selected)),
        "speed_observations": len(speeds),
        "speed_kmh_mean": mean(speeds),
        "speed_kmh_median": median(speeds) if speeds else None,
        "speed_kmh_max": max(speeds) if speeds else None,
        "first_serve_speed_kmh_mean": mean(first),
        "second_serve_speed_kmh_mean": mean(second),
        "serve_number_1_rows": int(sum(_int(x) == 1 for x in selected["ServeNumber"])),
        "serve_number_2_rows": int(sum(_int(x) == 2 for x in selected["ServeNumber"])),
        "serve_result_counts": dict(results),
        "sets_observed": len({x for x in sets if x is not None}),
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
            continue

        p1, p2 = source["player1"], source["player2"]
        pair = tuple(sorted((norm_text(p1), norm_text(p2))))
        candidates = list(index.get(pair, []))
        if source.get("round") and len(candidates) > 1:
            sr = _round(source["round"])
            exact = [m for m in candidates if _round(m.round_name) == sr]
            if exact:
                candidates = exact

        if not candidates:
            counts["unmatched"] += 1
            review.append({
                "source_match_id": source["source_match_id"],
                "reason": "unmatched",
                "player1": p1,
                "player2": p2,
                "round": source.get("round"),
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
        if norm_text(p1) == mp1 and norm_text(p2) == mp2:
            source_for_canonical = ((p1, match.player1_name), (p2, match.player2_name))
        elif norm_text(p1) == mp2 and norm_text(p2) == mp1:
            source_for_canonical = ((p2, match.player1_name), (p1, match.player2_name))
        else:
            counts["orientation_failed"] += 1
            continue

        player1_agg = _aggregate_player(rows, source_for_canonical[0][0])
        player2_agg = _aggregate_player(rows, source_for_canonical[1][0])
        row = {
            "schema": 1,
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
            "evidence": "exact normalized player pair + US Open 2024 + unique canonical match; round used only as disambiguator",
            "feature_policy": "research_post_match_only; eligible only for lagged chronological player-state experiments",
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
        "schema": 1,
        "status": "verified",
        "source": SOURCE,
        "license": LICENSE,
        "source_rows": int(len(frame)),
        "counts": dict(counts),
        "identity_safety": identity_safety,
        "production_mutated": False,
        "canonical_history_mutated": False,
        "model_promoted": False,
        "feature_policy": "same-match serve metadata is post-match; sidecar only; future use must be strictly lagged",
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
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "source_rows": report["source_rows"],
        "linked_matches": (report["counts"] or {}).get("linked_matches", 0),
        "both_players_speed": (report["counts"] or {}).get("both_players_speed", 0),
    }, indent=2))


if __name__ == "__main__":
    main()
