"""Reproduce training-only service calibration and paired v1/v2 market reliability."""
import argparse
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evaluate_point_model import (CANDIDATE_SHA, binary_metrics, competition, games_values,
                                  reliability, score_values)
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.models.feature_builder import stats_surface_key
from tbt.models.point_anchor import anchored_rates, calibrated_mean
from tbt.models.point_model import PointHistory, _ready_times, timestamp, format_for
from tbt.models.point_rules import calibration_level, rules_for, score_audit
from tbt.models.point_simulation import TOTAL_LINES, simulate
from tbt.services.data_quality import audit_history

UTC = timezone.utc
TRAIN_START = datetime(2024, 1, 1, tzinfo=UTC)
TRAIN_END = datetime.fromisoformat("2026-04-27T22:40:44+00:00")
HOLDOUT_END = datetime.fromisoformat("2026-11-22T17:10:00+00:00")
GRID = (-.10, -.075, -.05, -.025, 0., .025, .05, .075, .10)


def read_history(directory, years):
    rows, _ = sanitize_history_identities(load_partitions(directory, years=years))
    return audit_history(rows, now=datetime(2026, 11, 28, tzinfo=UTC))[0]


def fixture(match):
    return replace(match, stats={}, provider_payload={}, winner_id=None, status="upcoming", best_of=None)


def sample_training(history):
    buckets = defaultdict(list)
    for m in history:
        if not TRAIN_START <= m.scheduled_at < TRAIN_END:
            continue
        ready = _ready_times(m)[1]
        if ready is None or ready >= TRAIN_END:
            continue
        rules = rules_for(m)
        # A deciding match tiebreak is systematically absent from the eligible
        # frozen qualifying labels. Borrow the tour/surface main-draw prior.
        if not rules or rules.match_tiebreak or score_audit(m, format_for(fixture(m))[0], rules)[1] is None:
            continue
        key = calibration_level(m), stats_surface_key(m.surface)
        buckets[key].append(m)
    # Equal capped samples per surface, deterministic and independent of score.
    picked = []
    for rows in buckets.values():
        rows.sort(key=lambda m: hashlib.sha256(m.match_id.encode()).digest())
        picked.extend(rows[:400])
    return sorted(picked, key=lambda m: (m.scheduled_at, m.match_id))


def fit(history):
    replay = PointHistory(history)
    buckets = defaultdict(list)
    for match in sample_training(history):
        replay.advance(match.scheduled_at - timedelta(microseconds=1))
        card = replay.card(fixture(match))
        if not card or card["best_of"] != 3:
            continue
        mean = sum(r["serve_point"] for r in card["serve_return"]["value"]) / 2
        # During candidate training no out-of-sample frozen candidate is available.
        # Use the pre-match Elo as a strength proxy for fitting the totals only.
        strength = round(max(card["form_vs_elo"]["value"]["elo_probability"]), 2)
        strength = min(.99, strength)
        rules = rules_for(match)
        observed = sum(score_audit(match, 3, rules)[1])
        residuals = []
        for offset in GRID:
            mu = round(calibrated_mean(mean, offset), 2)
            points = anchored_rates(mu, strength, 3, card["deciding_tiebreak_to"], rules)
            totals = simulate(*points, 3, card["deciding_tiebreak_to"], rules)["totals"]
            residuals.append([totals[str(line)]["over"] - (observed > line) for line in TOTAL_LINES])
        level = calibration_level(match)
        for key in ("all", level, f"{level}|{stats_surface_key(match.surface)}"):
            buckets[key].append(residuals)
    groups = {}
    for key, rows in buckets.items():
        if key != "all" and len(rows) < 40:
            continue
        def loss(i):
            return sum((sum(row[i][j] for row in rows) / len(rows)) ** 2 for j in range(3))
        index = min(range(len(GRID)), key=lambda i: (loss(i), abs(GRID[i])))
        groups[key] = {"offset": GRID[index], "n": len(rows)}
    return {"train_end": TRAIN_END.isoformat(), "groups": groups}


def observations(card, m):
    yield "winner", card["favorite"]["value"]["probabilities"][0], int(m.winner_id == m.player1_id)
    score = score_values(m, card["best_of"])
    if not score:
        return
    for label, p in card["set_score"]["value"].items():
        yield f"sets/{label}", p, int(score == label)
    other = card["other_projections"]["value"]
    tb = m.stats.get("tiebreak_sets")
    if isinstance(tb, (int, float)) and tb == int(tb) and 0 <= tb <= sum(map(int, score.split(":"))):
        yield "tiebreak", other["tiebreak"], int(tb > 0)
    _, games = score_audit(m, card["best_of"], rules_for(m))
    if games:
        for line, sides in other["totals"].items():
            for side, p in sides.items():
                yield f"{side}/{line}", p, int((sum(games) > float(line)) == (side == "over"))
        for line, sides in other["handicap"].items():
            for i, p in enumerate(sides):
                yield f"handicap/P{i+1}/{line}", p, int(games[i] - games[1-i] + float(line) > 0)


def evaluate(history, rows, groups):
    replay = PointHistory(history)
    records = {m.match_id: m for m in history}
    metrics = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    maximum = 0.
    for row in sorted(rows, key=lambda r: (datetime.fromisoformat(r["scheduled_at"]), r["match_id"])):
        m = records[row["match_id"]]
        if m.player1_id != row["player1_id"]:
            m = m.swapped()
        if ([m.player1_id, m.player2_id, m.winner_id] != [row[k] for k in ("player1_id","player2_id","winner_id")]
                or m.scheduled_at != datetime.fromisoformat(row["scheduled_at"])):
            raise ValueError("Candidate pairing mismatch")
        p = float(row["p"])
        replay.advance(m.scheduled_at - timedelta(microseconds=1))
        for arm, options in (("v1", {}), ("v2", {"candidate": p, "offsets": groups})):
            card = replay.card(fixture(m), **options)
            if not card:
                raise ValueError("Unsupported fixture")
            if arm == "v2":
                maximum = max(maximum, abs(card["favorite"]["value"]["probabilities"][0]-p))
            for market, probability, y in observations(card, m):
                for key in ("all", competition(m), card["data_quality"]):
                    metrics[key][market][arm].append((probability, y))
    for markets in metrics.values():
        for arms in markets.values():
            for arm, pairs in arms.items():
                bins = reliability(pairs)
                arms[arm] = {**binary_metrics(pairs), "bins": bins,
                             "ece": sum(b["n"] * abs(b["p"]-b["y"]) for b in bins)/len(pairs)}
    if maximum > .005:
        raise AssertionError(maximum)
    return {"n": len(rows), "max_anchor_error": maximum, "metrics": metrics}


def archived_rows(history, path):
    """Strictly paired, issued ATP/WTA predictions for a separate temporal sensitivity check."""
    index = defaultdict(list)
    for match in history:
        if competition(match) in ("ATP", "WTA") and TRAIN_END < match.scheduled_at <= HOLDOUT_END:
            event = str(match.provider_payload.get("_tbt_provider_event_id") or "")
            index[event, match.scheduled_at, frozenset((match.player1_id, match.player2_id))].append(match)
    selected = {}
    for row in json.loads(path.read_bytes()):
        when = timestamp(row.get("scheduled_at"))
        issued = timestamp(row.get("issued_at"))
        settled = timestamp((row.get("result") or {}).get("settled_at"))
        if (not when or not issued or not settled or not TRAIN_END < issued < when < settled
                or row.get("publication_status") != "published" or not row.get("model_version")):
            continue
        a, b = row.get("player1") or {}, row.get("player2") or {}
        ids = str(a.get("id")), str(b.get("id"))
        matches = index.get((str(row.get("event_id")), when, frozenset(ids)), [])
        p, q = a.get("probability"), b.get("probability")
        if (len(matches) != 1 or not isinstance(p, (int,float)) or not isinstance(q,(int,float))
                or not 0 < p < 1 or abs(p+q-1) > .0001):
            continue
        match = matches[0]
        if format_for(fixture(match))[0] not in (3, 5):
            continue
        if match.winner_id != str(row["result"].get("winner_id")):
            continue
        old = selected.get(match.match_id)
        if old is None or issued < old[0]:
            selected[match.match_id] = (issued, {"match_id":match.match_id,"scheduled_at":when.isoformat(),
                "player1_id":ids[0],"player2_id":ids[1],"winner_id":match.winner_id,"p":p})
    return [item[1] for item in selected.values()]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("history","candidate","out"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--fit", action="store_true", help="Refit from frozen training outcomes and export a local copy")
    parser.add_argument("--issued-ledger", type=Path)
    args = parser.parse_args()
    if hashlib.sha256(args.candidate.read_bytes()).hexdigest() != CANDIDATE_SHA:
        raise ValueError("Wrong frozen candidate replay")
    if hashlib.sha256((args.history / "history_manifest.json").read_bytes()).hexdigest() != "abdcbb7770ba6495ac9636bffc12345d0a56339a43e68a5c659f96cfab3aeb99":
        raise ValueError("Expected the frozen candidate history manifest")
    rows = list(csv.DictReader(args.candidate.open(encoding="utf-8")))
    history = read_history(args.history, range(2023, 2027))
    args.out.mkdir(parents=True, exist_ok=True)
    cal_path = Path(__file__).with_name("point_calibration_v2.json")
    if args.issued_ledger:
        cal = json.loads(cal_path.read_bytes())
        rows = archived_rows(history, args.issued_ledger)
        if not rows:
            raise ValueError("No eligible timestamped historical predictions")
        name = "extended"
    else:
        if args.fit:
            cal = fit(history)
            (args.out / cal_path.name).write_text(json.dumps(cal, indent=2, sort_keys=True), encoding="utf-8")
        else:
            cal = json.loads(cal_path.read_bytes())
        name = "holdout"
    result = evaluate(history, rows, cal["groups"])
    result["start"] = min(r["scheduled_at"] for r in rows)
    result["end"] = max(r["scheduled_at"] for r in rows)
    result["anchor_source"] = "issued historical models" if args.issued_ledger else "blinq-candidate-frozen-45525499354-1"
    (args.out / (name+".json")).write_text(json.dumps(result), encoding="utf-8")
