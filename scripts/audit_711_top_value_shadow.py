#!/usr/bin/env python3
"""Read-only fixed-issued TOP/VALUE vs 7.1.1 shadow probability audit.

Only immutable pairs captured before actual publication. No historical refit.
NOT a full alternative daily selection replay. No CDB writes, deployment,
training, provider calls or promotion.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

CHAMPION = "v201-20260925T204608601094Z"
CANDIDATE = "v201-20261014T183415325901Z"
CUTOFF = "2026-10-18T00:00:00+00:00"
MIN_EVALUABLE_MATCHED_PICKS = 30
SECTIONS = {"top_daily", "value"}


def stamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    return result.astimezone(timezone.utc) if result.tzinfo is not None else None


def positive_odds(value):
    try:
        x = float(value)
    except (ValueError, TypeError):
        return None
    return x if math.isfinite(x) and x >= 1.5 else None


def fixed_cohort(issued_rows, cutoff):
    """Deduplicate recorded, settled, real-price ATP/WTA singles winner bets."""
    picked = {}
    reasons = Counter()
    for row in issued_rows:
        if not isinstance(row, dict):
            reasons["malformed_ledger_row"] += 1
            continue
        event = str(row.get("event_id") or row.get("id") or row.get("match_id") or "").strip()
        tour = str(row.get("tour") or "").lower()
        for pub in (row.get("market_publications") or []):
            if not isinstance(pub, dict) or pub.get("section") not in SECTIONS or pub.get("market") != "match_winner":
                continue
            result = pub.get("result") if isinstance(pub.get("result"), dict) else {}
            published = stamp(pub.get("issued_at"))
            scheduled = stamp(result.get("scheduled_at") or row.get("scheduled_at"))
            if not published or not scheduled or published >= scheduled or scheduled >= cutoff:
                reasons["invalid_or_outside_issued_time"] += 1
                continue
            if pub.get("excluded_reason") or pub.get("publication_status") in {"pending", "expired_unpublished"}:
                reasons["not_confirmed_issued"] += 1
                continue
            price = positive_odds(pub.get("odds"))
            if price is None:
                reasons["invalid_or_below_1_50_price"] += 1
                continue
            if tour not in {"atp", "wta"}:
                reasons["not_atp_wta_singles"] += 1
                continue
            if type(result.get("correct")) is not bool or str(result.get("status") or "").lower() in {"void", "retired", "walkover", "cancelled"}:
                reasons["unsettled_or_void"] += 1
                continue
            selection = str(pub.get("selection_id") or "").strip()
            left, right = row.get("player1"), row.get("player2")
            ids = {str(p.get("id")) for p in (left, right) if isinstance(p, dict) and p.get("id")}
            if not event or len(ids) != 2 or selection not in ids:
                reasons["missing_verified_identity"] += 1
                continue
            key = (str(pub["section"]), event, selection)
            entry = dict(section=str(pub["section"]), event=event, match=str(row.get("match_id") or ""),
                         tour=tour, scheduled=scheduled, published=published, selection=selection,
                         players=ids, correct=result["correct"], odds=price)
            if key in picked:
                reasons["duplicate_issued_selection"] += 1
                if entry["published"] == picked[key]["published"] and (
                    (entry["correct"], entry["odds"]) != (picked[key]["correct"], picked[key]["odds"])
                ):
                    raise ValueError("Conflicting exact-time immutable publication data")
                # A reissued section price can legitimately change later.
                # Keep the earliest truly issued version, never closing odds.
                if entry["published"] < picked[key]["published"]:
                    picked[key] = entry
            else:
                picked[key] = entry
    return list(picked.values()), dict(reasons)


def shadow_index(rows):
    index = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("production_model_version") != CHAMPION or row.get("challenger_model_version") != CANDIDATE:
            continue
        for key in [("event", row.get("event_id")), ("match", row.get("match_id"))]:
            if key[1]:
                index[(key[0], str(key[1]))].append(row)
    return index


def summary(entries):
    n = len(entries)
    if not n:
        return dict(n=0, wins=0, losses=0, hit_rate=None, roi=None, profit_units=None, avg_odds=None)
    wins = sum(x["correct"] for x in entries)
    profit = sum((x["odds"] - 1.0) if x["correct"] else -1.0 for x in entries)
    return dict(n=n, wins=wins, losses=n-wins, hit_rate=wins/n, roi=profit/n,
                profit_units=profit, avg_odds=sum(x["odds"] for x in entries)/n)


def evaluate(issued, shadow, *, cutoff=stamp(CUTOFF)):
    if cutoff is None:
        raise ValueError("Invalid evaluation cutoff")
    picks, ignored = fixed_cohort(issued, cutoff)
    index = shadow_index(shadow)
    rejected = Counter()
    paired, seen = [], set()
    for x in picks:
        matches = index.get(("event", x["event"]), [])
        if not matches and x["match"]:
            matches = index.get(("match", x["match"]), [])
        matches = list({(r.get("match_id"), r.get("captured_at")): r for r in matches}.values())
        if len(matches) != 1:
            rejected["no_unique_exact_shadow_pair"] += 1
            continue
        r = matches[0]
        capture, sched = stamp(r.get("captured_at")), stamp(r.get("scheduled_at"))
        if capture is None or sched != x["scheduled"] or not capture <= x["published"] < sched:
            rejected["capture_not_before_issued_or_date_mismatch"] += 1
            continue
        if str(r.get("tour") or "").lower() != x["tour"]:
            rejected["tour_mismatch"] += 1
            continue
        p1, p2 = str(r.get("player1_id") or ""), str(r.get("player2_id") or "")
        if {p1, p2} != x["players"] or p1 == p2 or x["selection"] not in {p1, p2}:
            rejected["player_identity_mismatch"] += 1
            continue
        if r.get("status") != "settled" or type(r.get("target_player1_win")) is not int or r["target_player1_win"] not in (0, 1):
            rejected["shadow_not_settled"] += 1
            continue
        if (((x["selection"] == p1) == bool(r["target_player1_win"])) != x["correct"]):
            rejected["settlement_disagreement"] += 1
            continue
        try:
            a, b = (float(r[k]) for k in ("production_player1_probability", "challenger_player1_probability"))
        except (ValueError, TypeError, KeyError):
            rejected["invalid_probability"] += 1
            continue
        if not (math.isfinite(a) and math.isfinite(b) and 0 < a < 1 and 0 < b < 1):
            rejected["invalid_probability"] += 1
            continue
        k = (x["event"], x["selection"])
        if k in seen:
            rejected["cross_section_same_pick_exposure"] += 1
            continue
        seen.add(k)
        paired.append({**x, "champion_probability": a if x["selection"] == p1 else 1-a,
                       "candidate_probability": b if x["selection"] == p1 else 1-b})
    groups = {}
    for tour in ["atp", "wta", "all"]:
        subset = [e for e in paired if tour == "all" or e["tour"] == tour]
        groups[tour] = {
            "baseline_same_fixed_picks": summary(subset),
            "probability": {
                model: {"mean_probability": (sum(e[model+"_probability"] for e in subset)/len(subset) if subset else None),
                        "brier": (sum((float(e["correct"])-e[model+"_probability"])**2 for e in subset)/len(subset) if subset else None),
                        "log_loss": (sum(-math.log(e[model+"_probability"] if e["correct"] else (1-e[model+"_probability"])) for e in subset)/len(subset) if subset else None)}
                for model in ["champion", "candidate"]
            },
            "fixed_offer_if_minimum_predicted_probability": {
                str(t): {m: summary([e for e in subset if e[m+"_probability"] >= t]) for m in ("champion", "candidate")}
                for t in [0.65, 0.75, 0.8, 0.85]
            },
        }
    return {
        "schema": 1, "status": "MATCHED_OBSERVATIONAL_ONLY" if len(paired) >= MIN_EVALUABLE_MATCHED_PICKS else "INSUFFICIENT_MATCHED_PUBLISHED_PICKS",
        "scope": "Exact issued ATP/WTA TOP+VALUE match-winner priced >=1.50, candidates captured <= publication < start.",
        "source_issued": len(picks), "source_by_tour": dict(Counter(e["tour"] for e in picks)),
        "matched_unique": len(paired), "matched_by_tour": dict(Counter(e["tour"] for e in paired)),
        "minimum_evaluable_matched_picks": MIN_EVALUABLE_MATCHED_PICKS,
        "matched_fraction_of_issued": len(paired)/len(picks) if picks else None,
        "source_diagnostics": ignored, "unmatched_reasons": dict(rejected), "groups": groups,
        "limits": ["Matched published picks are not a replay of all unissued opportunities.",
                   "Fixed-offer ROI is conditional and post-hoc; changed probability cannot establish unissued offers.",
                   "Only originally published selection and issued price; no inferred opposite-side odds.",
                   "Pretraining forecasts and hindsight historical feature reconstruction are forbidden.",
                   "Minimum threshold cohorts below 30 are inconclusive; no production promotion."],
        "production_mutated": False, "provider_requests": 0, "model_promoted": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    ap.add_argument("--out", default=".cache/tbt/model-711-top-value/report.json")
    args = ap.parse_args()
    from _bootstrap import ROOT
    from release_store import ReleaseStore
    root = ROOT / ".cache/tbt/model-711-top-value"
    sources = [("tbt-predictions-v1", "ledger.json"),
               ("tbt-model-shadow-v1", "shadow_ledger.json"),
               ("tbt-model-shadow-v1", "shadow_report.json")]
    loaded = {}
    for tag, name in sources:
        store = ReleaseStore(args.data_repository, tag, root/tag)
        store.download(required_names=(name,), require_bundle_manifest=True)
        content = (store.directory/name).read_bytes()
        loaded[name] = json.loads(content)
        loaded["sha_"+name] = sha256(content).hexdigest()
    previous = loaded["shadow_report.json"]
    if previous.get("production_model_version") != CHAMPION or previous.get("challenger_model_version") != CANDIDATE:
        raise ValueError("Shadow report is not the exact 7.1.1/champion pair")
    report = evaluate(loaded["ledger.json"], loaded["shadow_ledger.json"])
    report["source_sha256"] = {k[4:]: v for k, v in loaded.items() if k.startswith("sha_")}
    report["model_pair"] = {"champion": CHAMPION, "candidate": CANDIDATE}
    report["cutoff_utc"] = CUTOFF
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps(report, allow_nan=False, ensure_ascii=False))


if __name__ == "__main__":
    main()
