#!/usr/bin/env python3
"""Zero-request audit for BlinQ Data Model v3 feature source coverage."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from statistics import mean, median
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.services.feature_builder import stats_surface_key


def _present(stats: dict, keys: tuple[str, ...]) -> bool:
    return all(stats.get(key) is not None for key in keys)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", default=".cache/tbt/history")
    ap.add_argument("--out", default=".cache/tbt/feature-v3/coverage.json")
    args = ap.parse_args()

    raw = load_partitions(Path(args.history_dir))
    matches, identity = sanitize_history_identities(raw)
    total = len(matches)
    counts = Counter()
    by_surface = Counter()
    by_round = Counter()
    rich_signal_values = defaultdict(list)
    rich_signal_present = Counter()

    for match in matches:
        stats = match.stats if isinstance(match.stats, dict) else {}
        surface = stats_surface_key(match.surface)
        if surface != "unknown":
            by_surface[surface] += 1
        if str(match.round_name or "").strip():
            by_round[str(match.round_name).strip().lower()] += 1
        if _present(stats, ("p1_service_points_won", "p2_service_points_won", "p1_return_points_won", "p2_return_points_won")):
            counts["serve_return_complete"] += 1

        rich_pairs = {
            "rich_first_strike_serve": ("p1_first_strike_serve_win", "p2_first_strike_serve_win"),
            "rich_return_in_play": ("p1_return_in_play_rate", "p2_return_in_play_rate"),
            "rich_return_depth": ("p1_return_deep_rate", "p2_return_deep_rate"),
            "rich_break_point_serve": ("p1_break_point_serve_win", "p2_break_point_serve_win"),
            "rich_break_point_return": ("p1_break_point_return_win", "p2_break_point_return_win"),
            "rich_net_efficiency": ("p1_net_points_win", "p2_net_points_win"),
            "rich_attacking_rate": ("p1_attacking_points_rate", "p2_attacking_points_rate"),
            "rich_unforced_error_rate": ("p1_unforced_error_rate", "p2_unforced_error_rate"),
        }
        rich_complete = 0
        rich_any = False
        for label, keys in rich_pairs.items():
            present = _present(stats, keys)
            if present:
                counts[label] += 1
                rich_complete += 1
                rich_any = True
        if rich_any:
            counts["rich_charting_any"] += 1
        if rich_complete == len(rich_pairs):
            counts["rich_charting_full"] += 1

        # Descriptive only: measure whether the historical match winner had the
        # expected directional advantage in each specialist rate. This does not
        # feed outcomes back into FeatureBuilder and is not a promotion test.
        if match.winner_id in {match.player1_id, match.player2_id}:
            attack1 = stats.get("p1_attacking_points_rate")
            attack2 = stats.get("p2_attacking_points_rate")
            ue1 = stats.get("p1_unforced_error_rate")
            ue2 = stats.get("p2_unforced_error_rate")
            aggression1 = (
                float(attack1) - float(ue1)
                if attack1 is not None and ue1 is not None else None
            )
            aggression2 = (
                float(attack2) - float(ue2)
                if attack2 is not None and ue2 is not None else None
            )
            signals = {
                "first_strike_serve": (
                    stats.get("p1_first_strike_serve_win"),
                    stats.get("p2_first_strike_serve_win"),
                    1.0,
                ),
                "return_in_play": (
                    stats.get("p1_return_in_play_rate"),
                    stats.get("p2_return_in_play_rate"),
                    1.0,
                ),
                "return_depth": (
                    stats.get("p1_return_deep_rate"),
                    stats.get("p2_return_deep_rate"),
                    1.0,
                ),
                "break_point_serve": (
                    stats.get("p1_break_point_serve_win"),
                    stats.get("p2_break_point_serve_win"),
                    1.0,
                ),
                "break_point_return": (
                    stats.get("p1_break_point_return_win"),
                    stats.get("p2_break_point_return_win"),
                    1.0,
                ),
                "net_efficiency": (
                    stats.get("p1_net_points_win"),
                    stats.get("p2_net_points_win"),
                    1.0,
                ),
                "aggression_balance": (
                    aggression1,
                    aggression2,
                    1.0,
                ),
            }
            for label, (value1, value2, direction) in signals.items():
                if value1 is None or value2 is None:
                    continue
                value1, value2 = float(value1), float(value2)
                rich_signal_present[label] += 1
                if abs(value1 - value2) <= 1e-12:
                    continue
                winner_value = value1 if match.winner_id == match.player1_id else value2
                loser_value = value2 if match.winner_id == match.player1_id else value1
                rich_signal_values[label].append(
                    float(direction) * (winner_value - loser_value)
                )
        if _present(stats, ("total_sets", "total_games")):
            counts["structured_score"] += 1
        if _present(stats, ("p1_first_set_won", "p2_first_set_won", "p1_second_set_won", "p2_second_set_won")):
            counts["set1_set2_outcomes"] += 1
        if stats.get("deciding_set") is not None:
            counts["deciding_set"] += 1
        if str(match.tournament_id or "").strip():
            counts["tournament_id"] += 1
        if str(match.round_name or "").strip():
            counts["round"] += 1
        if match.player1_rank is not None and match.player2_rank is not None:
            counts["rank_both"] += 1

    coverage = {
        key: {
            "matches": int(value),
            "rate": (float(value) / total if total else 0.0),
        }
        for key, value in sorted(counts.items())
    }
    rich_signal_directional = {}
    for label in sorted(rich_signal_present):
        values = rich_signal_values.get(label, [])
        rich_signal_directional[label] = {
            "matches_present": int(rich_signal_present[label]),
            "matches_compared": int(len(values)),
            "directional_accuracy": (
                float(sum(value > 0 for value in values)) / len(values)
                if values else None
            ),
            "mean_winner_advantage": float(mean(values)) if values else None,
            "median_winner_advantage": float(median(values)) if values else None,
        }

    payload = {
        "schema": 1,
        "model": "blinq-data-model-v3",
        "zero_request_audit": True,
        "rows": total,
        "identity_safety": identity,
        "coverage": coverage,
        "rich_signal_directional": rich_signal_directional,
        "surface_rows": dict(by_surface.most_common()),
        "round_rows_top25": dict(by_round.most_common(25)),
        "feature_sources": {
            "surface_serve_return": "history.stats + surface",
            "surface_h2h": "chronological history replay",
            "set_game_workload": "structured score totals",
            "deciding_set": "structured score deciding_set",
            "lost_set1_recovery": "set1/set2 outcomes",
            "closing": "first-set outcome + final winner",
            "round_form": "historical round_name",
            "tournament_history": "historical tournament_id/name",
            "pbp_pressure": "reserved canonical enrichment; not enabled until provider path/payload is verified",
            "odds_consensus": "reserved enrichment; existing event odds remain source of current VALUE markets",
        },
    }
    target = ROOT / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
