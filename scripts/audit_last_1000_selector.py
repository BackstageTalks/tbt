"""Read-only optimization study for selecting 3-5 strongest BlinQ picks from the latest 1000 settled issued selections.

No provider calls, production writes, selector edits, or model promotion.  The
study uses only information available at issuance and evaluates chronologically.
Short Odds / PRIME is intentionally excluded.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import itertools
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from _bootstrap import ROOT
from audit_top_reliability import download, issued_snapshot, number, timestamp

SECTIONS = {"top_daily", "value", "ace", "double_faults", "sets", "games", "doubles"}
VOID = {"void", "push", "cancelled", "canceled", "postponed", "walkover", "walk over", "w/o",
        "retired", "ret", "abandoned", "interrupted", "suspended", "no_action"}


def betting_day(issued):
    return (issued.astimezone(ZoneInfo("Europe/Bratislava")) - timedelta(hours=6)).date().isoformat()


def competition(row):
    level = str(row.get("competition") or row.get("tournament_level") or "").lower()
    tournament = str(row.get("tournament") or "").lower()
    tour = str(row.get("tour") or "").lower()
    if "itf" in level or "itf" in tournament:
        return "ITF"
    if "challenger" in level or "challenger" in tournament:
        return "Challenger"
    if "wta" in tour or "wta" in level:
        return "WTA"
    if "atp" in tour or "atp" in level:
        return "ATP"
    return "unknown"


def semantic_key(row, pub):
    event = str(row.get("event_id") or row.get("id") or row.get("match_id") or "").strip()
    section = str(pub.get("section") or "").strip()
    market = str(pub.get("market") or pub.get("market_type") or section).strip().lower()
    selection = str(pub.get("selection_id") or pub.get("selection") or pub.get("pick") or "").strip().lower()
    return "|".join((event, section, market, selection)) if event and selection else None


def pub_probability(pub):
    snap = issued_snapshot(pub)
    for source in (snap if isinstance(snap, dict) else {}, pub):
        for key in ("blinq_probability", "model_probability", "probability", "confidence"):
            value = number(source.get(key))
            if value is not None:
                if value > 1 and value <= 100:
                    value /= 100.0
                if .5 <= value <= 1:
                    return value
    return None


def pub_depth(row, pub):
    snap = issued_snapshot(pub)
    for source in (snap if isinstance(snap, dict) else {}, pub, row):
        for key in ("data_depth", "depth"):
            value = number(source.get(key))
            if value is not None:
                if value > 1 and value <= 100:
                    value /= 100.0
                if 0 <= value <= 1:
                    return value
    return None


def min_surface_matches(row, pub):
    snap = issued_snapshot(pub)
    quality = snap.get("quality") if isinstance(snap, dict) and isinstance(snap.get("quality"), dict) else row.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    values = []
    for side in ("player1", "player2"):
        data = quality.get(side) if isinstance(quality.get(side), dict) else {}
        value = number(data.get("surface_matches"))
        if value is not None and value >= 0:
            values.append(value)
    return min(values) if len(values) == 2 else None


def extract(ledger, limit):
    dedup = {}
    for row in ledger:
        if not isinstance(row, dict):
            continue
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict) or str(pub.get("section") or "") not in SECTIONS:
                continue
            issued = timestamp(pub.get("issued_at"))
            result = pub.get("result") if isinstance(pub.get("result"), dict) else {}
            scheduled = timestamp(result.get("scheduled_at") or row.get("scheduled_at"))
            if issued is None or scheduled is None or issued >= scheduled:
                continue
            if pub.get("excluded_reason") or pub.get("publication_status") in {"pending", "expired_unpublished"}:
                continue
            status = str(result.get("status") or "").lower()
            if status in VOID or result.get("void") is True or result.get("is_void") is True:
                continue
            correct = result.get("correct")
            if correct not in (True, False):
                continue
            key = semantic_key(row, pub)
            if key is None:
                continue
            previous = dedup.get(key)
            if previous is not None and previous["issued"] <= issued:
                continue
            odds = number(pub.get("odds"))
            odds = odds if odds is not None and odds > 1 else None
            fair = number(pub.get("fair_implied_probability"))
            market_p = fair if fair is not None and 0 < fair < 1 else (1.0 / odds if odds else None)
            dedup[key] = {
                "event_id": str(row.get("event_id") or row.get("id") or row.get("match_id") or ""),
                "section": str(pub.get("section") or ""),
                "tour": str(row.get("tour") or "unknown").lower(),
                "surface": str(row.get("surface") or "unknown").lower(),
                "competition": competition(row),
                "issued": issued,
                "scheduled": scheduled,
                "day": betting_day(issued),
                "correct": bool(correct),
                "model_p": pub_probability(pub),
                "market_p": market_p,
                "depth": pub_depth(row, pub),
                "surface_matches": min_surface_matches(row, pub),
                "odds": odds,
                "exact_snapshot": issued_snapshot(pub) is not None,
            }
    rows = sorted(dedup.values(), key=lambda x: (x["scheduled"], x["issued"], x["event_id"]))
    return rows[-limit:]


def posterior(wins, total, prior, strength):
    return (wins + strength * prior) / (total + strength) if total + strength else prior


def add_past_only_reliability(rows):
    global_w = global_n = 0
    by_section = defaultdict(lambda: [0, 0])
    by_segment = defaultdict(lambda: [0, 0])
    out = []
    for row in rows:
        prior = (global_w + 2.0) / (global_n + 4.0)
        sw, sn = by_section[row["section"]]
        gw, gn = by_segment[(row["section"], row["tour"], row["surface"])]
        section_rel = posterior(sw, sn, prior, 25.0)
        segment_rel = posterior(gw, gn, section_rel, 20.0)
        copy = dict(row)
        copy["prior_global"] = prior
        copy["section_rel"] = section_rel
        copy["segment_rel"] = segment_rel
        copy["surface_evidence"] = None if row["surface_matches"] is None else min(1.0, math.log1p(row["surface_matches"]) / math.log(51.0))
        out.append(copy)
        y = 1 if row["correct"] else 0
        global_w += y
        global_n += 1
        by_section[row["section"]][0] += y
        by_section[row["section"]][1] += 1
        by_segment[(row["section"], row["tour"], row["surface"])][0] += y
        by_segment[(row["section"], row["tour"], row["surface"])][1] += 1
    return out


def blended_score(row, weights):
    features = [
        row.get("model_p"),
        row.get("market_p"),
        row.get("segment_rel"),
        row.get("depth"),
        row.get("surface_evidence"),
    ]
    pairs = [(float(w), float(v)) for w, v in zip(weights, features) if w > 0 and v is not None and math.isfinite(float(v))]
    denom = sum(w for w, _ in pairs)
    return sum(w * v for w, v in pairs) / denom if denom else row.get("segment_rel", .5)


def select_daily(rows, weights, n):
    by_day = defaultdict(list)
    for row in rows:
        scored = dict(row)
        scored["score"] = blended_score(row, weights)
        by_day[row["day"]].append(scored)
    selected = []
    for day, candidates in sorted(by_day.items()):
        candidates.sort(key=lambda r: (r["score"], r.get("model_p") or 0, r.get("market_p") or 0), reverse=True)
        used_events = set()
        for row in candidates:
            if row["event_id"] and row["event_id"] in used_events:
                continue
            selected.append(row)
            if row["event_id"]:
                used_events.add(row["event_id"])
            if sum(1 for x in selected if x["day"] == day) >= n:
                break
    return selected


def metrics(rows):
    if not rows:
        return {"n": 0, "wins": 0, "hit_rate": None, "days": 0, "mean_score": None}
    return {
        "n": len(rows),
        "wins": sum(r["correct"] for r in rows),
        "hit_rate": sum(r["correct"] for r in rows) / len(rows),
        "days": len({r["day"] for r in rows}),
        "mean_score": sum(r.get("score", 0) for r in rows) / len(rows),
    }


def wilson_lower(wins, n, z=1.96):
    if n <= 0:
        return 0.0
    p = wins / n
    d = 1 + z*z/n
    center = p + z*z/(2*n)
    spread = z * math.sqrt((p*(1-p) + z*z/(4*n))/n)
    return (center-spread)/d


def weight_grid(step=.25):
    vals = [0, .25, .5, .75, 1.0]
    for w in itertools.product(vals, repeat=5):
        if abs(sum(w)-1.0) < 1e-9:
            yield w


def best_on_train(train):
    candidates = []
    for weights in weight_grid():
        for n in (3, 4, 5):
            picked = select_daily(train, weights, n)
            m = metrics(picked)
            lower = wilson_lower(m["wins"], m["n"])
            candidates.append((lower, m["hit_rate"] or 0, m["n"], weights, n, m))
    candidates.sort(reverse=True)
    _, _, _, weights, n, m = candidates[0]
    return weights, n, m, candidates[:10]


def section_report(rows):
    result = {}
    for section in sorted(SECTIONS):
        part = [r for r in rows if r["section"] == section]
        if part:
            result[section] = metrics(part)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--out", default=".cache/tbt/last-1000-selector/report.json")
    args = ap.parse_args()
    if args.limit < 300:
        raise ValueError("Need at least 300 settled issued selections")

    ledger = download(args.data_repository, "tbt-predictions-v1", "ledger.json", ROOT/".cache/tbt/last-1000-selector/input")
    rows = add_past_only_reliability(extract(ledger, args.limit))
    if len(rows) < min(args.limit, 300):
        raise ValueError(f"Only {len(rows)} usable issued selections available")

    split = max(200, int(len(rows)*.70))
    train, test = rows[:split], rows[split:]
    weights, chosen_n, train_metrics, leaderboard = best_on_train(train)

    arms = {}
    named = {
        "model_only": (1,0,0,0,0),
        "market_only": (0,1,0,0,0),
        "past_reliability_only": (0,0,1,0,0),
        "market_reliability_50_50": (0,.5,.5,0,0),
        "market_reliability_model": (.15,.55,.30,0,0),
        "conservative_three_way": (.25,.50,.25,0,0),
        "model_reliability_50_50": (.5,0,.5,0,0),
        "tuned_blend": weights,
    }
    for name, w in named.items():
        arms[name] = {}
        for n in (3,4,5):
            arms[name][str(n)] = metrics(select_daily(test,w,n))

    report = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "read_only_last_1000_selection_optimization",
        "provider_requests": 0,
        "production_mutated": False,
        "short_odds_excluded": True,
        "one_pick_per_event": True,
        "usable_rows": len(rows),
        "first_scheduled": rows[0]["scheduled"].isoformat(),
        "last_scheduled": rows[-1]["scheduled"].isoformat(),
        "split": {
            "train_rows": len(train),
            "validation_rows": len(test),
            "train_last_scheduled": train[-1]["scheduled"].isoformat(),
            "validation_first_scheduled": test[0]["scheduled"].isoformat(),
        },
        "training_choice": {
            "weights": {
                "model_probability": weights[0],
                "market_probability": weights[1],
                "past_segment_reliability": weights[2],
                "data_depth": weights[3],
                "surface_evidence": weights[4],
            },
            "daily_n_selected_on_train": chosen_n,
            "train_metrics": train_metrics,
            "objective": "maximize Wilson 95% lower bound of hit rate on chronological training block",
            "top_train_candidates": [
                {"wilson_lower": a, "hit_rate": b, "n": c, "weights": list(w), "daily_n": n, "metrics": m}
                for a,b,c,w,n,m in leaderboard
            ],
        },
        "validation": arms,
        "validation_all_picks": metrics(test),
        "validation_by_section": section_report(test),
        "interpretation": [
            "Only genuine settled pre-match issued selections are used; PRIME/Short Odds is excluded.",
            "Reliability features are expanding and use only prior rows, never the row's own outcome.",
            "Weights and daily count are chosen on the first 70% only; the final 30% is held out chronologically.",
            "At most one selected bet per event is allowed to reduce same-event correlation.",
            "This is selector research, not a model-promotion result. No production selection is changed.",
            "A 1000-selection sample can still be noisy; prospective confirmation is required before deployment.",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "usable_rows": len(rows),
        "weights": report["training_choice"]["weights"],
        "chosen_daily_n": chosen_n,
        "validation_all": report["validation_all_picks"],
        "tuned_validation": report["validation"]["tuned_blend"],
        "model_validation": report["validation"]["model_only"],
        "market_validation": report["validation"]["market_only"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
