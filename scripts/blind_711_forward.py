#!/usr/bin/env python3
"""Prospective blind TOP/VALUE paired shadow audit; NO production/model/CDB changes."""
import argparse
import base64
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import subprocess

CHAMPION = "v201-20260925T204608601094Z"
CANDIDATE = "v201-20261014T183415325901Z"
SECTIONS = {"top_daily", "value"}
ARCHIVE = "audit/model-711-blind"


def ts(s):
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00")) if isinstance(s, str) else None
        return d.astimezone(timezone.utc) if d and d.tzinfo else None
    except (ValueError, OverflowError):
        return None


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def serial(x):
    return (json.dumps(x, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n").encode()


def capture(ledger, shadows, now, previously=()):
    """Freeze only unplayed TOP/VALUE picks; never read a completed outcome."""
    by_event = defaultdict(list)
    for s in shadows:
        if not isinstance(s, dict) or (s.get("production_model_version"), s.get("challenger_model_version")) != (CHAMPION, CANDIDATE):
            continue
        for name in ("event_id", "match_id"):
            if s.get(name):
                by_event[(name, str(s[name]))].append(s)
    existing = {f["key"] for f in previously}
    frozen, reasons = {}, Counter()
    for row in ledger:
        if not isinstance(row, dict) or str(row.get("tour") or "").lower() not in ("atp", "wta"):
            continue
        event = str(row.get("event_id") or row.get("id") or "").strip()
        match = str(row.get("match_id") or "").strip()
        ids = [str((row.get(k) or {}).get("id") or "") for k in ("player1", "player2")]
        if not event or not all(ids) or ids[0] == ids[1]:
            continue
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict) or pub.get("section") not in SECTIONS or pub.get("market") != "match_winner":
                continue
            outcome = pub.get("result") if isinstance(pub.get("result"), dict) else {}
            issued, start = ts(pub.get("issued_at")), ts(outcome.get("scheduled_at") or row.get("scheduled_at"))
            if not issued or not start or not issued <= now < start:
                reasons["not_open_before_match"] += 1
                continue
            if pub.get("excluded_reason") or pub.get("publication_status") in ("pending", "expired_unpublished"):
                reasons["not_confirmed_published"] += 1
                continue
            if type(outcome.get("correct")) is bool or str(outcome.get("status") or "").lower() in ("settled", "win", "loss", "void"):
                reasons["outcome_already_present"] += 1
                continue
            price, selected = num(pub.get("odds")), str(pub.get("selection_id") or "")
            if price is None or price < 1.5 or selected not in ids:
                reasons["price_below_1_50_or_identity"] += 1
                continue
            key = event + "|" + selected
            if key in existing:
                reasons["already_frozen"] += 1
                continue
            pairs = by_event.get(("event_id", event), []) or by_event.get(("match_id", match), [])
            pairs = {(s.get("match_id"), s.get("captured_at")): s for s in pairs}
            if len(pairs) != 1:
                reasons["no_unique_model_pair"] += 1
                continue
            pair = next(iter(pairs.values()))
            taken = ts(pair.get("captured_at"))
            if not taken or not taken <= now < start or ts(pair.get("scheduled_at")) != start:
                reasons["shadow_timestamp_invalid"] += 1
                continue
            if pair.get("status") != "pending" or pair.get("target_player1_win") is not None or pair.get("result_winner_id") is not None:
                reasons["shadow_outcome_already_present"] += 1
                continue
            if str(pair.get("tour") or "").lower() != str(row.get("tour") or "").lower() or [str(pair.get("player1_id")), str(pair.get("player2_id"))] != ids:
                reasons["shadow_identity_mismatch"] += 1
                continue
            a, b = num(pair.get("production_player1_probability")), num(pair.get("challenger_player1_probability"))
            if a is None or b is None or not (0 < a < 1 and 0 < b < 1):
                reasons["invalid_probabilities"] += 1
                continue
            p1_selected = selected == ids[0]
            record = {
                "key": key, "event_id": event, "match_id": match, "tour": str(row["tour"]).lower(),
                "player1_id": ids[0], "player2_id": ids[1], "selected_id": selected,
                "sections": [pub["section"]], "odds": price,
                "issued_at": issued.isoformat(), "scheduled_at": start.isoformat(),
                "shadow_captured_at": taken.isoformat(), "frozen_at": now.isoformat(),
                "timing": "before_issued" if taken <= issued else "after_issued_before_start",
                "champion_probability": a if p1_selected else 1-a,
                "candidate_probability": b if p1_selected else 1-b,
            }
            old = frozen.get(key)
            if old is None:
                frozen[key] = record
            elif record["issued_at"] == old["issued_at"]:
                if record["odds"] != old["odds"]:
                    raise ValueError("Conflicting same-time published price")
                old["sections"] = sorted(set(old["sections"] + record["sections"]))
            elif record["issued_at"] < old["issued_at"]:
                frozen[key] = record
    return list(frozen.values()), dict(reasons)


def grade(frozen, ledger, now):
    """Join outcomes only AFTER immutable pre-start capture."""
    events = defaultdict(list)
    for row in ledger:
        if isinstance(row, dict) and row.get("event_id"):
            events[str(row["event_id"])].append(row)
    settled, rejected = [], Counter()
    for record in frozen:
        start, taken = ts(record.get("scheduled_at")), ts(record.get("frozen_at"))
        if not start or not taken or taken >= start:
            rejected["bad_frozen_timestamp"] += 1
            continue
        if now <= start:
            rejected["not_started"] += 1
            continue
        rows = events.get(record["event_id"], [])
        if len(rows) != 1 or str(rows[0].get("tour") or "").lower() != record["tour"]:
            rejected["ambiguous_settlement_identity"] += 1
            continue
        row = rows[0]
        ids = [str((row.get(k) or {}).get("id") or "") for k in ("player1", "player2")]
        if ids != [record["player1_id"], record["player2_id"]]:
            rejected["player_identity_changed"] += 1
            continue
        outcomes = []
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict) or pub.get("section") not in record["sections"] or pub.get("market") != "match_winner":
                continue
            if str(pub.get("selection_id") or "") != record["selected_id"] or ts(pub.get("issued_at")) != ts(record["issued_at"]):
                continue
            result = pub.get("result") if isinstance(pub.get("result"), dict) else {}
            if str(result.get("status") or "").lower() in ("void", "retired", "walkover", "cancelled", "canceled"):
                continue
            if type(result.get("correct")) is bool:
                outcomes.append(result["correct"])
        if not outcomes or len(set(outcomes)) != 1:
            rejected["unsettled_or_inconsistent"] += 1
            continue
        settled.append({**record, "correct": outcomes[0]})
    return settled, dict(rejected)


def metrics(rows):
    n = len(rows)
    if not n:
        return {"n": 0, "roi": None}
    won = sum(r["correct"] for r in rows)
    profit = sum(r["odds"] - 1 if r["correct"] else -1 for r in rows)
    res = {"n": n, "wins": won, "hit_rate": won/n, "roi": profit/n, "units": profit}
    for name in ("champion", "candidate"):
        res[name] = {
            "brier": sum((int(r["correct"]) - r[name+"_probability"])**2 for r in rows)/n,
            "log_loss": sum(-math.log(r[name+"_probability"] if r["correct"] else 1-r[name+"_probability"]) for r in rows)/n,
        }
        for limit in (0.65, 0.75, 0.80):
            chosen = [r for r in rows if r[name+"_probability"] >= limit]
            res[name][str(limit)] = {
                "n": len(chosen), "wins": sum(x["correct"] for x in chosen),
                "roi": sum(x["odds"] - 1 if x["correct"] else -1 for x in chosen)/len(chosen) if chosen else None,
            }
    return res


def gh(*args, stdin=None):
    return subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=True, timeout=120).stdout


def get(repo, path):
    try:
        data = json.loads(gh("api", "repos/"+repo+"/contents/"+path))
    except subprocess.CalledProcessError as e:
        if "404" in (e.stderr or ""):
            return None, None
        raise
    return json.loads(base64.b64decode(data["content"])), data["sha"]


def save(repo, path, data, sha):
    payload = {"message": "[audit-only] seal pre-result TOP/VALUE 7.1.1 blind records",
               "content": base64.b64encode(serial(data)).decode()}
    if sha:
        payload["sha"] = sha
    gh("api", "--method", "PUT", "repos/"+repo+"/contents/"+path, "--input", "-", stdin=json.dumps(payload))
    readback, digest = get(repo, path)
    if digest is None or serial(readback) != serial(data):
        raise RuntimeError("Blind snapshot private readback failure")
    return sha256(serial(data)).hexdigest()


def run(repo, now, output):
    from _bootstrap import ROOT
    from release_store import ReleaseStore
    if json.loads(gh("repo", "view", repo, "--json", "visibility"))["visibility"] != "PRIVATE":
        raise RuntimeError("Blind records must stay in PRIVATE repository")
    base = ROOT/".cache/tbt/711-blind"
    data = {}
    for tag, names in (("tbt-predictions-v1", ("ledger.json",)),
                       ("tbt-model-shadow-v1", ("shadow_ledger.json", "shadow_report.json"))):
        store = ReleaseStore(repo, tag, base/tag)
        store.download(required_names=names, require_bundle_manifest=True)
        for name in names:
            data[name] = json.loads((store.directory/name).read_text())
    last = data["shadow_report.json"]
    correct_pair = (last.get("production_model_version"), last.get("challenger_model_version")) == (CHAMPION, CANDIDATE)
    saved, today, today_sha = [], None, None
    for age in range(22):
        day = (now - timedelta(days=age)).date().isoformat()
        obj, sha = get(repo, ARCHIVE+"/"+day+".json")
        if obj is None:
            continue
        if obj.get("schema") != 1 or obj.get("pair") != [CHAMPION, CANDIDATE]:
            raise RuntimeError("Unrecognized archived blind cohort")
        saved.extend(obj["entries"])
        if age == 0:
            today, today_sha = obj, sha
    if len({r["key"] for r in saved}) != len(saved):
        raise RuntimeError("Duplicate private blind cohort keys")
    fresh, rejected = capture(data["ledger.json"], data["shadow_ledger.json"], now, saved) if correct_pair else ([], {"model_pair_changed": 1})
    digest = None
    if fresh:
        day = now.date().isoformat()
        obj = {"schema": 1, "day": day, "pair": [CHAMPION, CANDIDATE], "entries": (today["entries"] if today else []) + fresh}
        digest = save(repo, ARCHIVE+"/"+day+".json", obj, today_sha)
        saved += fresh
    graded, reasons = grade(saved, data["ledger.json"], now)
    groups = {"all": metrics(graded)}
    for tour in ("atp", "wta"):
        groups[tour] = metrics([r for r in graded if r["tour"] == tour])
    for section in ("top_daily", "value"):
        groups[section] = metrics([r for r in graded if section in r["sections"]])
    for timing in ("before_issued", "after_issued_before_start"):
        groups[timing] = metrics([r for r in graded if r["timing"] == timing])
    report = {
        "status": "REVIEWABLE" if len(graded) >= 100 and groups["atp"]["n"] >= 50 and groups["wta"]["n"] >= 50 else "ACCUMULATING_FORWARD_BLIND",
        "generated_at": now.isoformat(), "model_pair_ok": correct_pair,
        "new_frozen": len(fresh), "frozen_rolling_22d": len(saved), "graded": len(graded),
        "freeze_rejections": rejected, "grade_rejections": reasons, "metrics": groups,
        "sealed_private_digest": digest, "provider_requests": 0,
        "CDB_mutated": False, "production_mutated": False, "model_promoted": False,
        "note": "Prospective frozen issued TOP/VALUE only. Post-issuance captures are separated; no fabricated odds or alternative selections.",
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(serial(report))
    print(json.dumps(report, allow_nan=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    ap.add_argument("--out", default=".cache/tbt/711-blind/report.json")
    args = ap.parse_args()
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("Missing private audit credentials")
    run(args.data_repository, datetime.now(timezone.utc), args.out)
