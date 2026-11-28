#!/usr/bin/env python3
"""Evaluate the point model against the frozen candidate on local inputs only."""
import argparse
import csv
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
from math import log, log1p, sqrt
from pathlib import Path
from statistics import mean
from time import perf_counter

import pandas as pd

from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.match_format import exact_best_of_from_score_stats
from tbt.models.point_model import PointHistory, competition, timestamp
from tbt.services.data_quality import audit_history
from tbt.services.training import _holdout_fingerprint

HOLDOUT_SHA = "2c7a1af7eea0891ad3f67fc0d8aa8ac62fedc7182db112c12da56c5248cbfcbe"
CANDIDATE_SHA = "7f0d664c12889e7cb8943deda9d4bfc3d612f0a86866fe7c5ff038ebd17543e5"


def binary_metrics(pairs):
    if not pairs:
        return {"n": 0}
    probabilities = [(min(1 - 1e-12, max(1e-12, p)), y) for p, y in pairs]
    return {
        "n": len(pairs),
        "log_loss": mean(-log(p) if y else -log1p(-p) for p, y in probabilities),
        "brier": mean((p - y) ** 2 for p, y in pairs),
    }


def reliability(pairs):
    bins = defaultdict(list)
    for p, y in pairs:
        bins[min(int(p * 10), 9)].append((p, y))
    return [{"bin": index, "n": len(rows), "p": mean(p for p, _ in rows), "y": mean(y for _, y in rows)}
            for index, rows in sorted(bins.items())]


def score_values(match, best):
    if (match.provider_payload or {}).get("_tbt_termination"):
        return None
    stats = match.stats
    if exact_best_of_from_score_stats(stats)[0] != best:
        return None
    a, b = (int(stats[f"p{i}_sets_won"]) for i in (1, 2))
    if (a > b) != (match.winner_id == match.player1_id):
        return None
    return f"{a}:{b}"


def games_values(match, score):
    if score is None:
        return None
    a, b, total = (match.stats.get(k) for k in ("p1_games_won", "p2_games_won", "total_games"))
    sets = sum(map(int, score.split(":")))
    if (any(v is None or v < 0 or int(v) != v for v in (a, b, total))
            or a + b != total or not 6 * sets <= total <= 13 * sets):
        return None
    return a, b


def evaluate_match(groups, match, row, card):
    winner = int(match.winner_id == match.player1_id)
    for group in groups:
        group["winner/point"].append((card["favorite"]["value"]["probabilities"][0], winner))
        group["winner/Elo"].append((card["form_vs_elo"]["value"]["elo_probability"][0], winner))
        group["winner/candidate"].append((float(row["p"]), winner))
    score = score_values(match, card["best_of"])
    if score:
        for label, p in card["set_score"]["value"].items():
            for group in groups:
                group[f"sets/BO{card['best_of']} {label}"].append((p, int(label == score)))
    games = games_values(match, score)
    if games:
        projections = card["other_projections"]["value"]
        for line, sides in projections["totals"].items():
            for group in groups:
                group[f"games/over {line}"].append((sides["over"], int(sum(games) > float(line))))
                group[f"games/under {line}"].append((sides["under"], int(sum(games) < float(line))))
        for line, probabilities in projections["handicap"].items():
            for i, p in enumerate(probabilities):
                y = int(games[i] - games[1 - i] + float(line) > 0)
                for group in groups:
                    group[f"handicap/P{i + 1} {line}"].append((p, y))
    if (match.provider_payload or {}).get("_tbt_termination"):
        return
    for index, side in enumerate(card["predicted_stats"]["value"], 1):
        for key in ("aces", "double_faults"):
            actual = match.stats.get(f"p{index}_{key}")
            predicted = side[key]["value"]
            if (isinstance(predicted, (int, float)) and isinstance(actual, (int, float))
                    and 0 <= actual <= 100 and int(actual) == actual):
                for group in groups:
                    group[f"count/{key}"].append((predicted, actual))


def summarize(group):
    result = {}
    for key, rows in sorted(group.items()):
        if key.startswith("count/"):
            residual = [p - y for p, y in rows]
            result[key] = {"n": len(rows), "mae": mean(abs(e) for e in residual),
                           "rmse": sqrt(mean(e * e for e in residual)), "bias": mean(residual)}
        else:
            result[key] = binary_metrics(rows)
            result[key]["bins"] = reliability(rows)
    return result


def plots(groups, output):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    panels = {
        "winner": ("Víťaz zápasu", ["point", "candidate", "Elo"]),
        "sets": ("Skóre na sety", ["BO3 2:0", "BO3 2:1", "BO3 0:2", "BO3 1:2"]),
        "games": ("Celkové gemy · over", ["over 19.5", "over 20.5", "over 21.5"]),
        "handicap": ("Handicap gemov · hráč 1", ["P1 -3.5", "P1 -1.5", "P1 +1.5", "P1 +3.5"]),
    }
    for market, (title, events) in panels.items():
        fig, axes = plt.subplots(3, 3, figsize=(11, 10), sharex=True, sharey=True, layout="constrained")
        selected = ("all", "ATP", "WTA", "Challenger", "ITF", "WTA 125",
                    "quality/supported", "quality/low", "quality/elo_fallback")
        for ax, name in zip(axes.flat, selected):
            ax.plot([0, 1], [0, 1], "--", color=".65", linewidth=1)
            usable = False
            for event in events:
                metric = groups.get(name, {}).get(f"{market}/{event}", {})
                bins = metric.get("bins", [])
                if bins:
                    usable = True
                    ax.plot([b["p"] for b in bins], [b["y"] for b in bins], "-", linewidth=.8,
                            alpha=.7, label=f"{event} ({metric['n']:,})")
                    color = ax.lines[-1].get_color()
                    ax.scatter([b["p"] for b in bins], [b["y"] for b in bins],
                               s=[max(8, 1.9 * sqrt(b["n"])) for b in bins], color=color, alpha=.8)
            ax.set(title=name, xlim=(0, 1), ylim=(0, 1), aspect="equal")
            ax.grid(alpha=.2)
            if usable:
                ax.legend(fontsize=7, loc="upper left")
            else:
                ax.text(.5, .15, "Bez pozorovaní", ha="center")
        fig.suptitle(f"{title} · holdout 27.10.–22.11.2026", fontsize=15)
        fig.supxlabel("Priemerná predikovaná pravdepodobnosť")
        fig.supylabel("Pozorovaná frekvencia")
        fig.savefig(output / f"50-{market}.png", dpi=140)
        plt.close(fig)


def run(history_dir, candidate_path, output):
    candidate_sha = sha256(candidate_path.read_bytes()).hexdigest()
    if candidate_sha != CANDIDATE_SHA:
        raise ValueError("Expected the frozen per-match candidate replay export")
    with candidate_path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    expected = {r["match_id"]: r for r in rows}
    frame = pd.DataFrame(rows)
    frame["scheduled_at"] = pd.to_datetime(frame["scheduled_at"], utc=True, format="mixed")
    if len(rows) != len(expected) or len(expected) != 9623 or _holdout_fingerprint(frame) != HOLDOUT_SHA:
        raise ValueError("Unexpected candidate holdout")
    reference = binary_metrics([(float(r["p"]), int(r["target"])) for r in rows])
    start = perf_counter()
    matches, identity = sanitize_history_identities(load_partitions(history_dir, years=range(2023, 2027)))
    matches, audit = audit_history(matches, now=frame["scheduled_at"].max().to_pydatetime() + timedelta(microseconds=1))
    restored = perf_counter()
    replay = PointHistory(matches)
    by_id = {m.match_id: m for m in matches if m.match_id in expected}
    if by_id.keys() != expected.keys():
        raise ValueError(f"Frozen CDB cohort mismatch: {len(expected.keys() - by_id.keys())} missing matches")
    grouped = defaultdict(lambda: defaultdict(list))
    timings, daily, skipped = [], defaultdict(list), defaultdict(int)
    for m in sorted(by_id.values(), key=lambda m: (m.scheduled_at, m.match_id)):
        row = expected[m.match_id]
        if timestamp(row["scheduled_at"]) != m.scheduled_at or row["winner_id"] != m.winner_id:
            raise ValueError(f"Frozen outcome mismatch for {m.match_id}")
        if row["player1_id"] != m.player1_id:
            m = m.swapped()
        if ((row["player1_id"], row["player2_id"]) != (m.player1_id, m.player2_id)
                or int(row["target"]) != (m.winner_id == m.player1_id)):
            raise ValueError(f"Frozen orientation mismatch for {m.match_id}")
        replay.advance(m.scheduled_at - timedelta(microseconds=1))
        before = perf_counter()
        card = replay.card(replace(m, stats={}, provider_payload={}, winner_id=None,
                                   status="upcoming", best_of=None))
        elapsed = perf_counter() - before
        if card is None:
            skipped[competition(m)] += 1
            continue
        timings.append(elapsed)
        daily[m.scheduled_at.date().isoformat()].append(elapsed)
        keys = ("all", card["competition"], f"quality/{card['data_quality']}",
                f"{card['competition']}/{card['data_quality']}")
        evaluate_match([grouped[key] for key in keys], m, row, card)
    groups = {key: summarize(values) for key, values in sorted(grouped.items())}
    results = {
        "holdout_n": len(rows), "holdout_fingerprint": HOLDOUT_SHA,
        "candidate_csv_sha256": candidate_sha,
        "candidate_reference": reference,
        "history_manifest_sha256": sha256((history_dir / "history_manifest.json").read_bytes()).hexdigest(),
        "history_accepted": audit["accepted"], "skipped": skipped, "groups": groups,
        "performance": {
            "input_seconds": restored - start, "replay_seconds": perf_counter() - restored,
            "median_match_ms": 1000 * sorted(timings)[len(timings) // 2],
            "p95_match_ms": 1000 * sorted(timings)[int(.95 * len(timings))],
            "daily": {day: {"n": len(values), "seconds": sum(values)} for day, values in daily.items()},
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "evaluation.json").write_text(json.dumps(results, indent=2, allow_nan=False), encoding="utf-8")
    plots(groups, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True, help="Frozen per-match candidate CSV")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.history, args.candidate, args.out)
