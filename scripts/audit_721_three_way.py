"""Read-only, fail-closed same-fixture comparison: champion / frozen 721 / research.

Input is PRIVATE per-fixture issued prediction evidence. Never infers third
probabilities from published aggregate metrics, match outcomes, or model versions.
No fitting, CDB writes, API requests, provider credentials, or activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import random

ARMS = {"champion": "production_player1_probability",
        "candidate_721": "challenger_player1_probability",
        "research": "research_player1_probability"}


def when(raw: str, name: str) -> datetime:
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_" + name) from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive_" + name)
    return value.astimezone(timezone.utc)


def probability(value, name: str) -> float:
    try:
        p = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_" + name) from exc
    if not math.isfinite(p) or not 0 < p < 1:
        raise ValueError("invalid_" + name)
    return p


def verify_source(source: object, names: tuple[str, ...]):
    if not isinstance(source, dict):
        raise ValueError("missing_source")
    for name in names:
        if not str(source.get(name) or "").strip():
            raise ValueError("missing_provenance_" + name)


def prepare(paired: dict, research: dict):
    """Strict join of settled source rows, not a post-hoc nearest name/time join."""
    verify_source(paired.get("source"), ("production_version", "candidate_version", "candidate_model_sha256", "candidate_tag"))
    verify_source(research.get("source"), ("model_version", "model_sha256", "training_end", "calibration_end", "input_release_sha256"))
    if paired["source"]["candidate_version"] == paired["source"]["production_version"]:
        raise ValueError("same_champion_candidate_version")
    if not isinstance(paired.get("rows"), list) or not isinstance(research.get("rows"), list):
        raise ValueError("missing_rows")
    research_rows = {}
    for row in research["rows"]:
        key = str(row.get("match_id") or "").strip()
        if not key or key in research_rows:
            raise ValueError("ambiguous_research_match_id")
        research_rows[key] = row
    paired_seen = set()
    eligible = []
    for row in paired["rows"]:
        key = str(row.get("match_id") or "").strip()
        if not key or key in paired_seen:
            raise ValueError("ambiguous_frozen_match_id")
        paired_seen.add(key)
        if row.get("status") != "settled":
            continue
        if key not in research_rows:
            raise ValueError("missing_research_prediction:" + key)
        other = research_rows[key]
        p1, p2 = str(row.get("player1_id") or ""), str(row.get("player2_id") or "")
        if not p1 or not p2 or p1 == p2:
            raise ValueError("invalid_identity:" + key)
        if any(str(other.get(field) or "") != str(row.get(field) or "")
               for field in ("match_id", "player1_id", "player2_id", "tour")):
            raise ValueError("orientation_or_tour_mismatch:" + key)
        if str(row.get("tour") or "").upper() not in {"ATP", "WTA"}:
            raise ValueError("unknown_tour")
        if (str(row.get("production_model_version")) != paired["source"]["production_version"]
                or str(row.get("challenger_model_version")) != paired["source"]["candidate_version"]):
            raise ValueError("wrong_version_in_paired_row")
        start = when(row.get("scheduled_at"), "scheduled_at")
        capture = when(row.get("captured_at"), "captured_at")
        issued = when(other.get("issued_at"), "research_issued_at")
        asof = when(other.get("feature_asof"), "feature_asof")
        if not (asof <= issued <= capture < start):
            raise ValueError("research_prediction_not_asof_original_snapshot:" + key)
        if not (when(research["source"]["training_end"], "training_end") < start
                and when(research["source"]["calibration_end"], "calibration_end") < start):
            raise ValueError("research_fit_or_calibration_uses_test_time")
        settled = when(row.get("settled_at"), "settled_at")
        if settled <= start:
            raise ValueError("invalid_settlement_clock")
        y = row.get("target_player1_win")
        winner = str(row.get("result_winner_id") or "")
        if type(y) is not int or y not in (0, 1) or winner not in (p1, p2) or y != int(winner == p1):
            raise ValueError("outcome_identity_mismatch")
        preds = {name: probability(row.get(field) if name != "research" else other.get(field), field)
                 for name, field in ARMS.items()}
        surf = str(row.get("surface") or "").lower()
        eligible.append({"match_id": key, "date": start.date().isoformat(),
                         "tour": row["tour"].upper(),
                         "surface": surf if surf in {"hard", "clay", "grass", "carpet"} else "unknown",
                         "y": y, "p": preds})
    # A research file is allowed to include not-yet-settled fixtures but not foreign matches.
    if set(research_rows) - paired_seen:
        raise ValueError("foreign_research_fixtures")
    if not eligible:
        raise ValueError("no_verified_settled_comparisons")
    return sorted(eligible, key=lambda x: (x["date"], x["match_id"]))


def metrics(rows: list[dict], arm: str) -> dict:
    if not rows:
        return {"n": 0, "accuracy": None, "brier": None, "log_loss": None,
                "high80": {"n": 0, "coverage": None, "accuracy": None}}
    n, correct, brier, loss, high, hits = len(rows), 0, 0.0, 0.0, 0, 0
    for r in rows:
        p, y = r["p"][arm], r["y"]
        right = ((p >= .5) == bool(y))
        correct += int(right)
        brier += (p - y)**2
        loss -= (y*math.log(p) + (1-y)*math.log(1-p))
        if max(p, 1-p) >= .80:
            high += 1
            hits += int(right)
    return {"n": n, "correct": correct, "accuracy": correct/n,
            "brier": brier/n, "log_loss": loss/n,
            "high80": {"n": high, "coverage": high/n,
                       "accuracy": hits/high if high else None}}


def paired_ci(rows: list[dict], challenger: str, baseline: str, *, replications=500) -> list[float] | None:
    if len(rows) < 200:
        return None
    by_day = defaultdict(lambda: [0, 0])
    for row in rows:
        y = bool(row["y"])
        right_c = int((row["p"][challenger] >= .5) == y)
        right_b = int((row["p"][baseline] >= .5) == y)
        by_day[row["date"]][0] += right_c-right_b
        by_day[row["date"]][1] += 1
    blocks = list(by_day.values())
    if len(blocks) < 14:
        return None
    rng = random.Random(721)
    bs = []
    for _ in range(replications):
        picked = [blocks[rng.randrange(len(blocks))] for j in range(len(blocks))]
        bs.append(sum(v[0] for v in picked)/sum(v[1] for v in picked))
    bs.sort()
    return [bs[int(.025*(replications-1))], bs[int(.975*(replications-1))]]


def report(paired: dict, research: dict) -> dict:
    rows = prepare(paired, research)
    def group(chunk):
        return {name: metrics(chunk, name) for name in ARMS}
    overall = group(rows)
    tour = {name: group([x for x in rows if x["tour"] == name]) for name in ("ATP","WTA")}
    surface = {name: group([x for x in rows if x["surface"] == name])
               for name in ("hard","clay","grass","carpet","unknown")}
    ci = {name: paired_ci(rows, name, "candidate_721")
          for name in ("champion","research")}
    fair = (len(rows) >= 200 and all(tour[t]["candidate_721"]["n"] >= 50 for t in ("ATP","WTA")))
    # Descriptive scorecard, never a standalone promotion authorization.
    return {"status": "EVALUATED_RESEARCH_ONLY", "production_mutated": False,
            "candidate_promoted": False, "provider_requests": 0,
            "comparison_cohort": {"n": len(rows), "first": rows[0]["date"],
                                  "last": rows[-1]["date"], "atp_n": tour["ATP"]["candidate_721"]["n"],
                                  "wta_n": tour["WTA"]["candidate_721"]["n"]},
            "source": {"production_version": paired["source"]["production_version"],
                       "candidate_version": paired["source"]["candidate_version"],
                       "research_version": research["source"]["model_version"],
                       "research_model_sha256": research["source"]["model_sha256"],
                       "input_release_sha256": research["source"]["input_release_sha256"]},
            "overall": overall, "tour": tour, "surface": surface,
            "paired_accuracy_delta_ci95_vs_721": ci,
            "assessment": "DESCRIPTIVE_MINIMUM_REACHED" if fair else "INSUFFICIENT_COHORT",
            "limits": ["No automatic promotion or live odds qualification",
                       "A later untouched time holdout is required for tuned variants",
                       "The original 7.2.1 and champion fixtures must be the same exact issued cohort"]}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--paired", type=Path, required=True)
    cli.add_argument("--research", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if len({p.resolve() for p in (args.paired,args.research,args.output)}) != 3:
        cli.error("All paths must differ; input must be immutable")
    paired_bytes, research_bytes = args.paired.read_bytes(), args.research.read_bytes()
    result = report(json.loads(paired_bytes), json.loads(research_bytes))
    result["input_sha256"] = {"paired": hashlib.sha256(paired_bytes).hexdigest(),
                              "research": hashlib.sha256(research_bytes).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    tmp.replace(args.output)
    print(json.dumps({"status":result["status"],"n":result["comparison_cohort"]["n"],
                      "production_mutated":False,"report":str(args.output)}))


if __name__ == "__main__":
    main()
