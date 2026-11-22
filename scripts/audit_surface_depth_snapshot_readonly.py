"""Read-only gate overlap and threshold sensitivity on frozen Match Winner rows.

No provider/API requests, CDB writes, releases, model fitting or public offer
mutation. Output is for diagnostic comparison, not a backdated pick issuance.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
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
        "depth_bins_all_priced":dict(depth_hist),
        "competitions_with_surface_or_depth_fails":{k:dict(v) for k,v in sorted(competition.items())},
        "scenario_gate_pass":sensitivity, "affected_examples":examples,
        "limitations":"Non-exclusive failures; source snapshot may have different day filters or evaluation time than audit logs. Scenario is pre-exclusivity, not public issuance. Model public probabilities and odds are held fixed; no new API calls, no outcomes, no backdating.",
        "provider_requests":0, "production_writes":0,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--day",default="2026-11-22")
    args=p.parse_args()
    print(json.dumps({"surface_depth_readonly_audit":compute(args.archive,args.day)},ensure_ascii=False))


if __name__ == "__main__":
    main()
