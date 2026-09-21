"""Fail-closed Slovak bookmaker availability annotation.

This layer is presentation-only. It never changes BlinQ selection, probability,
model odds, edge or EV. A bookmaker badge is attached only when an external
snapshot identifies the same event, market and selection (including the exact
line when a line exists).
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


SK_BOOKMAKERS: dict[str, dict[str, Any]] = {
    "tipsport": {
        "label": "Tipsport",
        "short": "T",
        "aliases": ("tipsport", "tipsport.sk", "tipsport sk"),
    },
    "nike": {
        "label": "Niké",
        "short": "N",
        "aliases": ("nike", "niké", "nike.sk", "niké.sk"),
    },
    "fortuna": {
        "label": "Fortuna",
        "short": "F",
        "aliases": ("fortuna", "fortuna.sk", "ifortuna", "ifortuna.sk"),
    },
    "doxxbet": {
        "label": "DOXXbet",
        "short": "D",
        "aliases": ("doxxbet", "doxxbet.sk", "doxx bet"),
    },
    "synottip": {
        "label": "SYNOT TIP",
        "short": "S",
        "aliases": ("synottip", "synot tip", "synottip.sk", "synot-tip"),
    },
    "tipos": {
        "label": "TIPOS",
        "short": "TP",
        "aliases": ("tipos", "tiposbet", "etipos", "etipos.sk", "tipos.sk"),
    },
    "chance": {
        "label": "Chance",
        "short": "C",
        "aliases": ("chance", "chance.sk", "chance sk"),
    },
}


def _text(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()


def canonical_bookmaker(value: Any) -> str:
    normalized = _text(value)
    compact = normalized.replace(" ", "")
    if not normalized:
        return ""
    for key, meta in SK_BOOKMAKERS.items():
        for alias in meta["aliases"]:
            a = _text(alias)
            if normalized == a or compact == a.replace(" ", ""):
                return key
    return ""


def _number(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _market(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if any(token in text for token in ("double fault", "doublefault", "dvojchyb")):
        return "double_faults"
    if "ace" in text or "esa" in text:
        return "aces"
    if "set" in text:
        return "sets"
    if any(token in text for token in ("game", "gem", "total games")):
        return "games"
    if any(token in text for token in ("match winner", "moneyline", "winner", "home away", "1 2")):
        return "match_winner"
    return text.replace(" ", "_")


def _side(value: Any) -> str:
    text = _text(value)
    if re.search(r"\b(over|o|nad|viac)\b", text):
        return "over"
    if re.search(r"\b(under|u|pod|menej)\b", text):
        return "under"
    return ""


def _line(value: Any) -> float | None:
    direct = _number(value)
    if direct is not None:
        return direct
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)", str(value or ""))
    return _number(match.group(1)) if match else None


def _row_market(row: dict[str, Any]) -> str:
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    raw = row.get("market") or row.get("projection_metric") or betting.get("market")
    return _market(raw or "match_winner")


def _row_selection(row: dict[str, Any]) -> str:
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    return str(row.get("selection") or row.get("pick") or betting.get("selection") or "").strip()


def _row_line(row: dict[str, Any]) -> float | None:
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    for candidate in (
        row.get("market_line"), row.get("line"), row.get("threshold"),
        betting.get("market_line"), betting.get("line"), _row_selection(row),
    ):
        parsed = _line(candidate)
        if parsed is not None:
            return parsed
    return None


def _row_players(row: dict[str, Any]) -> tuple[str, str]:
    p1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
    p2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
    return str(p1.get("name") or row.get("player1_name") or ""), str(p2.get("name") or row.get("player2_name") or "")


def _offer_players(offer: dict[str, Any]) -> tuple[str, str]:
    p1 = offer.get("player1") or offer.get("home") or offer.get("home_name") or offer.get("first_player")
    p2 = offer.get("player2") or offer.get("away") or offer.get("away_name") or offer.get("second_player")
    if isinstance(p1, dict):
        p1 = p1.get("name")
    if isinstance(p2, dict):
        p2 = p2.get("name")
    return str(p1 or ""), str(p2 or "")


def _same_event(row: dict[str, Any], offer: dict[str, Any], *, time_tolerance_seconds: int) -> bool:
    row_event = str(row.get("event_id") or "").strip()
    offer_event = str(offer.get("event_id") or offer.get("provider_event_id") or "").strip()
    if row_event and offer_event and row_event == offer_event:
        return True

    r1, r2 = map(_text, _row_players(row))
    o1, o2 = map(_text, _offer_players(offer))
    if not r1 or not r2 or not o1 or not o2:
        return False
    if {r1, r2} != {o1, o2}:
        return False
    row_at = _timestamp(row.get("scheduled_at") or row.get("date"))
    offer_at = _timestamp(offer.get("scheduled_at") or offer.get("start_at") or offer.get("date"))
    if row_at is None or offer_at is None:
        return False
    return abs((row_at - offer_at).total_seconds()) <= max(60, int(time_tolerance_seconds))


def _same_selection(row: dict[str, Any], offer: dict[str, Any]) -> bool:
    market = _row_market(row)
    target = _row_selection(row)
    offered = str(offer.get("selection") or offer.get("pick") or offer.get("outcome") or offer.get("side") or "").strip()
    target_side, offer_side = _side(target), _side(offered)
    target_line, offer_line = _row_line(row), _line(offer.get("line") if offer.get("line") is not None else offered)

    if market in {"games", "sets"}:
        if target_side and offer_side and target_side != offer_side:
            return False
        if target_line is None or offer_line is None:
            return False
        return abs(target_line - offer_line) <= 0.051

    if market in {"aces", "double_faults"}:
        # These are player props. Exact line alone is not enough: an offer such
        # as "Over 3.5" must also identify the same player as the BlinQ row.
        # This prevents Player A's prop from being shown on Player B's pick.
        target_subject = _text(
            row.get("projection_subject")
            or row.get("player")
            or target.split("·", 1)[0]
        )
        offered_subject_raw = (
            offer.get("player")
            or offer.get("participant")
            or offer.get("subject")
            or (offered.split("·", 1)[0] if "·" in offered else "")
        )
        offered_subject = _text(offered_subject_raw)

        if target_line is not None or offer_line is not None:
            if not target_side or not offer_side or target_side != offer_side:
                return False
            if target_line is None or offer_line is None or abs(target_line - offer_line) > 0.051:
                return False
            if target_subject and (not offered_subject or target_subject != offered_subject):
                return False
            return True

        # Superiority/no-line markets require an explicit same-player outcome.
        if not target or not offered:
            return False
        if target_subject and offered_subject:
            return target_subject == offered_subject
        return _text(target) == _text(offered)

    if market == "match_winner":
        if not target or not offered:
            return False
        return _text(target) == _text(offered)

    return False


def _offer_is_fresh(offer: dict[str, Any], snapshot_generated_at: datetime | None, now: datetime, max_age_minutes: int) -> bool:
    if offer.get("available") is False or offer.get("active") is False or offer.get("suspended") is True:
        return False
    stamp = _timestamp(offer.get("captured_at") or offer.get("verified_at") or offer.get("updated_at")) or snapshot_generated_at
    if stamp is None:
        return False
    return (now - stamp).total_seconds() <= max(60, int(max_age_minutes) * 60)


def _safe_offer_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return raw


def normalize_snapshot(payload: Any) -> tuple[list[dict[str, Any]], datetime | None]:
    if isinstance(payload, list):
        rows = payload
        generated = None
    elif isinstance(payload, dict):
        rows = payload.get("offers") or payload.get("bookmaker_offers") or payload.get("data") or []
        generated = _timestamp(payload.get("generated_at") or payload.get("captured_at") or payload.get("updated_at"))
    else:
        rows, generated = [], None
    if not isinstance(rows, list):
        return [], generated
    return [row for row in rows if isinstance(row, dict)], generated


def attach_bookmaker_availability(
    feed: dict[str, Any],
    offers: list[dict[str, Any]],
    *,
    snapshot_generated_at: datetime | None = None,
    now: datetime | None = None,
    max_age_minutes: int = 45,
    time_tolerance_seconds: int = 3 * 3600,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    result = deepcopy(feed)
    valid_offers: list[tuple[str, dict[str, Any]]] = []
    rejected = {"unknown_bookmaker": 0, "stale_or_inactive": 0, "invalid_market": 0}
    for offer in offers or []:
        book = canonical_bookmaker(offer.get("bookmaker") or offer.get("sportsbook") or offer.get("book") or offer.get("provider"))
        if not book:
            rejected["unknown_bookmaker"] += 1
            continue
        if not _offer_is_fresh(offer, snapshot_generated_at, now, max_age_minutes):
            rejected["stale_or_inactive"] += 1
            continue
        if _market(offer.get("market") or offer.get("market_name") or offer.get("bet_type")) not in {"match_winner", "games", "sets", "aces", "double_faults"}:
            rejected["invalid_market"] += 1
            continue
        valid_offers.append((book, offer))

    keys = ("top_daily_picks", "prime_picks", "value_picks", "doubles_picks", "ace_picks", "sg_picks", "upcoming")
    matched_rows = 0
    matched_by_book = {key: 0 for key in SK_BOOKMAKERS}
    matched_offers = 0
    for key in keys:
        rows = result.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_market = _row_market(row)
            matches: dict[str, dict[str, Any]] = {}
            for book, offer in valid_offers:
                if _market(offer.get("market") or offer.get("market_name") or offer.get("bet_type")) != row_market:
                    continue
                if not _same_event(row, offer, time_tolerance_seconds=time_tolerance_seconds):
                    continue
                if not _same_selection(row, offer):
                    continue
                odds = _number(offer.get("odds") or offer.get("price") or offer.get("decimal_odds"))
                if odds is not None and odds <= 1:
                    odds = None
                captured = _timestamp(offer.get("captured_at") or offer.get("verified_at") or offer.get("updated_at")) or snapshot_generated_at
                candidate = {
                    "bookmaker": book,
                    "label": SK_BOOKMAKERS[book]["label"],
                    "short": SK_BOOKMAKERS[book]["short"],
                    "odds": round(odds, 3) if odds is not None else None,
                    "line": _line(offer.get("line") if offer.get("line") is not None else offer.get("selection")),
                    "verified_at": captured.isoformat() if captured else None,
                    "expires_at": (captured + timedelta(minutes=max_age_minutes)).isoformat() if captured else None,
                    "url": _safe_offer_url(offer.get("url") or offer.get("deeplink") or offer.get("link")),
                }
                previous = matches.get(book)
                previous_stamp = _timestamp(previous.get("verified_at")) if previous else None
                if previous is None or (captured and (previous_stamp is None or captured > previous_stamp)):
                    matches[book] = candidate
            if matches:
                ordered = [matches[book] for book in SK_BOOKMAKERS if book in matches]
                row["bookmaker_availability"] = ordered
                matched_rows += 1
                matched_offers += len(ordered)
                for item in ordered:
                    matched_by_book[item["bookmaker"]] += 1
            else:
                row.pop("bookmaker_availability", None)

    return result, {
        "schema": 1,
        "policy": "exact_event_market_selection_fail_closed",
        "supported_bookmakers": list(SK_BOOKMAKERS),
        "valid_offers": len(valid_offers),
        "matched_rows": matched_rows,
        "matched_offers": matched_offers,
        "matched_by_bookmaker": matched_by_book,
        "rejected": rejected,
        "max_age_minutes": int(max_age_minutes),
        "time_tolerance_seconds": int(time_tolerance_seconds),
    }


def _read_url(url: str, token: str, timeout_seconds: int) -> Any:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("BLINQ_BOOKMAKER_FEED_URL must be a clean HTTPS URL")
    headers = {"Accept": "application/json", "User-Agent": "BlinQ-bookmaker-availability/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-API-Key"] = token
    request = Request(url, headers=headers)
    with urlopen(request, timeout=max(2, min(30, int(timeout_seconds)))) as response:
        raw = response.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("bookmaker feed exceeds 5 MB")
    return json.loads(raw.decode("utf-8"))


def load_bookmaker_snapshot(root: Path) -> tuple[list[dict[str, Any]], datetime | None, dict[str, Any]]:
    """Load an optional normalized bookmaker snapshot.

    Production integrations can either materialize a JSON file and set
    BLINQ_BOOKMAKER_OFFERS_FILE, or expose the same schema via HTTPS and set
    BLINQ_BOOKMAKER_FEED_URL. No source configured means zero badges, never
    guessed availability.
    """
    file_value = str(os.getenv("BLINQ_BOOKMAKER_OFFERS_FILE", "")).strip()
    url = str(os.getenv("BLINQ_BOOKMAKER_FEED_URL", "")).strip()
    token = str(os.getenv("BLINQ_BOOKMAKER_FEED_TOKEN", "")).strip()
    timeout = int(os.getenv("BLINQ_BOOKMAKER_FEED_TIMEOUT_SECONDS", "8") or 8)
    source = "none"
    try:
        if file_value:
            target = Path(file_value)
            if not target.is_absolute():
                target = root / target
            payload = json.loads(target.read_text(encoding="utf-8"))
            source = "file"
        elif url:
            payload = _read_url(url, token, timeout)
            source = "https"
        else:
            return [], None, {"enabled": False, "source": "none", "offers": 0, "error": None}
        offers, generated = normalize_snapshot(payload)
        return offers, generated, {"enabled": True, "source": source, "offers": len(offers), "error": None}
    except Exception as exc:  # optional integration: fail closed, do not block model publication
        return [], None, {"enabled": True, "source": source or "unknown", "offers": 0, "error": exc.__class__.__name__}
