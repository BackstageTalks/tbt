"""Reconcile original sent daily Telegram Aces through native Results CAS.

Uses the same exact-player match-status snapshot and native projection grader
as website Results. Only an authenticated private sender's immutable, pre-start
Telegram receipt may supply the missing O/U contract. No tennis provider,
CDB/model, Telegram or ad-hoc archive writer is invoked.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import math

from .feed import _betting_day_key
from .local_ace_results import local_ace_result_odds
from .match_status import _grade_runtime_projection, verified_terminal_statuses
from .results_archive import (
    _archive_record, _identity, load_settled_results_archive,
    save_settled_results_archive,
)

MAX_ACES = 40


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _number(value):
    try:
        val = float(value)
        return val if math.isfinite(val) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _frozen_receipt(day, receipt):
    if not isinstance(receipt, dict) or receipt.get("status") != "sent":
        raise ValueError("Confirmed daily Telegram receipt required")
    mids = receipt.get("message_ids")
    if (not isinstance(mids, list) or len(mids) < 1
            or len(mids) > 8 or any(type(i) is not int or i <= 0 for i in mids)):
        raise ValueError("Original Telegram message IDs required")
    sent_at = _time(receipt.get("sent_at"))
    if sent_at is None or _betting_day_key(sent_at) != day:
        raise ValueError("Invalid original Telegram send time")
    rows = receipt.get("rows")
    if not isinstance(rows, list) or len(rows) > 80:
        raise ValueError("Invalid sent rows")
    aces = [r for r in rows if isinstance(r, dict) and r.get("channel") == "aces"]
    if len(aces) > MAX_ACES:
        raise ValueError("Too many original Aces")
    seen = set()
    for ref in aces:
        event, selection = str(ref.get("event_id") or ""), str(ref.get("selection_id") or "")
        side = str(ref.get("projection_direction") or "").lower()
        line, odds, projection = (
            _number(ref.get("market_line")), _number(ref.get("odds")),
            _number(ref.get("projection")))
        scheduled = _time(ref.get("scheduled_at"))
        key = (event, selection, side, line)
        if (not all((event, selection)) or ref.get("section") != "ace"
                or ref.get("market") != "aces" or side not in {"over", "under"}
                or line is None or line < 0 or line * 2 != round(line * 2)
                or odds is None or not 1.60 <= odds <= 1.80
                or projection is None or scheduled is None
                or sent_at >= scheduled or _betting_day_key(scheduled) != day
                or ref.get("price_basis") != "local_aces_statistical_v1"
                or ref.get("publication_key") != (
                    f"local-aces-ou-v1:{event}:{selection}:{side}:{line:.1f}")
                or key in seen):
            raise ValueError("Invalid or duplicated frozen original Aces contract")
        seen.add(key)
    return sent_at, aces


def _source_for(ref, feed, archived):
    event, selection, scheduled = (str(ref.get(k) or "")
                                    for k in ("event_id", "selection_id", "scheduled_at"))
    candidates = list(feed.get("ace_picks") or []) + list(archived)
    found = []
    for row in candidates:
        if (not isinstance(row, dict)
                or str(row.get("event_id") or "") != event
                or _time(row.get("scheduled_at")) != _time(scheduled)):
            continue
        p1, p2 = row.get("player1"), row.get("player2")
        if (not isinstance(p1, dict) or not isinstance(p2, dict)
                or not str(p1.get("id") or "") or not str(p2.get("id") or "")
                or str(p1["id"]) == str(p2["id"])
                or selection not in {str(p1["id"]), str(p2["id"])}):
            continue
        found.append(row)
    if not found:
        return None
    rosters = {
        tuple(sorted((str(r["player1"]["id"]), str(r["player2"]["id"]))))
        for r in found
    }
    if len(rosters) != 1:
        raise ValueError("Conflicting source player identity")
    return found[0]


def _candidate(day, ref, sent_at, source_row, statuses):
    event = str(ref["event_id"])
    status_row = statuses.get(event)
    if not isinstance(status_row, dict):
        return None
    original = {
        "section": "ace", "market": "aces",
        "selection_id": str(ref["selection_id"]),
        "publication_key": str(ref["publication_key"]),
        "publication_status": "published",
        "price_contract": "player_total_ou",
        "ou_side": str(ref["projection_direction"]),
        "market_line": _number(ref["market_line"]),
        "selection": (str(ref.get("name") or "Player") + " "
                      + str(ref["projection_direction"]).title() + " "
                      + str(ref["market_line"]) + " Aces"),
        "projection_scope": "player", "projection_metric": "aces",
        "projection": _number(ref["projection"]),
        "issued_at": sent_at.isoformat(),
        "odds": _number(ref["odds"]),
        "price_status": "priced_projection",
        "price_basis": "local_aces_statistical_v1",
        "source": "confirmed_telegram_ou_reissue",
    }
    if local_ace_result_odds(source_row, original) != original["odds"]:
        raise ValueError("Unverified original local Aces quote")
    scored = _grade_runtime_projection(source_row, original, status_row)
    if scored is None:
        return None
    result = scored.get("result") or {}
    if (result.get("runtime_source") != "match_status_snapshot"
            or (type(result.get("correct")) is not bool and result.get("void") is not True)):
        return None
    result["recovery_evidence"] = "original_telegram_receipt_verified_match_status_native_v1"
    row = {k: deepcopy(source_row[k]) for k in (
        "event_id", "scheduled_at", "betting_day", "tour",
        "tournament", "tournament_id", "round", "surface")
        if k in source_row}
    row.update(event_id=event, scheduled_at=str(ref["scheduled_at"]),
               betting_day=day, player1=deepcopy(source_row["player1"]),
               player2=deepcopy(source_row["player2"]),
               market_publications=[scored],
               runtime_result_overlay=True,
               archive_source="verified_match_status_snapshot")
    return _archive_record(row, scored, sent_at.isoformat())


def reconcile(day, receipt, feed, snapshot, *, dry_run=True,
              expected_digest=None, now=None):
    """Dry-run then CAS append; independently read back every original contract."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Reconciliation requires timezone-aware clock")
    if (not isinstance(day, str) or not len(day) == 10
            or day not in {_betting_day_key(now), _betting_day_key(now - timedelta(days=1)),
                           _betting_day_key(now - timedelta(days=2))}):
        raise ValueError("Only current or recent betting day may be reconciled")
    if not isinstance(feed, dict) or not isinstance(snapshot, dict):
        raise ValueError("Live serving snapshot unavailable")
    sent_at, refs = _frozen_receipt(day, receipt)
    archived = load_settled_results_archive()
    statuses = verified_terminal_statuses(snapshot.get("statuses"))
    existing = {}
    for row in archived:
        if not isinstance(row, dict):
            continue
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict):
                continue
            identity = _identity(row, pub)
            existing.setdefault(identity, []).append(pub)
    pending, candidates, already = 0, {}, 0
    for ref in refs:
        source = _source_for(ref, feed, archived)
        if source is None:
            pending += 1
            continue
        proposal = _candidate(day, ref, sent_at, source, statuses)
        if proposal is None:
            pending += 1
            continue
        pub = proposal["market_publications"][0]
        identity = _identity(proposal, pub)
        if identity in candidates:
            raise ValueError("Duplicated original archived contract")
        original = existing.get(identity) or []
        if len(original) > 1:
            raise ValueError("Ambiguous original archived contract")
        if original:
            old = original[0]
            frozen_fields = ("publication_key","selection_id","market_line",
                             "ou_side","odds","issued_at","price_basis")
            result_fields = ("correct","void","actual_count","runtime_source",
                             "staked_units","profit_units")
            if any(old.get(k) != pub.get(k) for k in frozen_fields) or any(
                    (old.get("result") or {}).get(k) != (pub.get("result") or {}).get(k)
                    for k in result_fields):
                raise ValueError("Conflicting original archived contract")
            already += 1
        else:
            candidates[identity] = proposal
    digest = sha256(json.dumps([
        (key, candidates[key]["market_publications"][0])
        for key in sorted(candidates)
    ], sort_keys=True, default=str).encode("utf-8")).hexdigest()
    metrics = {"day":day,"expected_aces":len(refs),"already_verified":already,
               "net_new_aces":len(candidates),"pending_evidence":pending,
               "provider_requests":0,"cdb_writes":0,"telegram_sends":0,
               "digest":digest}
    if dry_run:
        return {"status":"dry_run",**metrics}
    if expected_digest != digest:
        raise ValueError("Dry-run evidence changed before commit")
    if candidates:
        write = save_settled_results_archive(list(candidates.values()))
        if (write.get("verified") is not True
                or write.get("added") != len(candidates)
                or write.get("updated") != 0):
            raise RuntimeError("Results CAS append readback mismatch")
    readback = load_settled_results_archive()
    read_ids = {}
    for row in readback:
        if not isinstance(row, dict):
            continue
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict):
                continue
            key = _identity(row, pub)
            if key in candidates:
                read_ids.setdefault(key, []).append(pub)
    for key, proposal in candidates.items():
        actual = read_ids.get(key) or []
        expected = proposal["market_publications"][0]
        if (len(actual) != 1
                or any(actual[0].get(k) != expected.get(k) for k in (
                    "publication_key","selection_id","odds","market_line",
                    "ou_side","issued_at"))
                or any((actual[0].get("result") or {}).get(k) !=
                       (expected.get("result") or {}).get(k)
                       for k in ("correct","void","actual_count","runtime_source"))):
            raise RuntimeError("Independent Results read-back mismatch")
    return {"status":"verified","readback_new_aces":len(read_ids),**metrics}
