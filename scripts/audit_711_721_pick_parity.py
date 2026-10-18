#!/usr/bin/env python3
"""Read-only parity audit of 7.1.1 and 7.2.1 TOP/VALUE picks.

Use independently frozen, before-start selection candidate snapshots from
build_selection_candidate_snapshot() and the canonical settlement ledger.
Same event+market+selection always has one canonical outcome. Different picks,
section changes, and independent prices are reported separately.
No changes to CDB, serving models, predictions or market data.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

SECTIONS = {"top_daily", "value"}
VOID = {"void", "retired", "walkover", "cancelled", "canceled"}


def _time(value):
    if not isinstance(value, str):
        raise ValueError("Missing point-in-time timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError) as exc:
        raise ValueError("Invalid point-in-time timestamp") from exc
    if dt.tzinfo is None:
        raise ValueError("Naive point-in-time timestamp")
    return dt.astimezone(timezone.utc)


def _ids(row):
    ids = tuple(str((row.get(side) or {}).get("id") or "").strip()
                for side in ("player1", "player2"))
    if not all(ids) or ids[0] == ids[1]:
        raise ValueError("Missing or ambiguous player IDs")
    return ids


def _picks(snapshot):
    if (not isinstance(snapshot, dict) or snapshot.get("schema") != 1
            or not isinstance(snapshot.get("rows"), list)):
        raise ValueError("Expected immutable selection candidate snapshot")
    if (snapshot.get("scope") or {}).get("post_match_fields_excluded") is not True:
        raise ValueError("Snapshot lacks pre-result provenance guarantee")
    frozen_at = _time(snapshot.get("generated_at"))
    picks = {}
    for row in snapshot["rows"]:
        if not isinstance(row, dict):
            raise ValueError("Malformed snapshot row")
        if row.get("selected_section") not in SECTIONS:
            continue
        if any(k in row for k in ("result", "correct", "outcome", "target_player1_win")):
            raise ValueError("Post-match fields leaked into frozen pick")
        if str(row.get("tour") or "").lower() not in {"atp", "wta"}:
            raise ValueError("Selection not ATP/WTA singles")
        event = str(row.get("event_id") or "").strip()
        start = _time(row.get("scheduled_at"))
        if not event or frozen_at >= start:
            raise ValueError("Missing event or snapshot created after match start")
        players = _ids(row)
        bet = row.get("betting")
        if not isinstance(bet, dict) or bet.get("market", "match_winner") != "match_winner":
            raise ValueError("Selection has no match-winner market")
        side = str(bet.get("selection_id") or "").strip()
        if side not in players:
            raise ValueError("Selection does not match immutable player ID")
        try:
            odds = float(bet.get("odds"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Selected pick has no real odds") from exc
        if not math.isfinite(odds) or odds < 1.50:
            raise ValueError("Selected pick below required odds >=1.50")
        if bet.get("captured_at") is not None and _time(bet["captured_at"]) > frozen_at:
            raise ValueError("Odds captured after frozen snapshot")
        key = (event, "match_winner", side)
        if key in picks:
            raise ValueError("Duplicate selected event/market/player within one snapshot")
        picks[key] = {
            "event": event, "side": side, "players": players,
            "tour": row["tour"].lower(), "scheduled": start,
            "section": row["selected_section"], "odds": odds,
            "betting_day": bet.get("betting_day"),
        }
    return picks


def _results(ledger, relevant_events):
    if not isinstance(ledger, list):
        raise ValueError("Expected canonical predictions ledger list")
    result = {}
    for row in ledger:
        if not isinstance(row, dict) or not row.get("event_id"):
            continue
        if str(row.get("tour") or "").lower() not in {"atp", "wta"}:
            continue
        event = str(row["event_id"])
        if event not in relevant_events:
            continue
        players = _ids(row)
        resolved = set()
        is_void = False
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict) or pub.get("market") != "match_winner":
                continue
            published_result = pub.get("result")
            if not isinstance(published_result, dict):
                continue
            status = str(published_result.get("status") or "").lower()
            if status in VOID:
                is_void = True
                continue
            correct = published_result.get("correct")
            side = str(pub.get("selection_id") or "")
            if type(correct) is bool and side in players:
                resolved.add(side if correct else (
                    players[1] if side == players[0] else players[0]
                ))
        if len(resolved) > 1 or (resolved and is_void):
            raise ValueError("Contradictory canonical settlement for event " + event)
        value = {
            "players": players, "tour": str(row["tour"]).lower(),
            "outcome": "settled" if resolved else "void" if is_void else "pending",
            "winner": next(iter(resolved)) if resolved else None,
        }
        if event in result and result[event] != value:
            raise ValueError("Conflicting canonical ledger identities/outcomes")
        result[event] = value
    return result


def _grade(pick, outcomes):
    result = outcomes.get(pick["event"])
    if result is None:
        return "unverified"
    if set(result["players"]) != set(pick["players"]) or result["tour"] != pick["tour"]:
        raise ValueError("Canonical identity mismatch for event " + pick["event"])
    if result["outcome"] != "settled":
        return result["outcome"]
    return "win" if pick["side"] == result["winner"] else "loss"


def _summary(items, outcomes):
    grades = [(_grade(p, outcomes), p["odds"]) for p in items]
    settled = [(g, o) for g, o in grades if g in {"win", "loss"}]
    wins = sum(g == "win" for g, _ in settled)
    profit = sum(o - 1 if g == "win" else -1 for g, o in settled)
    return {
        "selected": len(items), "settled": len(settled), "wins": wins,
        "losses": len(settled) - wins,
        "void": sum(g == "void" for g, _ in grades),
        "pending_or_unverified": sum(g in {"pending", "unverified"} for g, _ in grades),
        "hit_rate": wins / len(settled) if settled else None,
        "roi": profit / len(settled) if settled else None,
        "profit_units": profit,
    }


def compare(snapshot_711, snapshot_721, ledger):
    left, right = _picks(snapshot_711), _picks(snapshot_721)
    outcomes = _results(ledger, {key[0] for key in set(left) | set(right)})
    overlap = set(left) & set(right)
    only_left, only_right = set(left) - overlap, set(right) - overlap
    verified = 0
    for key in overlap:
        a, b = left[key], right[key]
        if a["tour"] != b["tour"] or set(a["players"]) != set(b["players"]):
            raise ValueError("Same pick key has different fixture identity")
        # Both are graded from ONE authoritative outcome, never separately
        # model-produced labels. Conflicting canonical results fail closed.
        grade_a, grade_b = _grade(a, outcomes), _grade(b, outcomes)
        if grade_a != grade_b:
            raise AssertionError("Same selected player settled differently")
        verified += grade_a in {"win", "loss", "void"}
    opposite_events = {k[0] for k in only_left} & {k[0] for k in only_right}
    by_section = {
        section: {
            "7.1.1": _summary([p for p in left.values() if p["section"] == section], outcomes),
            "7.2.1": _summary([p for p in right.values() if p["section"] == section], outcomes),
        }
        for section in ("top_daily", "value")
    }
    return {
        "schema": 1, "status": "OBSERVATIONAL_NOT_PROMOTION_EVIDENCE",
        "model_pair": ["7.1.1", "7.2.1"],
        "shared_exact_picks": len(overlap),
        "shared_settled_or_void_verified": verified,
        "shared_outcome_disagreements": 0,
        "shared_7_1_1": _summary([left[k] for k in overlap], outcomes),
        "shared_7_2_1": _summary([right[k] for k in overlap], outcomes),
        "only_7_1_1": _summary([left[k] for k in only_left], outcomes),
        "only_7_2_1": _summary([right[k] for k in only_right], outcomes),
        "same_pick_moved_top_value": sum(
            left[k]["section"] != right[k]["section"] for k in overlap),
        "shared_picks_with_changed_price": sum(
            left[k]["odds"] != right[k]["odds"] for k in overlap),
        "same_fixture_different_selected_side": len(opposite_events),
        "by_section": by_section,
        "note": (
            "Exact pick is event+market+selected player (not category or model probability). "
            "Shared win/loss is determined from one canonical result. Different quoted "
            "prices may change ROI. Opposite selections and unique matches are scored "
            "separately. Unsettled records never count as losses."
        ),
        "production_mutated": False, "provider_requests": 0, "CDB_mutated": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--v711", type=Path, required=True)
    parser.add_argument("--v721", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sources = [args.v711, args.v721, args.ledger]
    report = compare(*(json.loads(p.read_text(encoding="utf-8")) for p in sources))
    report["source_sha256"] = {
        name: sha256(p.read_bytes()).hexdigest()
        for name, p in zip(("v711", "v721", "ledger"), sources)
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")
    print(json.dumps(report, allow_nan=False, sort_keys=True))


if __name__ == "__main__":
    main()
