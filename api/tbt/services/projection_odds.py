"""Strict provider odds attachment for projection cards.

Projection models and bookmaker markets are deliberately separate.  This module
never invents a price or a line and never changes a model projection in order to
make it fit a provider market.  It only attaches provider-1 decimal odds when an
exact, two-sided market can be identified unambiguously.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import re
from typing import Any

from tbt.services.market_selection import _walk_market_rows, _outcome_text, _price, _match_side
from tbt.providers.budget import RequestBudgetExceeded


def _normal(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().replace("_", " ").split())


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _explicit_line(row: dict[str, Any], outcome: str = "") -> float | None:
    for key in ("line", "handicap", "total", "points", "threshold", "specifier", "choiceGroup", "choice_group"):
        value = row.get(key)
        if isinstance(value, str):
            match = re.search(r"[-+]?\d+(?:[.,]\d+)?", value)
            value = match.group(0).replace(",", ".") if match else None
        number = _number(value)
        if number is not None:
            return number
    # Outcome labels frequently carry the line: "Over 20.5" / "Under (20.5)".
    match = re.search(r"\b(?:over|under)\b[^0-9+-]*([-+]?\d+(?:[.,]\d+)?)", outcome, re.I)
    if match:
        return _number(match.group(1).replace(",", "."))
    return None


def _over_under(outcome: str, row: dict[str, Any]) -> str:
    text = _normal(outcome)
    if re.search(r"\bover\b", text):
        return "over"
    if re.search(r"\bunder\b", text):
        return "under"
    for key in ("choiceCode", "choice_code", "outcomeCode", "outcome_code", "type"):
        code = _normal(row.get(key))
        if code in {"o", "over"}:
            return "over"
        if code in {"u", "under"}:
            return "under"
    return ""


def _is_match_total_market(name: str, metric: str) -> bool:
    text = _normal(name)
    # Player-specific totals are not interchangeable with match totals.
    if any(token in text for token in ("player 1", "player 2", "home", "away", "team 1", "team 2", "player total")):
        return False
    if metric == "games":
        aliases = (
            "total games", "games total", "total number of games", "number of games",
            "total games won", "match games", "games in match",
        )
        return any(token in text for token in aliases) and "set" not in text
    if metric == "sets":
        aliases = (
            "total sets", "sets total", "total number of sets", "number of sets",
            "sets in match", "match sets",
        )
        return any(token in text for token in aliases) and "set winner" not in text
    return False


def extract_match_total_odds(payload: Any, metric: str) -> list[dict[str, Any]]:
    """Return complete two-sided O/U match-total markets, one row per line."""
    metric = str(metric or "").strip().lower()
    markets: dict[float, dict[str, Any]] = {}
    for row, market_name in _walk_market_rows(payload):
        if not _is_match_total_market(market_name, metric):
            continue
        outcome = _outcome_text(row)
        side = _over_under(outcome, row)
        price = _price(row)
        line = _explicit_line(row, outcome)
        if not side or price is None or line is None:
            continue
        # Physically plausible lines prevent accidental parsing of source IDs.
        if metric == "sets" and not (1.5 <= line <= 5.5):
            continue
        if metric == "games" and not (8.0 <= line <= 80.0):
            continue
        bucket = markets.setdefault(float(line), {"line": float(line), "market_name": market_name})
        bucket.setdefault(side, float(price))
    return [row for _, row in sorted(markets.items()) if row.get("over") and row.get("under")]


def extract_player_superiority_odds(payload: Any, metric: str, player1: str, player2: str) -> dict[str, Any] | None:
    """Extract exact winner-style Most Aces / Most Double Faults odds.

    Player O/U totals are intentionally rejected: the current Ace/DF model predicts
    which player records more, not whether a player clears an arbitrary bookmaker line.
    Provider labels vary, so superiority aliases are intentionally broader while the
    two-player/two-price requirement remains strict.
    """
    metric = str(metric or "").strip().lower()
    prices: dict[int, float] = {}
    market_used = ""
    superiority_tokens = ("most", "winner", "more", "higher", "who", "to record more", "to serve more", "to make more")
    for row, market_name in _walk_market_rows(payload):
        text = _normal(market_name)
        if metric == "aces":
            exact = "ace" in text and any(token in text for token in superiority_tokens)
        elif metric == "double_faults":
            exact = ("double fault" in text or "doublefault" in text) and any(token in text for token in superiority_tokens)
        else:
            exact = False
        if not exact or any(token in text for token in ("total", "over", "under", "handicap")):
            continue
        # First-set and match prices describe different bets. A match-wide
        # projection must not silently acquire a partial-match price.
        if re.search(r"\bset\b|\bsets\b|\bperiod\b|\btie.?break\b", text):
            continue
        price = _price(row)
        if price is None:
            continue
        side = _match_side(_outcome_text(row), player1, player2)
        if side is None:
            side = _match_side(str(row.get("choiceCode") or row.get("outcomeCode") or row.get("type") or ""), player1, player2)
        if side not in {1, 2}:
            continue
        prices.setdefault(side, float(price))
        market_used = market_name
    if set(prices) != {1, 2}:
        return None
    return {"player1_odds": prices[1], "player2_odds": prices[2], "market_name": market_used}



def extract_player_total_ou(payload: Any, metric: str, player_name: str, *, player_slot: int | None = None) -> list[dict[str, Any]]:
    """Extract two-sided individual player Aces / Double Faults O/U markets.

    Only the named player's complete markets count. A match-total or Most Aces
    market is never a substitute; both sides must have prices for one line.
    """
    metric = str(metric or "").strip().lower()
    if metric not in {"aces", "double_faults"} or not player_name:
        return []
    subject = _normal(player_name)
    candidates: dict[tuple[str, float], dict[str, Any]] = {}
    for row, market_name in _walk_market_rows(payload):
        text = _normal(market_name)
        if metric == "aces":
            metric_matches = re.search(r"\baces?\b", text)
        else:
            metric_matches = "double fault" in text or "doublefault" in text
        if not metric_matches or any(token in text for token in (
            "most", "winner", "who", "more than", "set 1", "1st set",
            "first set", "set 2", "second set", "tiebreak", "tie break",
        )):
            continue
        # The market must explicitly identify this player's total. Generic
        # match totals contain no player identity and are excluded.
        player_field = _normal(row.get("playerName") or row.get("player_name") or
                               row.get("participantName") or row.get("participant_name"))
        named = subject in text or player_field == subject
        numbered = player_slot in {1, 2} and (
            f"player {player_slot}" in text or f"player{player_slot}" in text
        )
        if not (named or numbered):
            continue
        choice = _outcome_text(row)
        side = _over_under(choice, row)
        line = _explicit_line(row, choice)
        price = _price(row)
        if side not in {"over", "under"} or line is None or price is None:
            continue
        if not (0.5 <= line <= (40.5 if metric == "aces" else 20.5)):
            continue
        key = (text, float(line))
        item = candidates.setdefault(key, {
            "line": float(line), "market_name": market_name,
            "player_name": player_name,
        })
        item.setdefault(side, float(price))
    return [item for item in candidates.values() if "over" in item and "under" in item]


def _player_ou_probability(mean: float, metric: str, line: float) -> float:
    """Provisional single-player count model; backtest before EV-led rollout."""
    floor = 1.20 ** 2 if metric == "aces" else 0.95 ** 2
    variance = max(floor, mean * (0.90 if metric == "aces" else 1.10))
    # Count is integer: Over N.5 corresponds to X >= floor(N.5)+1.
    threshold = math.floor(line) + 0.5
    return 0.5 * math.erfc((threshold - mean) / math.sqrt(2.0 * variance))


def _card_players(card: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    p1 = card.get("player1") if isinstance(card.get("player1"), dict) else {}
    p2 = card.get("player2") if isinstance(card.get("player2"), dict) else {}
    return p1, p2


def _attach_sg(card: dict[str, Any], payload: Any, captured_at: str, provider_id: int) -> tuple[dict[str, Any], bool, str]:
    out = deepcopy(card)
    metric = str(out.get("market") or "").strip().lower()
    markets = extract_match_total_odds(payload, metric)
    if not markets:
        return out, False, "no_exact_match_total_market"
    projection = _number(out.get("projection"))
    if projection is None:
        return out, False, "missing_projection"
    desired = "over" if projection > (_number(out.get("reference_projection")) or projection) else "under"
    if metric == "sets":
        sid = str(out.get("selection_id") or "").lower().split(":")
        if len(sid) >= 2 and sid[1] in {"over", "under"}:
            desired = sid[1]
    elif metric == "games":
        direction = _normal(out.get("projection_direction"))
        if direction in {"high", "over"}:
            desired = "over"
        elif direction in {"low", "under"}:
            desired = "under"

    reference = _number(out.get("reference_projection"))
    # Prefer the provider line closest to the model's pre-existing reference, but
    # never rewrite the model projection itself.
    target = reference if reference is not None else projection
    market = min(markets, key=lambda item: abs(float(item["line"]) - target))
    line = float(market["line"])
    tolerance = 0.55 if metric == "sets" else 2.0
    if reference is not None and abs(line - reference) > tolerance:
        return out, False, "provider_line_too_far_from_model_reference"
    # The bookmaker line must agree with the model direction; otherwise it is a
    # different bet and is not silently substituted.
    if (projection > line and desired != "over") or (projection < line and desired != "under") or projection == line:
        return out, False, "projection_direction_market_mismatch"
    odds = _number(market.get(desired))
    if odds is None or odds <= 1:
        return out, False, "missing_decimal_price"
    unit = "Sets" if metric == "sets" else "Games"
    out.update({
        "market_line": round(line, 2),
        "reference_projection": round(line, 2),
        "selection": f"{desired.title()} {line:.1f} {unit}",
        "pick": f"{desired.title()} {line:.1f} {unit}",
        "selection_id": f"{metric}:{desired}:{line:.1f}",
        "odds": round(float(odds), 3),
        "price_status": "priced_projection",
        "provider_id": int(provider_id),
        "captured_at": captured_at,
        "odds_market_name": market.get("market_name"),
    })
    return out, True, "priced"

def _attach_ace(card: dict[str, Any], payload: Any, captured_at: str, provider_id: int) -> tuple[dict[str, Any], bool, str]:
    out = deepcopy(card)
    metric = str(out.get("market") or "").strip().lower()
    p1, p2 = _card_players(out)
    name1, name2 = str(p1.get("name") or ""), str(p2.get("name") or "")
    selected_id = str(out.get("selection_id") or "")
    if selected_id and selected_id == str(p1.get("id") or ""):
        slot, selected_name = 1, name1
    elif selected_id and selected_id == str(p2.get("id") or ""):
        slot, selected_name = 2, name2
    else:
        return out, False, "selection_not_resolved_to_market_side"

    # Keep the identical Most Aces / Most DF wager where the bookmaker offers it.
    superiority = extract_player_superiority_odds(payload, metric, name1, name2)
    if superiority:
        odds = superiority["player1_odds"] if slot == 1 else superiority["player2_odds"]
        out.update({
            "odds": round(float(odds), 3), "price_status": "priced_projection",
            "provider_id": int(provider_id), "captured_at": captured_at,
            "odds_market_name": superiority.get("market_name"),
            "price_contract": "player_superiority",
        })
        return out, True, "priced"

    # Otherwise convert the COUNT prediction, not the superiority confidence,
    # to a new player-specific O/U contract with a REAL provider price.
    options = extract_player_total_ou(payload, metric, selected_name, player_slot=slot)
    mean = _number(out.get("projection"))
    if mean is None or mean < 0:
        return out, False, "missing_player_count_projection"
    priced = []
    for option in options:
        p_over = _player_ou_probability(mean, metric, option["line"])
        for direction in ("over", "under"):
            probability = p_over if direction == "over" else 1 - p_over
            odds = float(option[direction])
            ev = probability * odds - 1
            if probability >= 0.60 and ev >= 0:
                priced.append((ev, probability, odds, direction, option))
    if not priced:
        return out, False, ("no_exact_player_total_ou_market" if not options
                            else "player_total_ou_not_qualified")
    _ev, probability, odds, direction, choice = max(priced, key=lambda x: (x[0], x[1]))
    line = float(choice["line"])
    stat = "Aces" if metric == "aces" else "Double Faults"
    out.update({
        "selection": f"{selected_name} {direction.title()} {line:.1f} {stat}",
        "pick": f"{selected_name} {direction.title()} {line:.1f} {stat}",
        "market_type": f"Player {stat} Over/Under",
        "projection_label": f"Hráč · {stat} O/U",
        # Preserve player ID as the selection identity and use explicit
        # contract fields for settlement; no retroactive changes to old picks.
        "price_contract": "player_total_ou",
        "ou_side": direction, "market_line": line,
        "model_probability": round(probability, 4),
        "expected_value": round(_ev, 4),
        "odds": round(odds, 3), "price_status": "priced_projection",
        "provider_id": int(provider_id), "captured_at": captured_at,
        "odds_market_name": choice["market_name"],
    })
    return out, True, "priced_player_total_ou"

def prefetch_projection_market_board(
    provider: Any, predictions: list[dict[str, Any]], *, now: datetime,
    max_events: int, provider_id: int = 1,
) -> tuple[dict[str, Any], dict[str, set[str]], dict[str, Any]]:
    """Discover REAL available projection contracts BEFORE running projection models.

    One request per eligible upcoming event. Market names alone never qualify:
    require a complete two-sided GAMES/SETS market or complete Most Aces/DF
    or player-specific O/U for ACES/DF. The returned payloads are reused by
    Match Winner and projection pricing; no second request is necessary.
    """
    eligible = []
    seen = set()
    for row in predictions:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id or event_id in seen:
            continue
        scheduled = row.get("scheduled_at") or row.get("date")
        try:
            when = datetime.fromisoformat(str(scheduled).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            when = when.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if when <= now:
            continue
        seen.add(event_id)
        eligible.append((when, event_id, row))
    # Soonest upcoming eligible matches first; no provider calls for past rows.
    eligible.sort(key=lambda item: (item[0], item[1]))
    requested = eligible[:max(0, int(max_events))]
    payloads: dict[str, Any] = {}
    markets_by_event: dict[str, set[str]] = {}
    errors = 0
    stopped_on_budget = False
    counts = {key: 0 for key in ("aces", "double_faults", "games", "sets")}
    for _scheduled, event_id, row in requested:
        # One exhausted quota must not turn the rest of the board into a storm
        # of retries or falsely report unavailable bookmaker markets.
        limit = getattr(provider, "request_limit", None)
        spent = getattr(provider, "request_count", 0)
        if ((limit is not None and spent >= limit)
            or getattr(provider, "rate_limit_remaining", None) == 0):
            stopped_on_budget = True
            break
        try:
            payload = provider.event_odds(event_id, provider_id=provider_id)
        except RequestBudgetExceeded:
            stopped_on_budget = True
            break
        except Exception:
            errors += 1
            payloads[event_id] = None
            continue
        payloads[event_id] = payload
        supported = set()
        for metric in ("games", "sets"):
            if extract_match_total_odds(payload, metric):
                supported.add(metric)
        p1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
        p2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
        name1, name2 = str(p1.get("name") or ""), str(p2.get("name") or "")
        for metric in ("aces", "double_faults"):
            if ((name1 and name2 and extract_player_superiority_odds(
                    payload, metric, name1, name2))
                or (name1 and extract_player_total_ou(
                    payload, metric, name1, player_slot=1))
                or (name2 and extract_player_total_ou(
                    payload, metric, name2, player_slot=2))):
                supported.add(metric)
        if supported:
            markets_by_event[event_id] = supported
            for metric in supported:
                counts[metric] += 1
    return payloads, markets_by_event, {
        "schema": 1, "strategy": "odds_first_exact_two_sided_then_model",
        "eligible_upcoming": len(eligible), "events_requested": len(requested),
        "events_limited_out": max(0, len(eligible) - len(requested)),
        "events_with_projection_markets": len(markets_by_event),
        "events_without_projection_markets": max(
            0, len(payloads) - len(markets_by_event) - errors),
        "request_errors": errors, "stopped_on_budget": stopped_on_budget,
        "provider_payloads_fetched": len(payloads) - errors,
        "complete_markets_by_type": counts,
        "provider_id": int(provider_id),
        "policy": "exact_pre_match_two_sided_only_no_synthetic_prices",
    }


def enrich_projection_odds(provider: Any, ace_picks: list[dict[str, Any]], sg_picks: list[dict[str, Any]], *, max_events: int = 40, provider_id: int = 1, prefetched_payloads: dict[str, Any] | None = None, alternate_market_payloads: dict[str, dict[str, dict]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Attach exact provider prices to already-selected projection cards.

    Cards remain projection-only when no exact market is available.  This is a
    deliberate fail-closed behavior: BlinQ never substitutes confidence for odds.
    The report intentionally exposes observed provider market names and the exact
    reason a selected projection remained unpriced.
    """
    ace = [deepcopy(row) for row in (ace_picks or [])]
    sg = [deepcopy(row) for row in (sg_picks or [])]
    by_event: dict[str, list[tuple[str, int]]] = {}
    for kind, rows in (("ace", ace), ("sg", sg)):
        for index, row in enumerate(rows):
            event = str(row.get("event_id") or "").strip()
            if event:
                by_event.setdefault(event, []).append((kind, index))
    event_ids = list(by_event)[:max(0, int(max_events))]
    payloads: dict[str, Any] = dict(prefetched_payloads) if prefetched_payloads is not None else {}
    errors = 0
    for event_id in event_ids:
        if event_id in payloads:
            continue
        # Odds-first mode never spends additional calls on cards from an
        # unprobed event. The prefetch budget is the single source of truth.
        if prefetched_payloads is not None:
            payloads[event_id] = None
            continue
        try:
            payloads[event_id] = provider.event_odds(event_id, provider_id=provider_id)
        except Exception:
            errors += 1
            payloads[event_id] = None
    captured_at = datetime.now(timezone.utc).isoformat()
    priced = {"aces": 0, "double_faults": 0, "sets": 0, "games": 0}
    eligible = {"aces": 0, "double_faults": 0, "sets": 0, "games": 0}
    reasons: dict[str, dict[str, int]] = {key: {} for key in eligible}
    observed_market_names: dict[str, int] = {}
    attached_by_provider = {"rapidapi": 0, "propline": 0}

    # Record what the provider actually exposed on the exact projection events.
    # This makes missing Sets/Aces/DF prices diagnosable without guessing market
    # availability from a different event or provider.
    for payload in payloads.values():
        if payload is None:
            continue
        for _row, market_name in _walk_market_rows(payload):
            name = str(market_name or "").strip()
            if name:
                observed_market_names[name] = observed_market_names.get(name, 0) + 1

    for event_id, refs in by_event.items():
        payload = payloads.get(event_id)
        for kind, index in refs:
            row = ace[index] if kind == "ace" else sg[index]
            metric = str(row.get("market") or "").strip().lower()
            if metric in eligible:
                eligible[metric] += 1
            if payload is None and not (alternate_market_payloads or {}).get(event_id, {}).get(metric):
                reason = "odds_payload_unavailable_or_request_failed"
                if metric in reasons:
                    reasons[metric][reason] = reasons[metric].get(reason, 0) + 1
                continue
            alternate = (alternate_market_payloads or {}).get(event_id, {}).get(metric)
            actual_payload = alternate["payload"] if alternate else payload
            actual_provider = int(alternate["provider_id"]) if alternate else provider_id
            actual_captured = str(alternate.get("captured_at") or captured_at) if alternate else captured_at
            updated, ok, reason = (
                _attach_ace(row, actual_payload, actual_captured, actual_provider)
                if kind == "ace" else
                _attach_sg(row, actual_payload, actual_captured, actual_provider)
            )
            if ok:
                updated["odds_source"] = "propline" if alternate else "rapidapi"
                if alternate:
                    updated["odds_bookmaker"] = alternate.get("bookmaker")
                    updated["odds_provider_event_id"] = alternate.get("provider_event_id")
                attached_by_provider[updated["odds_source"]] += 1
            if kind == "ace":
                ace[index] = updated
            else:
                sg[index] = updated
            if metric in reasons:
                reasons[metric][reason] = reasons[metric].get(reason, 0) + 1
            if ok and metric in priced:
                priced[metric] += 1
    top_markets = dict(sorted(observed_market_names.items(), key=lambda item: (-item[1], item[0]))[:40])
    # Compact diagnostic on the *same events* as the projections. A provider
    # market name alone does not prove a complete pair of O/U prices exists.
    market_debug = []
    for event_id, refs in by_event.items():
        if len(market_debug) >= 80:
            break
        payload = payloads.get(event_id)
        if payload is None:
            continue
        requested_metrics = sorted({
            str((ace[i] if kind == "ace" else sg[i]).get("market") or "")
            for kind, i in refs
        })
        if not any(metric in {"games", "sets"} for metric in requested_metrics):
            continue
        total_rows = []
        for raw, name in _walk_market_rows(payload):
            if _is_match_total_market(name, "games") or _is_match_total_market(name, "sets"):
                total_rows.append({
                    "market": str(name)[:90],
                    "side": _over_under(_outcome_text(raw), raw),
                    "line": _explicit_line(raw, _outcome_text(raw)),
                    "priced": _price(raw) is not None,
                })
                if len(total_rows) >= 6:
                    break
        market_debug.append({
            "event_id": event_id,
            "projected_markets": requested_metrics,
            "total_market_sample": total_rows,
            "complete_games_lines": len(extract_match_total_odds(payload, "games")),
            "complete_sets_lines": len(extract_match_total_odds(payload, "sets")),
        })
    return ace, sg, {
        "schema": 2,
        "provider_id": int(provider_id),
        "events_considered": len(by_event),
        "events_requested": len(event_ids),
        "errors": errors,
        "attached_by_provider": attached_by_provider,
        "eligible_cards": eligible,
        "priced_cards": priced,
        "fail_closed_unpriced": {key: max(0, eligible[key] - priced[key]) for key in eligible},
        "unpriced_reasons": reasons,
        "observed_market_names_top40": top_markets,
        "match_total_market_debug": market_debug,
        "policy": "exact_provider_market_only_no_confidence_as_odds",
    }

