"""Read-only, exact-identity 2026 BlinQ selector replay; no EV/odds optimization.

Inputs are existing private pre-match selector snapshots and canonical completed
matches. No provider calls, model fitting, CDB writing or public publication.
The stored selected_section is *candidate assignment*, NOT proof of issuance.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

SECTIONS = ("value", "top_daily", "prime")
MIN_PRESTART = timedelta(minutes=15)
LOCAL = ZoneInfo("Europe/Bratislava")
FINISHED = {"completed", "finished", "final", "ended", "closed"}


def dt(value):
    if hasattr(value, "isoformat") and not isinstance(value, str):
        value = value.isoformat()
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid timestamp") from exc
    if result.tzinfo is None:
        raise ValueError("naive timestamp")
    return result.astimezone(timezone.utc)


def num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_snapshots(paths):
    snapshots = []
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            document = json.load(handle)
        if not isinstance(document, dict) or document.get("schema") != 1:
            raise ValueError("invalid selector history envelope")
        month = document.get("month")
        if not isinstance(month, str) or len(month) != 7:
            raise ValueError("selector month missing")
        if not isinstance(document.get("snapshots"), list):
            raise ValueError("selector history snapshots missing")
        for snapshot in document["snapshots"]:
            if not isinstance(snapshot, dict) or snapshot.get("schema") != 1:
                raise ValueError("invalid selector snapshot")
            if (snapshot.get("scope") or {}).get("post_match_fields_excluded") is not True:
                raise ValueError("selector snapshot not confirmed pre-match-only")
            if dt(snapshot.get("generated_at")).strftime("%Y-%m") != month:
                raise ValueError("snapshot outside its month partition")
            rows = snapshot.get("rows")
            if not isinstance(rows, list):
                raise ValueError("invalid snapshot rows")
            for row in rows:
                if not isinstance(row, dict) or any(
                    key in row for key in ("result", "settlement", "stats", "correct")
                ):
                    raise ValueError("post-match field in pre-match candidate")
            snapshots.append(snapshot)
    return sorted(snapshots, key=lambda s: dt(s["generated_at"]))


def anchors(snapshots):
    """One predeclared earliest >=06:00 Europe/Bratislava generation/day."""
    picked = {}
    for snapshot in snapshots:
        local = dt(snapshot["generated_at"]).astimezone(LOCAL)
        if local.hour < 6:
            continue
        picked.setdefault(local.date().isoformat(), snapshot)
    return picked


def betting_day(when):
    local = when.astimezone(LOCAL)
    if local.hour < 6:
        local -= timedelta(days=1)
    return local.date().isoformat()


def canonical_index(matches):
    """Index exact canonical AND existing provider-native IDs; never name-match."""
    index = {}
    for match in matches:
        if not isinstance(match, dict):
            raise ValueError("invalid canonical match record")
        event = str(match.get("match_id") or "").strip()
        if not event:
            raise ValueError("canonical match has no ID")
        payload = match.get("provider_context_json") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError as exc:
                raise ValueError("malformed canonical provider context") from exc
        if not isinstance(payload, dict):
            raise ValueError("invalid canonical provider context")
        match["_replay_context"] = payload
        keys = {event}
        # Same sources the production event_id(match) function uses.
        for field in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id"):
            native = payload.get(field)
            if native not in (None, ""):
                keys.add(str(native).strip())
        for key in keys:
            if key in index and index[key] is not match:
                raise ValueError("duplicate canonical/provider match ID: refusing uncertain join")
            index[key] = match
    return index


def _canonical_schedule_consistent(observed, scheduled):
    try:
        return abs((dt(observed) - scheduled).total_seconds()) <= 86400
    except ValueError:
        return False


def _void_or_unsettled(observed, ids):
    status = str(observed.get("status") or "").strip().lower()
    if status not in FINISHED:
        return True
    context = observed.get("_replay_context") or {}
    if (isinstance(context.get("_tbt_termination"), dict)
        and context["_tbt_termination"].get("reason")):
        return True
    return str(observed.get("winner_id") or "") not in ids


def prepare(row, generated, day, index, diagnostics):
    if not isinstance(row, dict):
        diagnostics["invalid_row"] += 1
        return None
    event = str(row.get("event_id") or "").strip()
    p1, p2 = row.get("player1"), row.get("player2")
    if not event or not isinstance(p1, dict) or not isinstance(p2, dict):
        diagnostics["missing_identity"] += 1
        return None
    a, b, winner = str(p1.get("id") or ""), str(p2.get("id") or ""), str(row.get("winner_id") or "")
    if not a or not b or a == b or winner not in {a, b}:
        diagnostics["invalid_player_identity"] += 1
        return None
    try:
        scheduled = dt(row.get("scheduled_at"))
    except ValueError:
        diagnostics["invalid_schedule"] += 1
        return None
    if scheduled - generated < MIN_PRESTART or betting_day(scheduled) != day:
        diagnostics["late_or_outside_betting_day"] += 1
        return None
    model = str(row.get("model_version") or "").strip()
    x, y = num(p1.get("probability")), num(p2.get("probability"))
    raw, public, depth = (
        num(row.get("raw_model_probability")),
        num(row.get("blinq_probability")),
        num(row.get("data_depth")),
    )
    if not model or None in (x, y, raw, public, depth):
        diagnostics["missing_model_evidence"] += 1
        return None
    if not (0 <= depth <= 1 and 0 < x < 1 and 0 < y < 1 and abs(x + y - 1) <= .02):
        diagnostics["invalid_probability"] += 1
        return None
    selected_p = x if winner == a else y
    if not (.5 <= raw < 1 and .5 <= public < 1):
        diagnostics["invalid_probability"] += 1
        return None
    if abs(selected_p - raw) > .005 or abs(public - (.5 + (raw - .5) * depth)) > .005:
        diagnostics["inconsistent_probability"] += 1
        return None
    observed = index.get(event)
    correct = None
    level = "unknown"
    if observed is None:
        diagnostics["no_canonical_event"] += 1
    else:
        ids = {str(observed.get("player1_id") or ""), str(observed.get("player2_id") or "")}
        if ids != {a, b}:
            diagnostics["canonical_player_collision"] += 1
        elif str(observed.get("tour") or "").strip().lower() not in ("", str(row.get("tour") or "").strip().lower()):
            diagnostics["canonical_tour_disagreement"] += 1
        elif not _canonical_schedule_consistent(observed.get("scheduled_at"), scheduled):
            diagnostics["canonical_schedule_disagreement"] += 1
        elif _void_or_unsettled(observed, ids):
            diagnostics["unsettled_or_void"] += 1
        else:
            correct = winner == str(observed["winner_id"])
            level = str(observed.get("tournament_level") or "unknown")
    sample = row.get("samples") if isinstance(row.get("samples"), dict) else {}
    surface_values = [num(sample.get("player1_surface_matches")), num(sample.get("player2_surface_matches"))]
    min_surface = (min(surface_values)
                   if all(v is not None and v >= 0 for v in surface_values) else None)
    ranks = [num(p1.get("rank")), num(p2.get("rank"))]
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    two_way = row.get("two_way_market") if isinstance(row.get("two_way_market"), dict) else {}
    quote_ok = False
    odds = num(betting.get("odds"))
    if row.get("priced") is True and odds is not None and odds > 1:
        try:
            quote_time = dt(betting.get("captured_at"))
            market_time = dt(two_way.get("captured_at"))
            quote_ok = (quote_time <= generated and market_time <= generated
                        and scheduled - max(quote_time, market_time) >= MIN_PRESTART
                        and str(betting.get("selection_id") or "") == winner)
        except ValueError:
            diagnostics["missing_or_invalid_quote_time"] += 1
    return {
        "event": event, "model": model, "tour": str(row.get("tour") or "unknown").upper(),
        "surface": str(row.get("surface") or "unknown").lower(), "level": level,
        "day": day, "raw": raw, "public": public, "depth": depth,
        "min_surface": min_surface, "both_ranks": all(v is not None and v > 0 for v in ranks),
        "correct": correct, "section": row.get("selected_section"),
        "quote_ok": quote_ok, "odds": odds if quote_ok else None,
        "two_way": two_way if quote_ok else {},
    }


def metrics(rows, field="raw"):
    settled = [r for r in rows if type(r.get("correct")) is bool]
    n = len(settled)
    if not n:
        return {"selected": len(rows), "settled": 0, "hit_rate": None, "brier": None,
                "log_loss": None, "ece_10": None}
    hits = sum(r["correct"] for r in settled)
    ps = [r[field] for r in settled]
    ys = [int(r["correct"]) for r in settled]
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / n
    log_loss = -sum(y * math.log(max(p, 1e-12)) +
                    (1-y) * math.log(max(1-p, 1e-12)) for p, y in zip(ps, ys)) / n
    bins = defaultdict(list)
    for p, y in zip(ps, ys):
        bins[min(9, int(p * 10))].append((p, y))
    ece = sum(len(g)/n * abs(sum(x[0] for x in g)/len(g) -
                              sum(x[1] for x in g)/len(g)) for g in bins.values())
    mean_p = sum(ps) / n
    return {"selected": len(rows), "settled": n, "hit_rate": hits/n,
            "settlement_coverage": n / len(rows) if rows else None,
            "mean_probability": mean_p, "observed_minus_predicted": hits/n - mean_p,
            "brier": brier, "log_loss": log_loss, "ece_10": ece}


def historical_cdb_coverage(matches):
    """Current canonical 2026 field availability, NEVER issuance-time features."""
    groups = defaultdict(Counter)
    for match in matches:
        ids = {str(match.get("player1_id") or ""), str(match.get("player2_id") or "")}
        if (str(match.get("winner_id") or "") not in ids
                or str(match.get("status") or "").strip().lower() not in FINISHED):
            continue
        try:
            month = dt(match.get("scheduled_at")).strftime("%Y-%m")
        except ValueError:
            continue
        if not month.startswith("2026-"):
            continue
        tour = str(match.get("tour") or "unknown").upper()
        raw = match.get("stats_json") or "{}"
        try:
            stats = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            stats = {}
        if not isinstance(stats, dict):
            stats = {}

        def observed(side, fields):
            for field in fields:
                rate = num(stats.get(side + "_" + field))
                if rate is not None and 0 <= rate <= 1:
                    return True
            return False

        s = [observed(side, ("service_points_won", "first_serve_win", "second_serve_win"))
             for side in ("p1", "p2")]
        r = [observed(side, ("return_points_won",))
             for side in ("p1", "p2")]
        bp = [observed(side, ("break_point_serve_win", "break_point_return_win"))
              for side in ("p1", "p2")]
        rank = (num(match.get("player1_rank")), num(match.get("player2_rank")))
        for key in ("all", month, "tour:" + tour, month + "|tour:" + tour):
            counter = groups[key]
            counter["completed_matches"] += 1
            counter["both_service_rates"] += int(all(s))
            counter["both_return_rates"] += int(all(r))
            counter["both_service_return_rates"] += int(all(s) and all(r))
            counter["both_break_point_rates"] += int(all(bp))
            counter["both_rank_values"] += int(all(v is not None and v > 0 for v in rank))
    return {"scope": "CURRENT_CDB_POST_MATCH_FIELD_AVAILABILITY_NOT_PIT_INFERENCE",
            "groups": {k: dict(v) for k, v in sorted(groups.items())}}


def paired_complete_day_comparison(baseline_days, alternative_days):
    """Strict same betting-day capacity, all outcomes settled in BOTH arms."""
    if len(baseline_days) != len(alternative_days):
        raise ValueError("daily comparison not aligned")
    complete = []
    for (a_day, a), (b_day, b) in zip(baseline_days, alternative_days):
        if a_day != b_day:
            raise ValueError("daily comparison keys differ")
        if len(a) != len(b):
            raise ValueError("daily candidate capacity differs")
        if not a or any(type(r["correct"]) is not bool for r in a + b):
            continue
        complete.append((len(a), sum(r["correct"] for r in a),
                         sum(r["correct"] for r in b)))
    if not complete:
        return {"complete_days": 0, "paired_capacity": 0, "status": "NO_FULLY_SETTLED_DAYS"}
    n = sum(x[0] for x in complete)
    original = sum(x[1] for x in complete) / n
    alternate = sum(x[2] for x in complete) / n
    return {"complete_days": len(complete), "paired_capacity": n,
            "baseline_accuracy": original, "alternative_accuracy": alternate,
            "difference_percentage_points": 100 * (alternate - original),
            "status": "DESCRIPTIVE_NOT_CAUSAL_OR_DEPLOYMENT_READY"}


def eligible(record, section):
    if not record["quote_ok"] or record["min_surface"] is None:
        return False
    p, d, s, odds = (record[k] for k in ("public", "depth", "min_surface", "odds"))
    if section == "value":
        m = record["two_way"]
        a, b = num(m.get("player1_odds")), num(m.get("player2_odds"))
        return (p >= .65 and d >= .75 and s >= 3 and odds >= 1.80 and
                a is not None and b is not None and a > 1 and b > 1 and
                abs(a-b)/((a+b)/2) <= .15 + 1e-12)
    if section == "top_daily":
        return p >= .70 and d >= .80 and s >= 5 and odds >= 1.50 and not eligible(record, "value")
    if section == "prime":
        return p >= .65 and d >= .80 and s >= 5 and 1 < odds < 1.50
    return False


def forward_subset(snapshots, first_betting_day):
    """Use only predeclared *future* betting days, not a retrospective sample."""
    from datetime import date
    start = date.fromisoformat(first_betting_day)
    if start < date(2026, 11, 4):
        raise ValueError("forward cohort must begin on/after the predeclared 2026-11-04 boundary")
    return [s for s in snapshots
            if dt(s["generated_at"]).astimezone(LOCAL).date() >= start]


def analyze(snapshots, matches):
    diagnostics = Counter()
    index = canonical_index(matches)
    rows_by_day = {}
    seen = set()
    for day, snapshot in sorted(anchors(snapshots).items()):
        generated = dt(snapshot["generated_at"])
        good = []
        for row in snapshot["rows"]:
            prepared = prepare(row, generated, day, index, diagnostics)
            if prepared is None:
                continue
            key = (prepared["model"], prepared["event"])
            if key in seen:
                diagnostics["repeat_event_excluded"] += 1
                continue
            seen.add(key)
            good.append(prepared)
        rows_by_day[day] = good
    grouped = defaultdict(list)
    for records in rows_by_day.values():
        for r in records:
            grouped[r["model"]].append(r)
    by_model = {}
    for model, entries in sorted(grouped.items()):
        groups = {
            "tour": lambda r: r["tour"],
            "surface": lambda r: r["surface"],
            "level": lambda r: r["level"],
            "confidence": lambda r: ("below_65" if r["raw"] < .65 else
                                     "65_70" if r["raw"] < .70 else
                                     "70_75" if r["raw"] < .75 else
                                     "75_80" if r["raw"] < .80 else "80_plus"),
            "data_depth": lambda r: ("below_80" if r["depth"] < .80 else
                                     "80_90" if r["depth"] < .90 else "90_plus"),
            "rank_availability": lambda r: ("both_known" if r["both_ranks"] else "missing"),
        }
        slices = {}
        for group_name, keyfn in groups.items():
            part = defaultdict(list)
            for row in entries:
                part[keyfn(row)].append(row)
            slices[group_name] = {k: metrics(v) for k, v in sorted(part.items())}
        by_model[model] = {
            "all_candidates_raw": metrics(entries, "raw"),
            "all_candidates_public": metrics(entries, "public"),
            "by_segment": slices,
            "rank_both_available": sum(r["both_ranks"] for r in entries),
            "serve_return_observation": "NOT_IN_SNAPSHOT_SCHEMA",
            "ranking_freshness": "NOT_IN_SNAPSHOT_SCHEMA",
        }

    variants = ("baseline_assignment", "confidence_first", "quality_first")
    section_results = defaultdict(lambda: defaultdict(list))
    per_day_methods = defaultdict(lambda: defaultdict(list))
    changes = Counter()
    for day, rows in rows_by_day.items():
        for model in sorted({r["model"] for r in rows}):
            model_rows = [r for r in rows if r["model"] == model]
            for section in SECTIONS:
                baseline = [r for r in model_rows if r["section"] == section]
                if not baseline:
                    continue
                pool = [r for r in model_rows if eligible(r, section)]
                if any(not eligible(r, section) for r in baseline):
                    diagnostics["baseline_eligibility_disagreement"] += 1
                    continue
                capacity = len(baseline)
                methods = {
                    "baseline_assignment": baseline,
                    "confidence_first": sorted(pool, key=lambda r: (r["public"], r["depth"], r["event"]), reverse=True)[:capacity],
                    "quality_first": sorted(pool, key=lambda r: (r["depth"], r["min_surface"], r["public"], r["event"]), reverse=True)[:capacity],
                }
                if any(len(rows_) != capacity for rows_ in methods.values()):
                    diagnostics["unequal_capacity_replay"] += 1
                    continue
                group = f"{model}|{section}"
                for name, chosen in methods.items():
                    section_results[group][name].extend(chosen)
                    per_day_methods[group][name].append((day, chosen))
                for name in variants[1:]:
                    changes[group + "|" + name] += len({r["event"] for r in baseline} ^
                                                        {r["event"] for r in methods[name]}) // 2
    replay = {}
    for key, methods in sorted(section_results.items()):
        entry = {name: metrics(methods.get(name, []), "public") for name in variants}
        baseline = entry["baseline_assignment"]
        entry["changed_selections"] = {
            name: changes[key + "|" + name] for name in variants[1:]
        }
        entry["paired_complete_day_replay"] = {
            name: paired_complete_day_comparison(
                per_day_methods[key]["baseline_assignment"],
                per_day_methods[key][name],
            ) for name in variants[1:]
        }
        entry["comparison_readiness"] = (
            "DESCRIPTIVE_ONLY" if baseline["settled"] >= 100 and
            all(entry[name]["settled"] == baseline["selected"] for name in variants)
            else "INSUFFICIENT_OR_UNEQUAL_OUTCOME_COVERAGE"
        )
        replay[key] = entry
    return {
        "schema": 1,
        "status": "READ_ONLY_REPLAY_NO_DEPLOY",
        "anchor_policy": "earliest_generation_at_or_after_06_local_per_betting_day",
        "snapshot_generations": len(snapshots),
        "anchored_days": len(rows_by_day),
        "evaluated_unique_model_events": sum(len(x) for x in grouped.values()),
        "diagnostics": dict(sorted(diagnostics.items())),
        "model_quality_A": by_model,
        "selector_comparison_B": replay,
        "interpretation_limits": [
            "Only canonical completed/finished records with native-ID, player, tour and schedule match are scored.",
            "CDB break-point rates use break_point_serve_win/break_point_return_win, never count fields.",
            "Stored assignment is not public issuance; results are replay of frozen candidate decisions.",
            "Unmatched or unsettled events are excluded from accuracy, never inferred as wins/losses.",
            "The available snapshot cannot establish serve/return availability or ranking timestamps.",
            "Current canonical 2026 stat coverage is post-match storage only; not a point-in-time feature audit.",
            "Paired full-day comparisons are descriptive only; unequal outcome coverage is not evidence of uplift.",
            "Distinct frozen model versions never share a quality denominator.",
            "One earliest generation per betting day avoids repeated scoring of daily refreshes.",
            "Quality-first is predeclared, uses no outcomes or EV, and preserves baseline section capacity.",
            "No live champion swap, no CDB writes, no provider calls, no automatic selector promotion.",
        ],
        "provider_requests": 0,
        "production_mutated": False,
        "recommended_production_action": "NONE_UNTIL_INDEPENDENT_FORWARD_SHADOW_AND_OWNER_REVIEW",
    }


def verify_pins(before_path, after_path, names, directory, *, require_manifest=False):
    before = json.loads(Path(before_path).read_text())
    after = json.loads(Path(after_path).read_text())
    def inventory(release):
        return {a["name"]: a for a in release.get("assets", [])}
    old, new = inventory(before), inventory(after)
    digest_list = {}
    manifest_path = Path(directory) / "_tbt_bundle_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for name in names:
        if name not in old or name not in new:
            raise ValueError("release asset absent: " + name)
        first, last = old[name], new[name]
        pinned = ("id", "size", "updated_at")
        if any(first.get(k) != last.get(k) for k in pinned):
            raise ValueError("release asset changed during replay: " + name)
        file_path = Path(directory) / name
        if not file_path.exists() or file_path.stat().st_size != first["size"]:
            raise ValueError("release file missing or partial: " + name)
        digest = sha(file_path)
        expected = (manifest.get("files") or {}).get(name)
        expected_sha = expected.get("sha256") if isinstance(expected, dict) else None
        if expected_sha and expected_sha != digest:
            raise ValueError("release bundle checksum mismatch: " + name)
        if require_manifest and not expected_sha and name != "_tbt_bundle_manifest.json":
            raise ValueError("required release bundle checksum absent: " + name)
        digest_list[name] = {"sha256": digest, "asset_id": first["id"],
                             "bytes": first["size"], "bundle_manifest_verified": bool(expected_sha)}
    return digest_list


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", nargs="+", required=True, type=Path)
    parser.add_argument("--canonical", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--forward-out", type=Path)
    parser.add_argument("--forward-from", default="2026-11-04")
    parser.add_argument("--prediction-before", type=Path)
    parser.add_argument("--prediction-after", type=Path)
    parser.add_argument("--history-before", type=Path)
    parser.add_argument("--history-after", type=Path)
    args = parser.parse_args()
    import pandas as pd
    evidence = {}
    if args.prediction_before and args.prediction_after:
        folder = args.snapshots[0].parent
        names = [p.name for p in args.snapshots] + ["_tbt_bundle_manifest.json"]
        evidence["predictions"] = verify_pins(args.prediction_before, args.prediction_after, names, folder)
    if args.history_before and args.history_after:
        folder = args.canonical.parent
        evidence["canonical"] = verify_pins(
            args.history_before, args.history_after,
            [args.canonical.name, "history_manifest.json", "_tbt_bundle_manifest.json"],
            folder, require_manifest=True,
        )
        years = json.loads((folder / "history_manifest.json").read_text()).get("years", {})
        expected = (years.get("2026") or {}).get("sha256")
        if not expected or expected != sha(args.canonical):
            raise ValueError("canonical year differs from history manifest SHA256")
    columns = ["match_id", "player1_id", "player2_id", "winner_id", "status",
               "scheduled_at", "tour", "tournament_level", "provider_context_json"]
    columns.extend(("stats_json", "player1_rank", "player2_rank"))
    matches = pd.read_parquet(args.canonical, columns=columns).to_dict("records")
    snapshots = load_snapshots(args.snapshots)
    report = analyze(snapshots, matches)
    report["canonical_cdb_field_coverage"] = historical_cdb_coverage(matches)
    report["evidence"] = evidence
    report["github_source_sha"] = os.getenv("GITHUB_SHA")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    if args.forward_out:
        forward = analyze(forward_subset(snapshots, args.forward_from), matches)
        forward["cohort"] = "OUT_OF_TIME_AFTER_POLICY_FREEZE"
        forward["prospective_from_betting_day"] = args.forward_from
        forward["policy_predeclared_utc"] = "2026-11-03T20:43:00Z"
        forward["historical_comparison_not_prospectively_reused"] = True
        forward["evidence"] = evidence
        forward["github_source_sha"] = os.getenv("GITHUB_SHA")
        forward["operational_readiness"] = (
            "RESEARCH_ONLY_NO_POLICY_PROMOTION"
            if forward["evaluated_unique_model_events"]
            else "AWAITING_FUTURE_SNAPSHOT"
        )
        args.forward_out.parent.mkdir(parents=True, exist_ok=True)
        args.forward_out.write_text(
            json.dumps(forward, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        )
        print(json.dumps({
            "forward_betting_days": forward["anchored_days"],
            "forward_candidates": forward["evaluated_unique_model_events"],
            "state": forward["operational_readiness"],
        }))
    print(json.dumps({
        "status": report["status"], "anchored_days": report["anchored_days"],
        "unique": report["evaluated_unique_model_events"],
        "models": {k: v["all_candidates_raw"] for k, v in report["model_quality_A"].items()},
        "comparisons": {k: v["comparison_readiness"] for k, v in report["selector_comparison_B"].items()},
        "report": str(args.out),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
