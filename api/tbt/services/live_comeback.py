"""Conservative BlinQ Comeback LIVE Radar.

PRIME remains an internal candidate pool.  After an eligible favourite loses
set 1, the radar exposes a WATCH state and can attach a historical conditional
Set-2 probability plus a real provider Set-2 Winner price when that market is
available.  CONFIRMED still requires an on-court second-set confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
import math
import os
import re
from typing import Any

from .admin_storage import (
    save_automated_insight, live_alert_levels, load_insight_by_id,
    save_live_radar_result,
)
from .market_selection import _walk_market_rows, _outcome_text, _price, _match_side

DEFAULT_MIN_PROBABILITY = .68
DEFAULT_MAX_ODDS = 1.49


def _num(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _int(v):
    n = _num(v)
    return int(round(n)) if n is not None and abs(n - round(n)) < 1e-9 else None


def radar_thresholds():
    def ev(name, default):
        n = _num(os.getenv(name))
        return float(n) if n is not None else default
    return {
        "min_probability": min(.99, max(.5, ev("BLINQ_LIVE_RADAR_MIN_PROBABILITY", DEFAULT_MIN_PROBABILITY))),
        "max_odds": min(1.49, max(1.01, ev("BLINQ_LIVE_RADAR_MAX_ODDS", DEFAULT_MAX_ODDS))),
    }




def set2_push_thresholds():
    def ev(name, default):
        n = _num(os.getenv(name))
        return float(n) if n is not None else default
    return {
        "min_samples": max(1, int(ev("BLINQ_LIVE_SET2_MIN_SAMPLES", 10))),
        "min_edge": max(0.0, ev("BLINQ_LIVE_SET2_MIN_EDGE", 0.0)),
        "min_ev": max(0.0, ev("BLINQ_LIVE_SET2_MIN_EV", 0.0)),
        "accepted_quality": {"medium", "high"},
    }


def set2_push_eligible(row: dict[str, Any]) -> bool:
    """True only for evidence-backed Set-2 value with a real live market."""
    if not isinstance(row, dict):
        return False
    th = set2_push_thresholds()
    quality = str(row.get("second_set_quality") or "").strip().lower()
    samples = int(_num(row.get("second_set_samples")) or 0)
    probability = _num(row.get("second_set_probability"))
    odds = _num(row.get("second_set_odds"))
    edge = _num(row.get("second_set_edge"))
    ev = _num(row.get("second_set_ev"))
    return bool(
        quality in th["accepted_quality"]
        and samples >= th["min_samples"]
        and probability is not None
        and odds is not None and odds > 1.0
        and edge is not None and edge > th["min_edge"]
        and ev is not None and ev > th["min_ev"]
    )

def _selection(row):
    b = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    return str(b.get("selection_id") or row.get("winner_id") or "").strip(), str(b.get("selection") or row.get("pick") or "").strip()


def _probability(row):
    b = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    for v in (b.get("blinq_probability"), row.get("blinq_probability"), b.get("model_probability"), row.get("raw_model_probability"), row.get("confidence"), row.get("probability")):
        n = _num(v)
        if n is not None:
            return n / 100 if n > 1 else n
    vals = []
    for k in ("player1", "player2"):
        p = row.get(k) if isinstance(row.get(k), dict) else {}
        n = _num(p.get("probability"))
        if n is not None:
            vals.append(n / 100 if n > 1 else n)
    return max(vals, default=0.)


def _second_set_projection(row: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    payload = row.get("live_second_set_projection") if isinstance(row.get("live_second_set_projection"), dict) else {}
    p = _num(payload.get("probability"))
    if p is not None and p > 1:
        p /= 100.0
    if p is None or not 0.0 <= p <= 1.0:
        return None, payload
    return p, payload


def _odds(row):
    b = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    for v in (b.get("odds"), row.get("odds")):
        n = _num(v)
        if n is not None and n > 1:
            return n
    return None


def prime_radar_eligible(row: dict) -> bool:
    """Cheap prefilter used before any live-provider request."""
    th = radar_thresholds()
    p = _probability(row)
    odds = _odds(row)
    return bool(p + 1e-12 >= th["min_probability"] and odds is not None and odds <= th["max_odds"] + 1e-12)


def _event_id(e):
    return str(e.get("id") or e.get("eventId") or e.get("event_id") or "").strip()


def _team(e, k):
    return e.get(k) if isinstance(e.get(k), dict) else {}


def _score(e, k):
    return e.get(k) if isinstance(e.get(k), dict) else {}


def _set_score(e, p):
    return _int(_score(e, "homeScore").get(f"period{p}")), _int(_score(e, "awayScore").get(f"period{p}"))


def _winner(pair):
    h, a = pair
    if h is None or a is None or h == a:
        return ""
    hi, lo = max(h, a), min(h, a)
    complete = (hi == 6 and lo <= 4) or (hi == 7 and lo in {5, 6})
    if not complete:
        return ""
    return "home" if h > a else "away"


def _side_pair(pair, side):
    h, a = pair
    return (h, a) if side == "home" else (a, h)


def _favorite_side(e, row):
    hid, aid = str(_team(e, "homeTeam").get("id") or ""), str(_team(e, "awayTeam").get("id") or "")
    sid, sname = _selection(row)
    if sid and sid == hid:
        return "home"
    if sid and sid == aid:
        return "away"
    sn = " ".join(sname.casefold().split())
    hn = " ".join(str(_team(e, "homeTeam").get("name") or "").casefold().split())
    an = " ".join(str(_team(e, "awayTeam").get("name") or "").casefold().split())
    if sn and sn == hn:
        return "home"
    if sn and sn == an:
        return "away"
    return ""


def _name(e, side):
    return str(_team(e, "homeTeam" if side == "home" else "awayTeam").get("name") or "").strip()


def _opp(e, side):
    return str(_team(e, "awayTeam" if side == "home" else "homeTeam").get("name") or "").strip()


@dataclass
class RadarCandidate:
    event_id: str
    favorite: str
    opponent: str
    probability: float
    odds: float | None
    first_set: str
    second_set: str
    stage: str
    trigger: bool
    reason: str
    tournament: str = ""
    favorite_side: str = ""
    second_set_probability: float | None = None
    second_set_model: str = ""
    second_set_quality: str = ""
    second_set_samples: int = 0
    second_set_odds: float | None = None
    second_set_fair_probability: float | None = None
    second_set_edge: float | None = None
    second_set_ev: float | None = None
    second_set_market: str = ""

    def public(self):
        return asdict(self)


def evaluate_prime_live(row, event, *, min_probability, max_odds):
    p = _probability(row)
    odds = _odds(row)
    if p + 1e-12 < min_probability or odds is None or odds > max_odds + 1e-12:
        return None
    side = _favorite_side(event, row)
    if not side:
        return None
    first = _set_score(event, 1)
    fw = _winner(first)
    if not fw or fw == side:
        return None
    second = _set_score(event, 2)
    fav2, opp2 = _side_pair(second, side)
    sw = _winner(second)
    trigger = False
    stage = "watch"
    reason = "favorite_lost_first_set"
    if sw == side:
        trigger = True
        stage = "second_set_won"
        reason = "favorite_won_second_set"
    elif fav2 is not None and opp2 is not None and fav2 >= 3 and fav2 - opp2 >= 2:
        trigger = True
        stage = "break_lead"
        reason = "favorite_has_break_lead_in_second_set"
    ff, fo = _side_pair(first, side)
    t = event.get("tournament") if isinstance(event.get("tournament"), dict) else {}
    set2_p, set2_meta = _second_set_projection(row)
    samples = int(set2_meta.get("favorite_samples") or 0) + int(set2_meta.get("opponent_closeout_samples") or 0)
    return RadarCandidate(
        _event_id(event) or str(row.get("event_id") or ""),
        _name(event, side),
        _opp(event, side),
        p,
        odds,
        "—" if ff is None or fo is None else f"{ff}:{fo}",
        "—" if fav2 is None or opp2 is None else f"{fav2}:{opp2}",
        stage,
        trigger,
        reason,
        str(t.get("name") or row.get("tournament") or "").strip(),
        side,
        set2_p,
        str(set2_meta.get("model") or ""),
        str(set2_meta.get("quality") or ""),
        samples,
    )


def scan_comeback_radar(feed, live_events):
    th = radar_thresholds()
    prime = feed.get("prime_picks") if isinstance(feed.get("prime_picks"), list) else []
    live = {_event_id(e): e for e in live_events if isinstance(e, dict) and _event_id(e)}
    eligible_prime = []
    rejected_probability = 0
    rejected_odds = 0
    rejected_missing_odds = 0
    for row in prime:
        if not isinstance(row, dict):
            continue
        probability = _probability(row)
        odds = _odds(row)
        if probability + 1e-12 < th["min_probability"]:
            rejected_probability += 1
            continue
        if odds is None:
            rejected_missing_odds += 1
            continue
        if odds > th["max_odds"] + 1e-12:
            rejected_odds += 1
            continue
        eligible_prime.append(row)
    candidates = []
    for row in prime:
        if not isinstance(row, dict):
            continue
        e = live.get(str(row.get("event_id") or "").strip())
        if not e:
            continue
        status = e.get("status") if isinstance(e.get("status"), dict) else {}
        st = str(status.get("type") or status.get("description") or e.get("status") or "").lower()
        if st in {"finished", "ended", "canceled", "cancelled", "postponed"}:
            continue
        c = evaluate_prime_live(row, e, **th)
        if c:
            candidates.append(c)
    signals = [c for c in candidates if c.trigger]
    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "live_events": len(live_events),
        "prime_pool": len(prime),
        "eligible_prime_pool": len(eligible_prime),
        "rejected_prime": {
            "probability": rejected_probability,
            "odds": rejected_odds,
            "missing_odds": rejected_missing_odds,
        },
        "candidates": [c.public() for c in candidates],
        "signals": [c.public() for c in signals],
        "thresholds": th,
    }


def _normal_market(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).split())


def _is_second_set_winner_market(name: str) -> bool:
    text = _normal_market(name)
    compact = text.replace(" ", "")
    exact = {
        "set 2 winner", "2nd set winner", "second set winner", "winner set 2",
        "set2 winner", "winner 2nd set", "winner second set",
    }
    return text in exact or compact in {x.replace(" ", "") for x in exact} or (
        "winner" in text and ("set 2" in text or "2nd set" in text or "second set" in text)
    )


def extract_second_set_winner_odds(payload: Any, event: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a real two-way Set 2 Winner market; return None if ambiguous."""
    home = str(_team(event, "homeTeam").get("name") or "").strip()
    away = str(_team(event, "awayTeam").get("name") or "").strip()
    prices: dict[int, float] = {}
    market_used = ""
    for row, market_name in _walk_market_rows(payload):
        if not _is_second_set_winner_market(market_name):
            continue
        price = _price(row)
        if price is None:
            continue
        side = _match_side(_outcome_text(row), home, away)
        if side is None:
            selector = row.get("choiceCode") or row.get("outcomeCode") or row.get("type")
            side = _match_side(str(selector or ""), home, away)
        if side is None:
            continue
        prices.setdefault(side, price)
        market_used = market_used or str(market_name or "")
    if 1 not in prices or 2 not in prices:
        return None
    raw1, raw2 = 1.0 / prices[1], 1.0 / prices[2]
    total = raw1 + raw2
    if not math.isfinite(total) or total <= 0:
        return None
    return {
        "market": market_used,
        "home_odds": prices[1],
        "away_odds": prices[2],
        "home_fair_probability": raw1 / total,
        "away_fair_probability": raw2 / total,
        "raw_overround": total - 1.0,
    }


def attach_second_set_odds(scan: dict[str, Any], odds_payloads: dict[str, Any], live_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach provider Set-2 odds and value diagnostics without inventing prices."""
    events = {_event_id(e): e for e in live_events if isinstance(e, dict) and _event_id(e)}
    enriched_by_id: dict[str, dict[str, Any]] = {}
    candidates = []
    for source in scan.get("candidates", []):
        if not isinstance(source, dict):
            continue
        row = dict(source)
        eid = str(row.get("event_id") or "")
        market = extract_second_set_winner_odds(odds_payloads.get(eid), events.get(eid, {})) if eid in odds_payloads and eid in events else None
        if market:
            side = str(row.get("favorite_side") or "")
            fav_odds = market["home_odds"] if side == "home" else market["away_odds"] if side == "away" else None
            fair = market["home_fair_probability"] if side == "home" else market["away_fair_probability"] if side == "away" else None
            model_p = _num(row.get("second_set_probability"))
            row["second_set_odds"] = fav_odds
            row["second_set_fair_probability"] = fair
            row["second_set_market"] = market.get("market") or ""
            if fav_odds is not None and model_p is not None:
                row["second_set_edge"] = model_p - fair if fair is not None else None
                row["second_set_ev"] = model_p * fav_odds - 1.0
        enriched_by_id[eid] = row
        candidates.append(row)
    result = dict(scan)
    result["candidates"] = candidates
    result["signals"] = [dict(enriched_by_id.get(str(row.get("event_id") or ""), row)) for row in scan.get("signals", []) if isinstance(row, dict)]
    return result


def _live_active_until(scan: dict[str, Any], minutes: int) -> str:
    raw = str((scan or {}).get("scanned_at") or "").strip()
    try:
        base = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else datetime.now(timezone.utc)
    except ValueError:
        base = datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return (base.astimezone(timezone.utc) + timedelta(minutes=max(5, int(minutes)))).isoformat()


def publish_radar_signals(scan, *, actor_id="live-radar"):
    """Publish comeback alerts plus a separate high-quality Set-2 signal."""
    published = []
    set2_until = _live_active_until(scan, 20)
    watch_until = _live_active_until(scan, 20)
    confirmed_until = _live_active_until(scan, 30)
    # SET 2 is a distinct signal. It gets a durable LIVE item (and therefore a
    # browser push) only when evidence depth is sufficient, a real provider
    # price exists and both edge and EV are positive. Otherwise it stays panel-only.
    for s in scan.get("candidates", []):
        if not isinstance(s, dict) or not set2_push_eligible(s):
            continue
        eid = str(s.get("event_id") or "").strip()
        if not eid:
            continue
        fav = str(s.get("favorite") or "Favorit")
        opp = str(s.get("opponent") or "")
        p2 = _num(s.get("second_set_probability")) or 0.0
        odds2 = _num(s.get("second_set_odds"))
        edge2 = _num(s.get("second_set_edge"))
        ev2 = _num(s.get("second_set_ev"))
        samples = int(_num(s.get("second_set_samples")) or 0)
        quality = str(s.get("second_set_quality") or "").upper()
        body = f"{fav} · samostatný model 2. setu: {p2*100:.1f}%"
        if opp:
            body += f" proti {opp}"
        body += f". LIVE kurz {odds2:.2f}, edge {edge2*100:+.1f} p.b., EV {ev2*100:+.1f}%. Data depth: {quality} · {samples} vzoriek."
        item, created = save_automated_insight({
            "title": f"2. set LIVE · {fav}", "body": body, "type": "set2",
            "priority": "important", "levels": live_alert_levels(), "match_id": eid,
            "link_label": "Otvoriť LIVE Radar", "active": True, "pinned": False,
            "active_until": set2_until,
        }, actor_id=actor_id, insight_id=f"live-set2-{eid}"[:96])
        published.append({"id": item.get("id"), "event_id": eid, "stage": "set2", "created": created})
    signal_ids = {str(x.get("event_id") or "").strip() for x in scan.get("signals", []) if isinstance(x, dict)}
    for s in scan.get("candidates", []):
        if not isinstance(s, dict):
            continue
        eid = str(s.get("event_id") or "").strip()
        if not eid or eid in signal_ids:
            continue
        fav = str(s.get("favorite") or "Favorit")
        opp = str(s.get("opponent") or "")
        p = _num(s.get("probability")) or 0
        odds = _num(s.get("odds"))
        fs = str(s.get("first_set") or "—")
        ss = str(s.get("second_set") or "—")
        set2_p = _num(s.get("second_set_probability"))
        set2_odds = _num(s.get("second_set_odds"))
        set2_edge = _num(s.get("second_set_edge"))
        set2_ev = _num(s.get("second_set_ev"))
        body = f"{fav} prehral 1. set ({fs}) a BlinQ ho zaradil do WATCH comeback režimu."
        if ss != "—":
            body += f" Druhý set: {ss}."
        if opp:
            body += f" Súper: {opp}."
        body += f" Predzápasová pravdepodobnosť {p*100:.1f}%" + (f", pôvodný kurz {odds:.2f}." if odds is not None else ".")
        if set2_p is not None:
            body += f" Historický conditional odhad výhry 2. setu: {set2_p*100:.1f}%."
        if set2_odds is not None:
            body += f" LIVE Set 2 kurz {set2_odds:.2f}."
            if set2_edge is not None and set2_ev is not None:
                body += f" Edge {set2_edge*100:+.1f} p.b., EV {set2_ev*100:+.1f}%."
        body += " Toto ešte nie je potvrdený comeback signál."
        item, created = save_automated_insight({
            "title": f"Potential Comeback · {fav}", "body": body, "type": "live_watch",
            "priority": "normal", "levels": live_alert_levels(), "match_id": eid,
            "link_label": "Sledovať zápas", "active": True, "pinned": False,
            "active_until": watch_until,
        }, actor_id=actor_id, insight_id=f"live-watch-{eid}"[:96])
        published.append({"id": item.get("id"), "event_id": eid, "stage": "watch", "created": created})
    for s in scan.get("signals", []):
        eid = str(s.get("event_id") or "").strip()
        if not eid:
            continue
        fav = str(s.get("favorite") or "Favorit")
        opp = str(s.get("opponent") or "")
        p = _num(s.get("probability")) or 0
        odds = _num(s.get("odds"))
        stage = str(s.get("stage") or "")
        ss = str(s.get("second_set") or "—")
        body = (f"{fav} prehral 1. set, ale vyrovnal zápas na sety. BlinQ comeback profil zostáva silný." if stage == "second_set_won" else f"{fav} prehral 1. set a v 2. sete má break náskok ({ss}). BlinQ comeback podmienky sú splnené.")
        if opp:
            body += f" Súper: {opp}."
        body += f" Predzápasová pravdepodobnosť {p*100:.1f}%" + (f", pôvodný kurz {odds:.2f}." if odds is not None else ".")
        item, created = save_automated_insight({
            "title": f"Comeback LIVE · {fav}", "body": body, "type": "alert",
            "priority": "important", "levels": live_alert_levels(), "match_id": eid,
            "link_label": "Otvoriť zápas", "active": True, "pinned": False,
            "active_until": confirmed_until,
        }, actor_id=actor_id, insight_id=f"live-comeback-{eid}"[:96])
        published.append({"id": item.get("id"), "event_id": eid, "stage": "confirmed", "created": created})
    return {
        "published": published,
        "created": sum(1 for x in published if x["created"]),
        "watch_created": sum(1 for x in published if x["created"] and x["stage"] == "watch"),
        "confirmed_created": sum(1 for x in published if x["created"] and x["stage"] == "confirmed"),
        "set2_created": sum(1 for x in published if x["created"] and x["stage"] == "set2"),
        "set2_push_thresholds": {k: (sorted(v) if isinstance(v, set) else v) for k, v in set2_push_thresholds().items()},
    }


def settle_radar_results(settled_events: list[dict[str, Any]]) -> dict[str, int]:
    """Settle only LIVE signals that were actually published/confirmed.

    WATCH-only candidates never enter history. Comeback is settled by the final
    match result; the independent Set-2 signal is settled by the completed
    second-set score.
    """
    saved = comeback = set2 = 0
    for row in settled_events or []:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("event_id") or "").strip()
        if not eid:
            continue
        settled_at = str(row.get("checked_at") or datetime.now(timezone.utc).isoformat())

        comeback_source = load_insight_by_id(f"live-comeback-{eid}"[:96])
        match_status = str(row.get("match_status") or "").lower()
        if comeback_source and match_status in {"win", "loss", "retired", "void"}:
            outcome = match_status if match_status in {"win", "loss"} else "void"
            save_live_radar_result({
                "kind": "comeback", "outcome": outcome, "event_id": eid,
                "reason": "retired" if match_status == "retired" else "",
                "title": comeback_source.get("title") or "Comeback LIVE",
                "source_id": comeback_source.get("id") or f"live-comeback-{eid}",
                "signal_at": comeback_source.get("created_at") or "",
                "settled_at": settled_at,
            }, result_id=f"live-result-comeback-{eid}"[:96])
            saved += 1
            comeback += 1

        set2_source = load_insight_by_id(f"live-set2-{eid}"[:96])
        second_status = str(row.get("second_set_status") or "").lower()
        if set2_source and second_status in {"win", "loss"}:
            save_live_radar_result({
                "kind": "set2", "outcome": second_status, "event_id": eid,
                "title": set2_source.get("title") or "2. set LIVE",
                "source_id": set2_source.get("id") or f"live-set2-{eid}",
                "signal_at": set2_source.get("created_at") or "",
                "settled_at": settled_at,
            }, result_id=f"live-result-set2-{eid}"[:96])
            saved += 1
            set2 += 1
    return {"saved": saved, "comeback": comeback, "set2": set2}
