"""Read-only pre-match raw-vs-depth-shrunk probability ablation.

Uses the actual BlinQ selector function on *reconstructed frozen priced inputs*
and refuses to call it a valid exact counterfactual unless its public-probability
arm reproduces the frozen section assignments for every eligible fixture.
Not a shadow release, retrain, or automatic production recommendation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
import random
from pathlib import Path

from replay_selection_reliability import (
    anchors, canonical_index, dt, load_snapshots, metrics, prepare, sha,
)
from tbt.services.market_selection import select_market_sections

SECTIONS = ("value", "top_daily", "prime")
RETURNED = {"value": "value_picks", "top_daily": "top_daily_picks", "prime": "prime_picks"}


def snapshots_to_candidates(snapshots, matches):
    index = canonical_index(matches)
    groups, diagnostics = defaultdict(list), Counter()
    seen = set()
    for day, snap in sorted(anchors(snapshots).items()):
        when = dt(snap["generated_at"])
        for row in snap["rows"]:
            prepared = prepare(row, when, day, index, diagnostics)
            if not prepared:
                continue
            key = (prepared["model"], prepared["event"])
            if key in seen:
                diagnostics["repeated_model_event"] += 1
                continue
            seen.add(key)
            groups[(day, prepared["model"])].append((row, prepared))
    return groups, diagnostics


def reconstructed_card(source, evidence, *, raw_instead_of_shrunk, day):
    if not evidence["quote_ok"]:
        return None
    quote = source["betting"]
    market = source["two_way_market"]
    if not isinstance(quote, dict) or not isinstance(market, dict):
        return None
    if quote.get("betting_day") not in (None, "", day):
        return None
    samples = source.get("samples")
    if not isinstance(samples, dict):
        return None
    player1, player2 = source["player1"], source["player2"]
    confidence = evidence["raw"] if raw_instead_of_shrunk else evidence["public"]
    betting = {
        **quote,
        "market": "match_winner",
        "model_probability": evidence["raw"],
        "blinq_probability": confidence,
        "probability_reliability": evidence["depth"],
        "betting_day": day,
        "odds": evidence["odds"],
    }
    return {
        "event_id": evidence["event"],
        "scheduled_at": source["scheduled_at"],
        "tour": evidence["tour"],
        "surface": evidence["surface"],
        "model_version": evidence["model"],
        "winner_id": source["winner_id"],
        "player1": player1, "player2": player2,
        "quality": {
            "player1": {
                "matches": samples.get("player1_matches"),
                "surface_matches": samples.get("player1_surface_matches"),
            },
            "player2": {
                "matches": samples.get("player2_matches"),
                "surface_matches": samples.get("player2_surface_matches"),
            },
        },
        "data_depth": evidence["depth"],
        "betting": betting,
        "match_winner_market": market,
    }


def selection_ids(result):
    return {
        section: {
            str(x["event_id"])
            for x in result.get(RETURNED[section], [])
        }
        for section in SECTIONS
    }


def assigned_ids(records):
    groups = {section: set() for section in SECTIONS}
    for _, record in records:
        section = record.get("section")
        if section in groups:
            groups[section].add(record["event"])
    return groups


def sorted_score(rows, probability):
    settled = [r for r in rows if type(r.get("correct")) is bool]
    if not settled:
        return {"settled": 0, "hit_rate": None, "brier": None, "log_loss": None}
    return metrics([{**r, "raw": r[probability], "public": r[probability]} for r in settled])


def paired_day_ci(entries, *, metric, repeats=1000):
    """Paired event difference: public-minus-raw; bootstrap entire days."""
    scored = defaultdict(list)
    for row in entries:
        if type(row["correct"]) is not bool:
            continue
        y = int(row["correct"])
        p, q = row["raw"], row["public"]
        if metric == "brier":
            delta = (q-y)**2 - (p-y)**2
        elif metric == "log_loss":
            delta = (-y*math.log(q)-(1-y)*math.log(1-q)) - (
                -y*math.log(p)-(1-y)*math.log(1-p)
            )
        else:
            raise ValueError("unknown paired metric")
        scored[row["day"]].append(delta)
    if not scored:
        return {"days": 0, "n": 0, "mean_public_minus_raw": None, "day_bootstrap_ci95": None}
    day_groups = list(scored.values())
    n = sum(map(len, day_groups))
    mean = sum(map(sum, day_groups))/n
    rng = random.Random(20261103)
    estimates = []
    for _ in range(repeats):
        chosen = [day_groups[rng.randrange(len(day_groups))] for _ in day_groups]
        estimates.append(sum(sum(x) for x in chosen)/sum(len(x) for x in chosen))
    estimates.sort()
    lo = estimates[int(.025*(repeats-1))]
    hi = estimates[int(.975*(repeats-1))]
    return {
        "days": len(day_groups), "n": n, "mean_public_minus_raw": mean,
        "day_bootstrap_ci95": [lo, hi],
        "policy": "descriptive day-cluster resampling; does not remove outcome or historical selection biases",
    }


def same_capacity_complete_days(baseline, raw):
    """Don't compare hit rates on unmatched denominators or partial outcomes."""
    all_results = {}
    for section in SECTIONS:
        orig, alt = baseline[section], raw[section]
        if len(orig) != len(alt):
            all_results[section] = None
            continue
        all_results[section] = len(orig)
    return all_results


def test_replay(snapshots, matches, reference=None):
    groups, diagnostics = snapshots_to_candidates(snapshots, matches)
    by_model = defaultdict(list)
    for (day, version), pairs in groups.items():
        for _, row in pairs:
            by_model[version].append(row)
    report = {"schema": 1, "status": "RESEARCH_ONLY_NOT_PROMOTION", "models": {}}
    for version, rows in sorted(by_model.items()):
        s_raw, s_public = sorted_score(rows, "raw"), sorted_score(rows, "public")
        reference_model = (reference or {}).get("model_quality_A", {}).get(version)
        if reference_model:
            for name, scored in (("all_candidates_raw", s_raw), ("all_candidates_public", s_public)):
                for metric in ("settled", "hit_rate", "brier", "log_loss"):
                    expected, actual = reference_model[name][metric], scored[metric]
                    if expected is None or actual is None:
                        if expected != actual:
                            raise ValueError("independent replay reference mismatch: " + name)
                    elif abs(actual-expected) > 1e-10:
                        raise ValueError("independent replay reference mismatch: " + name+"/"+metric)
        by_tour = defaultdict(list)
        by_depth = defaultdict(list)
        by_assigned_section = defaultdict(list)
        for r in rows:
            by_assigned_section[str(r["section"] or "unassigned")].append(r)
            by_tour[r["tour"]].append(r)
            bucket = "below_80" if r["depth"] < .8 else "80_90" if r["depth"] < .9 else "90_plus"
            by_depth[bucket].append(r)
        replays = {
            "priced_rows": 0, "exact_reproduced_days": 0,
            "baseline_mismatch_days": 0, "baseline_missing_quoted_rows": 0,
            "fully_settled_same_capacity_days": {section: 0 for section in SECTIONS},
            "fully_settled_same_capacity_n": {section: 0 for section in SECTIONS},
            "same_capacity_original_correct": {section: 0 for section in SECTIONS},
            "same_capacity_raw_correct": {section: 0 for section in SECTIONS},
            "raw_changes": {section: {"entered": 0, "exited": 0} for section in SECTIONS},
            "raw_section_counts": Counter(), "public_section_counts": Counter(),
            "raw_candidate_outcome_coverage": {section: Counter() for section in SECTIONS},
        }
        all_reproduced = []
        for (day, model), pairs in groups.items():
            if model != version:
                continue
            public_inputs = []
            raw_inputs = []
            outcome = {}
            valid = []
            for original, row in pairs:
                outcome[row["event"]] = row["correct"]
                if row["quote_ok"]:
                    public_card = reconstructed_card(original, row, raw_instead_of_shrunk=False, day=day)
                    raw_card = reconstructed_card(original, row, raw_instead_of_shrunk=True, day=day)
                    if public_card and raw_card:
                        public_inputs.append(public_card)
                        raw_inputs.append(raw_card)
                        valid.append((original, row))
                    else:
                        diagnostics["incomplete_reconstructed_card"] += 1
            replays["priced_rows"] += len(valid)
            snapshot_baseline = assigned_ids(pairs)
            if any(row["section"] in SECTIONS and row["event"] not in {r["event"] for _, r in valid}
                   for _, row in pairs):
                replays["baseline_missing_quoted_rows"] += 1
                continue
            pub = selection_ids(select_market_sections(public_inputs))
            if pub != snapshot_baseline:
                replays["baseline_mismatch_days"] += 1
                continue
            replays["exact_reproduced_days"] += 1
            alt = selection_ids(select_market_sections(raw_inputs))
            all_reproduced.append(day)
            for section in SECTIONS:
                original_ids, counter_ids = pub[section], alt[section]
                replays["public_section_counts"][section] += len(original_ids)
                replays["raw_section_counts"][section] += len(counter_ids)
                replays["raw_changes"][section]["entered"] += len(counter_ids-original_ids)
                replays["raw_changes"][section]["exited"] += len(original_ids-counter_ids)
                replays["raw_candidate_outcome_coverage"][section]["selected"] += len(counter_ids)
                replays["raw_candidate_outcome_coverage"][section]["settled"] += sum(
                    type(outcome[e]) is bool for e in counter_ids
                )
                if len(original_ids) != len(counter_ids):
                    continue
                if not all(type(outcome[e]) is bool for e in original_ids | counter_ids):
                    continue
                replays["fully_settled_same_capacity_days"][section] += 1
                replays["fully_settled_same_capacity_n"][section] += len(original_ids)
                replays["same_capacity_original_correct"][section] += sum(outcome[e] for e in original_ids)
                replays["same_capacity_raw_correct"][section] += sum(outcome[e] for e in counter_ids)
        if replays["exact_reproduced_days"] == 0:
            diagnostics["no_exact_reproduction_for_" + version] += 1
        for field in ("raw_section_counts", "public_section_counts", "raw_candidate_outcome_coverage"):
            replays[field] = dict(replays[field])
        for s in SECTIONS:
            replays["raw_candidate_outcome_coverage"][s] = dict(replays["raw_candidate_outcome_coverage"][s])
        report["models"][version] = {
            "candidate_count": len(rows),
            "fixed_candidate_raw": s_raw,
            "fixed_candidate_shrunk": s_public,
            "paired_day_brier": paired_day_ci(rows, metric="brier"),
            "paired_day_log_loss": paired_day_ci(rows, metric="log_loss"),
            "fixed_depth_gte_80": {
                "raw": sorted_score([r for r in rows if r["depth"] >= .80], "raw"),
                "shrunk": sorted_score([r for r in rows if r["depth"] >= .80], "public"),
            },
            "fixed_verified_prestart_quoted": {
                "raw": sorted_score([r for r in rows if r["quote_ok"]], "raw"),
                "shrunk": sorted_score([r for r in rows if r["quote_ok"]], "public"),
            },
            "fixed_snapshot_assigned_sections": {
                section: {
                    "raw": sorted_score(group, "raw"),
                    "shrunk": sorted_score(group, "public"),
                    "n_all": len(group),
                } for section, group in sorted(by_assigned_section.items())
            },
            "by_tour": {
                k: {"raw": sorted_score(v, "raw"), "shrunk": sorted_score(v, "public")}
                for k, v in sorted(by_tour.items())
            },
            "by_data_depth": {
                k: {"raw": sorted_score(v, "raw"), "shrunk": sorted_score(v, "public")}
                for k, v in sorted(by_depth.items())
            },
            "native_selector_replay": replays,
        }
    report.update({
        "anchored_days": len({d for d, _ in groups}),
        "diagnostics": dict(diagnostics),
        "constraints": [
            "Unpriced candidates are not counterfactually priced. This does not replay earlier odds-discovery priority.",
            "Selector replay is only valid on days where native-public arm exactly reproduces stored section assignments.",
            "Depth below 0.80 is ineligible for TOP/PRIME; whole-universe Brier gain cannot be presumed to improve those categories.",
            "Fixed snapshot section metrics are candidate assignments, not independently verified public issuances.",
            "Match winner historical candidates are not proof of live public issuance.",
            "Same-capacity performance only counts days with both complete outcomes; other rates cannot be compared.",
            "Paired raw/shrunk quality affects confidence scoring; winner identity is unchanged.",
            "Source release credentials and SHA checks are provided by existing read-only replay workflow.",
            "No CDB writes, provider calls, fitting, production candidate activation or EV optimization.",
        ],
        "production_mutated": False,
        "provider_requests": 0,
        "candidate_promoted": False,
    })
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshots", required=True, nargs="+", type=Path)
    ap.add_argument("--canonical", required=True, type=Path)
    ap.add_argument("--reference", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    import pandas as pd
    needed = ["match_id", "player1_id", "player2_id", "winner_id", "status",
              "scheduled_at", "tour", "tournament_level", "provider_context_json"]
    matches = pd.read_parquet(args.canonical, columns=needed).to_dict("records")
    reference = json.loads(args.reference.read_text())
    if reference.get("status") != "READ_ONLY_REPLAY_NO_DEPLOY":
        raise ValueError("reference report is not from native integrity-pinned replay")
    report = test_replay(load_snapshots(args.snapshots), matches, reference)
    report["source_sha256"] = {
        "canonical": sha(args.canonical),
        "snapshots": {p.name: sha(p) for p in args.snapshots},
        "reference": sha(args.reference),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({
        "status": report["status"], "anchored_days": report["anchored_days"],
        "models": {name: {
            "matched": value["fixed_candidate_raw"]["settled"],
            "raw_brier": value["fixed_candidate_raw"]["brier"],
            "public_brier": value["fixed_candidate_shrunk"]["brier"],
            "reproduced_days": value["native_selector_replay"]["exact_reproduced_days"],
            "baseline_mismatch_days": value["native_selector_replay"]["baseline_mismatch_days"],
        } for name, value in report["models"].items()}
    }))


if __name__ == "__main__":
    main()
