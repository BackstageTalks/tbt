"""Read-only gate overlap and threshold sensitivity on frozen Match Winner rows.

No provider/API requests, CDB writes, releases, model fitting or public offer
mutation. Output is for diagnostic comparison, not a backdated pick issuance.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import gzip
import json
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("Europe/Bratislava")
QUALITY = {"insufficient_surface_history", "insufficient_data_depth"}
KNOWN = {
    "missing_or_low_odds",
    "probability_below_fixed_floor",
    "insufficient_surface_history",
    "insufficient_data_depth",
}
SCENARIOS = [(5, .50), (4, .50), (3, .50), (2, .50),
             (5, .40), (5, .30), (4, .40), (3, .40), (3, .30)]


def number(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def stamp(value):
    try:
        x = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return x if x.tzinfo else None


def is_today(row, day):
    when = stamp(row.get("scheduled_at"))
    if when is None:
        return False
    local = when.astimezone(LOCAL)
    return local.date().isoformat() == day and local.hour >= 6


def load_latest(archive: Path, day: str):
    with gzip.open(archive, "rt", encoding="utf-8") as f:
        envelope = json.load(f)
    if envelope.get("schema") != 1 or not isinstance(envelope.get("snapshots"), list):
        raise ValueError("Invalid snapshot envelope")
    matching = [x for x in envelope["snapshots"]
                if isinstance(x, dict) and stamp(x.get("generated_at"))
                and stamp(x["generated_at"]).astimezone(LOCAL).date().isoformat() == day]
    if not matching:
        raise ValueError("No frozen candidate snapshot for requested local date")
    matching.sort(key=lambda x: stamp(x["generated_at"]))
    snap = matching[-1]
    if (snap.get("scope") or {}).get("post_match_fields_excluded") is not True:
        raise ValueError("Snapshot must be pre-match-only")
    if not isinstance(snap.get("rows"), list):
        raise ValueError("Missing candidate rows")
    return snap, len(matching)


def classify(row):
    rs = set(row.get("top_rejection_reasons") or [])
    sample = row.get("samples") if isinstance(row.get("samples"), dict) else {}
    a = number(sample.get("player1_surface_matches"))
    b = number(sample.get("player2_surface_matches"))
    depth = number(row.get("data_depth"))
    return rs, a, b, depth


def compute(archive: Path, day: str):
    snap, count = load_latest(archive, day)
    rows = [x for x in snap["rows"]
            if isinstance(x, dict) and is_today(x, day)]
    priced = [x for x in rows if x.get("priced") is True]
    raw_reasons = Counter()
    depth_hist, surf_hist, overlap = Counter(), Counter(), Counter()
    competition, examples = defaultdict(Counter), []
    surface_fail_surface_labels = Counter()
    quality_cofailures = Counter()
    depth_fail_bins = Counter()
    for row in priced:
        rs, a, b, depth = classify(row)
        raw_reasons.update(rs)
        surf = min(a,b) if a is not None and b is not None else None
        if surf is None:
            surf_hist["unknown"] += 1
        elif surf == 0:
            surf_hist["0"] += 1
        elif surf == 1:
            surf_hist["1"] += 1
        elif surf == 2:
            surf_hist["2"] += 1
        elif surf == 3:
            surf_hist["3"] += 1
        elif surf == 4:
            surf_hist["4"] += 1
        elif surf < 10:
            surf_hist["5-9"] += 1
        else:
            surf_hist["10+"] += 1
        if depth is None:
            depth_hist["unknown"] += 1
        elif depth < .20:
            depth_hist["<20%"] += 1
        elif depth < .30:
            depth_hist["20-29%"] += 1
        elif depth < .40:
            depth_hist["30-39%"] += 1
        elif depth < .50:
            depth_hist["40-49%"] += 1
        elif depth < .80:
            depth_hist["50-79%"] += 1
        else:
            depth_hist["80-100%"] += 1
        surface_fail, depth_fail = ("insufficient_surface_history" in rs,
                                    "insufficient_data_depth" in rs)
        if surface_fail and depth_fail:
            overlap["both"] += 1
        elif surface_fail:
            overlap["surface_only_of_two"] += 1
        elif depth_fail:
            overlap["depth_only_of_two"] += 1
        else:
            overlap["neither"] += 1
        if surface_fail or depth_fail:
            if surface_fail:
                surface_fail_surface_labels[str(row.get("surface") or "missing").lower()] += 1
            if depth_fail:
                binname = ("unknown" if depth is None else
                           "<20%" if depth < .20 else
                           "20-29%" if depth < .30 else
                           "30-39%" if depth < .40 else
                           "40-49%" if depth < .50 else "50%+")
                depth_fail_bins[binname] += 1
            if rs - QUALITY:
                quality_cofailures["also_other_blockers"] += 1
                for extra in rs - QUALITY:
                    quality_cofailures["also_"+extra] += 1
            else:
                quality_cofailures["only_surface_depth_blockers"] += 1
            category = str(row.get("competition") or row.get("tournament_level") or row.get("tour") or "unknown")
            competition[category]["affected"] += 1
            if surface_fail:
                competition[category]["surface"] += 1
            if depth_fail:
                competition[category]["depth"] += 1
            if len(examples) < 16:
                players = [row.get(k) if isinstance(row.get(k), dict) else {} for k in ("player1", "player2")]
                bet = row.get("betting") if isinstance(row.get("betting"), dict) else {}
                others = rs - QUALITY
                examples.append({
                    "event_id": row.get("event_id"), "competition": category,
                    "match": " vs ".join(str(p.get("name") or "?") for p in players),
                    "surface": row.get("surface"),
                    "surface_samples": [a,b], "min_depth_pct": None if depth is None else round(100*depth,1),
                    "model_public_pct": round(100*(number(row.get("blinq_probability")) or 0),1),
                    "odds": bet.get("odds"), "reasons": sorted(rs),
                    "only_quality_blockers": not others,
                })
    sensitivity={}
    for surface_floor, depth_floor in SCENARIOS:
        qualifying=[]
        for row in priced:
            rs,a,b,depth=classify(row)
            residual=rs-QUALITY
            if residual:
                continue
            if a is None or b is None or min(a,b)<surface_floor:
                continue
            if depth is None or depth < depth_floor:
                continue
            qualifying.append(str(row.get("event_id") or ""))
        sensitivity[f"surface_{surface_floor}_depth_{int(depth_floor*100)}"]={
            "pre_exclusivity_gate_pass":len(qualifying), "new_vs_baseline":0,
        }
        sensitivity[f"surface_{surface_floor}_depth_{int(depth_floor*100)}"]["_ids"]=qualifying
    base=set(sensitivity["surface_5_depth_50"]["_ids"])
    for v in sensitivity.values():
        v["new_vs_baseline"]=len(set(v.pop("_ids"))-base)
    return {
        "day":day, "generated_at":snap["generated_at"], "snapshot_count_on_day":count,
        "snapshot_total_rows":len(snap["rows"]), "day_rows":len(rows),
        "day_priced":len(priced), "source_rejection_counts":dict(raw_reasons),
        "quality_overlap":dict(overlap),
        "surface_min_count_bins_all_priced":dict(surf_hist),
        "surface_fail_surface_labels":dict(surface_fail_surface_labels),
        "quality_failure_cofactors":dict(quality_cofailures),
        "depth_fail_bins":dict(depth_fail_bins),
        "depth_bins_all_priced":dict(depth_hist),
        "competitions_with_surface_or_depth_fails":{k:dict(v) for k,v in sorted(competition.items())},
        "scenario_gate_pass":sensitivity, "candidate_policy_scenarios":scenario_analysis(priced,snap["generated_at"]), "affected_examples":examples,
        "limitations":"Non-exclusive failures; source snapshot may have different day filters or evaluation time than audit logs. Scenario is pre-exclusivity, not public issuance. Model public probabilities and odds are held fixed; no new API calls, no outcomes, no backdating.",
        "provider_requests":0, "production_writes":0,
    }



# Diagnostic-only recomputation. These scenarios are NOT a production eligibility
# engine. All non-tunable original rejections are retained (identity, timing,
# market integrity, model provenance). Frozen probabilities and odds never change.
TUNABLE_TOP_REASONS = {
    "probability_below_fixed_floor", "missing_or_low_odds",
    "insufficient_surface_history", "insufficient_data_depth", "assigned_to_value",
}
POLICY_VARIANTS = [
    ("baseline", .65, 1.50, 5, .50, .15),
    ("surface_3", .65, 1.50, 3, .50, .15),
    ("depth_30", .65, 1.50, 5, .30, .15),
    ("top_prob_62", .62, 1.50, 5, .50, .15),
    ("top_prob_60", .60, 1.50, 5, .50, .15),
    ("top_surface3_prob62", .62, 1.50, 3, .50, .15),
    ("top_surface3_depth30_prob62", .62, 1.50, 3, .30, .15),
    ("value_spread_25", .65, 1.50, 5, .50, .25),
    ("value_spread_35", .65, 1.50, 5, .50, .35),
    ("value_spread_50", .65, 1.50, 5, .50, .50),
    ("top62_value_spread35", .62, 1.50, 5, .50, .35),
    ("top60_value_spread50", .60, 1.50, 5, .50, .50),
    ("top_surface3_prob62_value35", .62, 1.50, 3, .50, .35),
    ("top_odds_140_overlaps_acca", .65, 1.40, 5, .50, .15),
    ("top_odds_130_overlaps_acca", .65, 1.30, 5, .50, .15),
    ("top_odds_120_overlaps_acca", .65, 1.20, 5, .50, .15),
    ("top_odds_130_surface3", .65, 1.30, 3, .50, .15),
    ("top_odds_130_surface3_prob62", .62, 1.30, 3, .50, .15),
]


def _row_core_safe(row):
    reasons = set(row.get("top_rejection_reasons") or [])
    return not (reasons - TUNABLE_TOP_REASONS)


def _candidate_id(row):
    return str(row.get("event_id") or "")


def _price(row):
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    return number(betting.get("odds"))


def _surface_min(row):
    samples = row.get("samples") if isinstance(row.get("samples"), dict) else {}
    values = [number(samples.get("player1_surface_matches")),
              number(samples.get("player2_surface_matches"))]
    return min(values) if all(v is not None for v in values) else None


def _spread(row):
    market = row.get("two_way_market") if isinstance(row.get("two_way_market"), dict) else {}
    a, b = number(market.get("player1_odds")), number(market.get("player2_odds"))
    if not a or not b or a <= 1.0 or b <= 1.0:
        return None
    return abs(a-b)/((a+b)/2)


def prestart_at_snapshot(row, observed_at):
    start=stamp(row.get("scheduled_at"))
    creation=stamp(row.get("created_at"))
    betting=row.get("betting") if isinstance(row.get("betting"), dict) else {}
    quote=stamp(betting.get("captured_at"))
    observed=stamp(observed_at)
    return bool(start and creation and quote and observed
                and start-observed >= timedelta(minutes=15)
                and creation <= observed and quote <= observed
                and creation < start and quote < start)


def scenario_analysis(priced, observed_at):
    safe = [r for r in priced if _row_core_safe(r)]
    report = {}
    for name, top_prob, top_odds, top_surface, top_depth, value_spread in POLICY_VARIANTS:
        values, tops, acca = [], [], []
        for row in safe:
            p = number(row.get("blinq_probability"))
            o = _price(row)
            surface = _surface_min(row)
            depth = number(row.get("data_depth"))
            if None in (p,o,surface,depth):
                continue
            value = (p >= .60 and o > 1.80 and depth >= .50
                     and surface >= 3 and _spread(row) is not None
                     and _spread(row) <= value_spread + 1e-12)
            if value:
                values.append(row)
                continue
            if (p >= top_prob and o >= top_odds and depth >= top_depth
                    and surface >= top_surface):
                tops.append(row)
            elif p >= .65 and o < 1.50 and depth >= .50 and surface >= 5:
                acca.append(row)
        # TOP has five cards maximum, Value has no configured cardinality cap.
        tops = sorted(tops, key=lambda x: number(x.get("blinq_probability")) or 0, reverse=True)
        values = sorted(values, key=lambda x: number(x.get("blinq_probability")) or 0, reverse=True)
        actual_top=tops[:5]
        issueable_top=[x for x in tops if prestart_at_snapshot(x, observed_at)][:5]
        issueable_values=[x for x in values if prestart_at_snapshot(x, observed_at)]
        report[name]={
            "top_candidates_before_5_cap":len(tops),
            "top_after_5_cap":len(actual_top),
            "value_candidates":len(values),
            "total_top_value":len(actual_top)+len(values),
            "at_least_five":len(actual_top)+len(values)>=5,
            "prestart_15m_top":len(issueable_top),
            "prestart_15m_value":len(issueable_values),
            "prestart_15m_total":len(issueable_top)+len(issueable_values),
            "prestart_15m_at_least_5":len(issueable_top)+len(issueable_values)>=5,
            "prestart_15m_top_ids":[_candidate_id(x) for x in issueable_top],
            "prestart_15m_value_ids":[_candidate_id(x) for x in issueable_values],
            "acca_candidate_count":len(acca),
            "top_event_ids":[_candidate_id(x) for x in actual_top],
            "value_event_ids":[_candidate_id(x) for x in values],
            "odds_bucket_overlap_with_acca":top_odds<1.50,
            "low_surface_unknown_admitted":any(str(r.get("surface"))=="unknown" for r in actual_top+values),
        }
    base=set(report["baseline"]["top_event_ids"]+report["baseline"]["value_event_ids"])
    for item in report.values():
        now=set(item["top_event_ids"]+item["value_event_ids"])
        item["unique_new_vs_baseline"]=len(now-base)
    return {"safeguarded_priced_rows":len(safe), "variants":report,
            "limits":"One same-day frozen snapshot, no repricing and no model rerun. Non-tunable rejection reasons preserved; ACCA and TOP odds overlap noted, not deployed. Counts are rough upper bounds prior to canonical publication/issuance validation."}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--day",default="2026-11-22")
    args=p.parse_args()
    print(json.dumps({"surface_depth_readonly_audit":compute(args.archive,args.day)},ensure_ascii=False))


if __name__ == "__main__":
    main()
