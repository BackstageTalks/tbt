"""Offer SHADOW testing: virtual (never published) picks in excluded categories.

Every betting day the pipeline re-runs the normal selector on a deep copy of
the same pre-start slate with the admin 'Ponuka' exclusions opened up (all
Value competitions, Value without the serve+return filter, TOP low-odds fill).
Each virtual pick is tagged with its category and whether the LIVE rules
would have published it. The first capture per day is frozen; results are
settled read-only from canonical completed matches. Nothing here touches the
public offer, Telegram, the CDB or provider quota.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import os
from typing import Any
from unittest.mock import patch

SCHEMA = 1
MIN_LEAD_SECONDS = 600
SECTIONS = {"top": "top_daily_picks", "value": "value_picks"}
ALL_LEVELS = "ATP,WTA,Challenger,WTA 125,ITF-M,ITF-W"
VARIANTS: dict[str, dict[str, str]] = {
    # Value in every competition, live serve+return rule kept.
    "value_all_levels": {"TBT_VALUE_LEVELS": ALL_LEVELS},
    # Value in every competition without the serve+return filter.
    "value_all_no_sr": {"TBT_VALUE_LEVELS": ALL_LEVELS, "TBT_VALUE_SERVE_RETURN": "false"},
    # TOP always topped up from 1.40 (live only fills when short).
    "top_low_odds": {"TBT_TOP_LOW_ODDS_FLOOR": "1.40", "TBT_TOP_MIN_PICKS": "10"},
}
VARIANT_LABELS = {
    "value_all_levels": "Value · všetky súťaže",
    "value_all_no_sr": "Value · bez podania+príjmu",
    "top_low_odds": "TOP · kurz od 1,40",
}


def _ts(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def category(card: dict[str, Any]) -> str:
    from .top_policy import competition_group
    group = competition_group(card)
    if group == "ITF":
        return "ITF-M" if str(card.get("tour") or "").upper() == "ATP" else "ITF-W"
    return str(group or "unknown")


def build_offer_shadow(predictions, *, observed_at, public_offer_day):
    from .market_selection import (select_market_sections, value_level_ok,
                                   _belongs_to_public_offer_day)
    clock = _ts(observed_at)
    if clock is None or not public_offer_day:
        raise ValueError("Offer shadow needs aware clock and betting day")
    prepared, by_event = [], {}
    for source in predictions or []:
        if not isinstance(source, dict) or source.get("prediction_family") == "doubles":
            continue
        if not _belongs_to_public_offer_day(source, public_offer_day):
            continue
        start = _ts(source.get("scheduled_at"))
        if start is None or (start - clock).total_seconds() <= MIN_LEAD_SECONDS:
            continue
        event = str(source.get("event_id") or "")
        p1 = str((source.get("player1") or {}).get("id") or "")
        p2 = str((source.get("player2") or {}).get("id") or "")
        if not event or not p1 or not p2 or p1 == p2 or event in by_event:
            continue
        copied = deepcopy(source)
        by_event[event] = copied
        prepared.append(copied)
    if not prepared:
        return None
    # Live picks (current env) so virtual rows can be marked as published.
    live = select_market_sections(deepcopy(prepared), public_offer_day=public_offer_day)
    live_keys = {(s, str(c.get("event_id")), str((c.get("betting") or {}).get("selection_id")))
                 for s, k in SECTIONS.items() for c in live.get(k, [])}
    variants = {}
    for name, env in VARIANTS.items():
        with patch.dict(os.environ, env):
            result = select_market_sections(deepcopy(prepared), public_offer_day=public_offer_day)
        rows = []
        for section, key in SECTIONS.items():
            if name.startswith("value") and section != "value":
                continue
            if name.startswith("top") and section != "top":
                continue
            for card in result.get(key, []):
                event = str(card.get("event_id") or "")
                source = by_event.get(event)
                betting = card.get("betting") or {}
                selection = str(betting.get("selection_id") or "")
                if source is None:
                    continue
                if name == "top_low_odds" and card.get("selection_tier") != "low_odds_fill":
                    continue
                p1 = str(source["player1"]["id"])
                p2 = str(source["player2"]["id"])
                if selection not in (p1, p2):
                    continue
                published = (section, event, selection) in live_keys
                rows.append({
                    "section": section, "category": category(card),
                    "event_id": event, "match_id": str(source.get("id") or ""),
                    "selected_player_id": selection, "player1_id": p1, "player2_id": p2,
                    "scheduled_at": str(source.get("scheduled_at")),
                    "odds": _num(betting.get("odds")),
                    "probability": _num(card.get("probability")),
                    "tier": card.get("selection_tier"),
                    "live_level_ok": bool(value_level_ok(card)),
                    "published": published,
                })
        variants[name] = rows
    capture = {"schema": SCHEMA, "public_offer_day": public_offer_day,
               "captured_at": clock.isoformat(), "variants": variants}
    capture["sha256"] = _digest(capture)
    return capture


def _digest(capture):
    payload = {k: v for k, v in capture.items() if k != "sha256"}
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode()).hexdigest()


def first_day_capture(history, *, public_offer_day):
    for snap in (history or {}).get("snapshots") or []:
        cap = snap.get("offer_shadow")
        if isinstance(cap, dict) and cap.get("public_offer_day") == public_offer_day:
            return cap
    return None


def _blank():
    return {"issued": 0, "settled": 0, "correct": 0, "staked": 0, "returned": 0.0,
            "odds_sum": 0.0}


def settle_month(history, matches, *, asof) -> dict:
    """Aggregate per variant -> category, ONLY rows not published live."""
    clock = _ts(asof)
    by_match = {}
    for m in matches or []:
        if getattr(m, "is_completed", False):
            mid = str(getattr(m, "match_id", "") or "")
            if mid:
                by_match[mid] = m
    out: dict[str, dict[str, dict]] = {v: {} for v in VARIANTS}
    days = set()
    for snap in (history or {}).get("snapshots") or []:
        cap = snap.get("offer_shadow")
        if not isinstance(cap, dict) or cap.get("schema") != SCHEMA:
            continue
        if cap.get("sha256") != _digest(cap) or cap["public_offer_day"] in days:
            continue
        days.add(cap["public_offer_day"])
        for variant, rows in (cap.get("variants") or {}).items():
            if variant not in out:
                continue
            for row in rows:
                if row.get("published"):
                    continue  # already measured as a live pick
                dest = out[variant].setdefault(row.get("category") or "unknown", _blank())
                dest["issued"] += 1
                match = by_match.get(row.get("match_id"))
                start = _ts(row.get("scheduled_at"))
                if (match is None or start is None or clock is None or clock <= start
                        or {str(match.player1_id), str(match.player2_id)}
                        != {row["player1_id"], row["player2_id"]}
                        or str(match.winner_id) not in (row["player1_id"], row["player2_id"])):
                    continue
                dest["settled"] += 1
                odds = row.get("odds")
                priced = isinstance(odds, (int, float)) and odds > 1
                if priced:
                    dest["staked"] += 1
                    dest["odds_sum"] += odds
                if str(match.winner_id) == row["selected_player_id"]:
                    dest["correct"] += 1
                    if priced:
                        dest["returned"] += odds
    for cats in out.values():
        for d in cats.values():
            d["returned"] = round(d["returned"], 4)
            d["odds_sum"] = round(d["odds_sum"], 4)
    return {"schema": SCHEMA, "days": len(days), "variants": out}


def summarize(months: dict[str, dict]) -> dict:
    """Combine stored month aggregates into the admin view."""
    total: dict[str, dict[str, dict]] = {}
    for month in sorted(months):
        for variant, cats in (months[month].get("variants") or {}).items():
            for cat, d in cats.items():
                t = total.setdefault(variant, {}).setdefault(cat, _blank())
                for k in t:
                    t[k] += d.get(k, 0)
    rows = []
    for variant, cats in total.items():
        for cat, d in sorted(cats.items()):
            rows.append({
                "variant": variant, "label": VARIANT_LABELS.get(variant, variant),
                "category": cat, "issued": d["issued"], "settled": d["settled"],
                "correct": d["correct"],
                "hit_rate": d["correct"] / d["settled"] if d["settled"] else None,
                "avg_odds": d["odds_sum"] / d["staked"] if d["staked"] else None,
                "roi": (d["returned"] / d["staked"] - 1.0) if d["staked"] else None,
                "profit_units": round(d["returned"] - d["staked"], 2),
            })
    return {"rows": rows, "months": sorted(months),
            "days": sum(int(m.get("days") or 0) for m in months.values())}


PARTITION = "offer-shadow-v1"


def save_month(month: str, report: dict) -> None:
    from .admin_storage import _table, UI_TABLE, AdminStorageUnavailable
    if not (isinstance(month, str) and len(month) == 7 and month[4] == "-"):
        raise ValueError("invalid_month")
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise ValueError("invalid_report")
    body = json.dumps(report, separators=(",", ":"))
    if len(body) > 30_000:
        raise ValueError("report_too_large")
    try:
        _table(UI_TABLE).upsert_entity({"PartitionKey": PARTITION, "RowKey": month,
                                        "payload": body}, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save offer shadow") from exc


def load_months() -> dict[str, dict]:
    from .admin_storage import _table, UI_TABLE, AdminStorageUnavailable
    try:
        return {str(e["RowKey"]): json.loads(e["payload"])
                for e in _table(UI_TABLE).query_entities(f"PartitionKey eq '{PARTITION}'")}
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to read offer shadow") from exc
