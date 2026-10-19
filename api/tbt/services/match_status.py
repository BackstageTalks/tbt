"""Lightweight post-start status refresh for BlinQ daily prediction rows.

The public prediction feed is immutable between full data refreshes, but users do
not need to wait for that refresh to see a finished match.  This module performs
an inexpensive runtime-only reconciliation against the tennis provider:

* pre-start rows remain silent in the UI;
* scheduled rows are shown as STARTED by the browser once their start time passes;
* a small hourly worker checks only unresolved, already-started fixtures;
* settled fixtures are persisted as win / loss / retired and are never re-queried.

No model probabilities, odds, publication commitments or historical training data
are changed here.
"""
from __future__ import annotations

from copy import deepcopy
import math
from datetime import datetime, timedelta, timezone
import re
import time
from typing import Any
from zoneinfo import ZoneInfo


TERMINAL_STATUSES = {"win", "loss", "retired", "void"}


def _explicitly_nonterminal_status(value: Any) -> bool:
    """Never settle live fixtures from an early/incomplete winnerCode."""
    status = str(value or "").strip().lower()
    return status.startswith((
        "inprogress", "in progress", "notstarted", "not started",
        "scheduled", "ongoing", "live", "suspended", "interrupted", "paused",
    ))

def verified_terminal_statuses(snapshot_statuses: Any) -> dict[str, dict[str, Any]]:
    """Fail closed when an older persisted winner was actually still live.

    This read-side guard prevents stale wrong results/KPI values between a
    runtime deployment and the next successful external scheduler check.
    The worker retains the raw prior snapshot to recheck and repair it.
    """
    if not isinstance(snapshot_statuses, dict):
        return {}
    return {
        str(event_id): row
        for event_id, row in snapshot_statuses.items()
        if isinstance(row, dict)
        and str(row.get("status") or "").strip().lower() in TERMINAL_STATUSES
        and not _explicitly_nonterminal_status(row.get("provider_status"))
    }


_PUBLIC_MATCH_WINNER_KEYS = (
    "top200_picks",
    "prime_picks",
    "top_daily_picks",
    "value_picks",
    "doubles_picks",
)
_PUBLIC_PROJECTION_KEYS = ("ace_picks", "sg_picks")
_PROJECTION_MARKETS = {"aces", "double_faults", "sets", "games"}
LEGACY_PENDING_CARRY_HOURS = 48


def _current_betting_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Return the active 06:00 Europe/Bratislava betting-day UTC bounds."""
    local_now = now.astimezone(ZoneInfo("Europe/Bratislava"))
    start_local = local_now.replace(hour=6, minute=0, second=0, microsecond=0)
    if local_now < start_local:
        start_local -= timedelta(days=1)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _scheduled_in_current_betting_day(row: dict[str, Any], now: datetime) -> bool:
    scheduled = _parse_time(row.get("scheduled_at") or row.get("date"))
    if scheduled is None:
        return False
    start, end = _current_betting_day_bounds(now)
    return start <= scheduled < end


def _event_id(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("event_id") or row.get("id") or row.get("match_id") or "").strip()


def _parse_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _selection_id(row: dict[str, Any]) -> str:
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    return str(
        betting.get("selection_id")
        or row.get("winner_id")
        or row.get("selection_id")
        or ""
    ).strip()


def _player_id(row: dict[str, Any], key: str) -> str:
    player = row.get(key) if isinstance(row.get(key), dict) else {}
    return str(player.get("id") or "").strip()


def deployed_priced_projection(row: dict[str, Any], feed: dict[str, Any]) -> dict[str, Any] | None:
    """Recover an immutable, already-served priced projection without a nested ledger.

    Daily serving rows can carry the complete frozen bookmaker contract while
    the private publication ledger is stored separately. A public row is enough
    evidence ONLY if both its quote capture and the serving feed generation
    strictly precede the match. Never turn arbitrary model-board projections
    or post-start captures into published Results.
    """
    if (
        not isinstance(row, dict) or not isinstance(feed, dict)
        or row.get("excluded_reason") or row.get("market_publications")
        or str(row.get("publication_status") or "published").lower() != "published"
        or str(row.get("price_status") or "").lower() != "priced_projection"
    ):
        return None
    scheduled = _parse_time(row.get("scheduled_at") or row.get("date"))
    issued = _parse_time(row.get("issued_at") or feed.get("generated_at"))
    captured = _parse_time(row.get("captured_at"))
    if not scheduled or not issued or not captured or not (captured <= issued < scheduled):
        return None
    try:
        odds = float(row.get("odds"))
        provider_id = int(row.get("provider_id"))
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(odds) or odds < 1.5 or provider_id <= 0:
        return None

    raw_market = str(row.get("market") or row.get("projection_metric") or "").lower()
    market = {"ace": "aces", "double-faults": "double_faults"}.get(raw_market, raw_market)
    sections = {"aces": "ace", "double_faults": "double_faults",
                "sets": "sets", "games": "games"}
    if market not in sections:
        return None
    p1, p2 = _player_id(row, "player1"), _player_id(row, "player2")
    if not p1 or not p2 or p1 == p2:
        return None

    selection_text = str(row.get("selection") or row.get("pick") or "").strip()
    match = re.search(r"\b(over|under)\s+(\d+(?:[.,]\d+)?)\b", selection_text, re.I)
    published_side = match.group(1).lower() if match else ""
    published_line = float(match.group(2).replace(",", ".")) if match else None
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    raw_side = str(
        row.get("side") or row.get("prediction_side") or row.get("selection_side")
        or row.get("projection_direction") or betting.get("side") or ""
    ).strip().lower()
    sides = {"o": "over", "high": "over", "above": "over", "higher": "over",
             "u": "under", "low": "under", "below": "under", "lower": "under"}
    side = sides.get(raw_side, raw_side) if raw_side else published_side
    if side not in {"over", "under"} or (published_side and side != published_side):
        return None

    line = None
    for raw in (
        row.get("line"), row.get("market_line"), row.get("betting_line"),
        row.get("bookmaker_line"), row.get("over_under_line"), row.get("total_line"),
        row.get("threshold"), betting.get("line"), betting.get("market_line"),
        published_line,
    ):
        if raw is None or raw == "":
            continue
        try:
            candidate = float(str(raw).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if math.isfinite(candidate) and candidate > 0:
            line = candidate
            break
    if line is None or (published_line is not None and abs(line - published_line) > 0.0001):
        return None

    source_selection = str(
        betting.get("selection_id") or row.get("projection_subject_id")
        or row.get("selection_id") or ""
    ).strip()
    if market in {"aces", "double_faults"}:
        if source_selection not in {p1, p2}:
            return None
        selection_id = source_selection
    elif market == "sets":
        selection_id = f"sets:{side}:{line:g}"
    else:
        selection_id = f"games:{'high' if side == 'over' else 'low'}"

    pub = {
        "section": sections[market], "market": market, "selection_id": selection_id,
        "selection": selection_text, "issued_at": issued.isoformat(),
        "publication_status": "published",
        "runtime_publication_evidence": "deployed_daily_offer_row",
        "price_status": "priced_projection", "odds": odds,
        "provider_id": provider_id, "captured_at": captured.isoformat(),
        "projection_scope": row.get("projection_scope") or (
            "player" if market in {"aces", "double_faults"} else "match_total"
        ),
        "projection_metric": market,
    }
    for name in ("projection", "data_depth", "model_probability", "betting_day",
                 "opponent_projection", "publication_key"):
        if row.get(name) is not None:
            pub[name] = deepcopy(row[name])
    if market in {"aces", "double_faults"}:
        pub.update(price_contract="player_total_ou", ou_side=side, market_line=line)
    elif market == "games":
        pub.update(projection_direction="high" if side == "over" else "low",
                   reference_projection=line)
    return pub


def prediction_rows(
    feed: dict[str, Any], *, now: datetime | None = None
) -> dict[str, dict[str, Any]]:
    """Return published Match Winner rows that need runtime settlement.

    Production feeds are restricted to the active 06:00–06:00 Bratislava
    betting day. Historical results rows and stale prior-day snapshots are
    never part of the hourly queue. The legacy upcoming fallback remains
    unrestricted only for focused compatibility tests / old payloads.
    """
    out: dict[str, dict[str, Any]] = {}
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    def add_rows(rows: Any) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            eid = _event_id(row)
            if not eid:
                continue
            existing = out.get(eid)
            # Prefer rows that carry both a selection and player identity.
            quality = int(bool(_selection_id(row))) + int(bool(_player_id(row, "player1")))
            old_quality = (
                int(bool(_selection_id(existing))) + int(bool(_player_id(existing, "player1")))
                if isinstance(existing, dict)
                else -1
            )
            if existing is None or quality > old_quality:
                out[eid] = row

    public_contract_present = any(key in feed for key in (_PUBLIC_MATCH_WINNER_KEYS + _PUBLIC_PROJECTION_KEYS))
    if public_contract_present:
        for key in _PUBLIC_MATCH_WINNER_KEYS:
            rows = feed.get(key)
            if isinstance(rows, list):
                add_rows([
                    row for row in rows
                    if isinstance(row, dict) and _scheduled_in_current_betting_day(row, now)
                ])
    else:
        # Compatibility fallback for focused tests/legacy payloads that predate
        # the public market-section contract. Production feeds carry the public
        # keys above, so generic model-board rows are never queued there.
        add_rows(feed.get("upcoming"))

    # Stat-only published fixtures must enter the same bounded finished-event
    # lookup. Prefer existing winner rows, and never treat an O/U selection ID
    # (e.g. sets:over:2.5) as the predicted match winner.
    if public_contract_present:
        for key in _PUBLIC_PROJECTION_KEYS:
            for row in feed.get(key, []) or []:
                if not isinstance(row, dict) or not _scheduled_in_current_betting_day(row, now):
                    continue
                eid = _event_id(row)
                if not eid or eid in out:
                    continue
                publications = row.get("market_publications") or []
                issued_projection = any(
                    isinstance(p, dict)
                    and str(p.get("market") or "").lower() in _PROJECTION_MARKETS
                    and p.get("issued_at")
                    and str(p.get("publication_status") or "") == "published"
                    for p in publications
                )
                if not issued_projection and deployed_priced_projection(row, feed) is None:
                    continue
                p1, p2 = _player_id(row, "player1"), _player_id(row, "player2")
                anchor = str(row.get("winner_id") or "").strip()
                if not p1 or not p2 or p1 == p2 or anchor not in {p1, p2}:
                    continue
                safe_row = dict(row)
                safe_row["betting"] = {}
                safe_row["selection_id"] = anchor
                out[eid] = safe_row

    return out


def event_ids_from_feed(feed: dict[str, Any]) -> set[str]:
    return set(prediction_rows(feed))


_RUNTIME_RESULT_SOURCE_KEYS = (
    "top200_picks",
    "daily_picks",
    "prime_picks",
    "top_daily_picks",
    "value_picks",
    "doubles_picks",
    "ace_picks",
    "sg_picks",
)

_RUNTIME_RESULT_SOURCE_SECTIONS = {
    "top200_picks": "top200",
    "daily_picks": "top_daily",
    "prime_picks": "prime",
    "top_daily_picks": "top_daily",
    "value_picks": "value",
    "doubles_picks": "doubles",
}


def _projection_contract_identity(publication: dict[str, Any]) -> str:
    """Do not deduplicate distinct player O/U lines on the same fixture."""
    explicit = str(publication.get("publication_key") or "").strip()
    if explicit:
        return "|" + explicit
    return "|" + "|".join((
        str(publication.get("price_contract") or ""),
        str(publication.get("ou_side") or publication.get("projection_direction") or ""),
        str(publication.get("market_line") if publication.get("market") in {"aces", "double_faults"}
            else publication.get("reference_projection")),
    ))


def _runtime_result_identity(
    row: dict[str, Any], publication: dict[str, Any], index: int = 0
) -> str:
    """Semantic result identity, independent of lifecycle timestamps."""
    event_id = _event_id(row)
    section = str(publication.get("section") or "").strip().lower()
    market = str(publication.get("market") or "match_winner").strip().lower()
    scope = str(publication.get("projection_scope") or "").strip().lower()
    metric = str(publication.get("projection_metric") or "").strip().lower()
    selection = str(
        publication.get("selection_id")
        or publication.get("winner_id")
        or publication.get("pick_id")
        or ""
    ).strip()
    if event_id and section and market and selection:
        base = f"{event_id}|{section}|{market}|{scope}|{metric}|{selection}"
        return base + _projection_contract_identity(publication) if market in _PROJECTION_MARKETS else base
    return f"{event_id}|{section}|{market}|{scope}|{metric}|{selection}|{index}"


def _deployed_match_winner_publication(
    row: dict[str, Any], source_key: str
) -> dict[str, Any] | None:
    """Derive the exact already-deployed Match Winner card for runtime settlement.

    The private serving release intentionally keeps immutable publication history
    in the separate ledger, so current daily section rows do not embed publication
    objects. Once such a row is being served by the production feed, the row
    itself is the exact public commitment. Runtime settlement may therefore copy
    its immutable market fields without inventing an issuance timestamp or
    changing any price/probability.
    """
    if row.get("excluded_reason"):
        return None
    section = _RUNTIME_RESULT_SOURCE_SECTIONS.get(source_key)
    selection = _selection_id(row)
    if not section or not selection:
        return None
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}

    publication: dict[str, Any] = {
        "section": section,
        "market": "match_winner",
        "selection_id": selection,
        "publication_status": "published",
        "runtime_publication_evidence": "deployed_daily_offer_row",
    }
    selection_text = (
        betting.get("selection")
        or row.get("selection")
        or row.get("pick")
        or row.get("prediction")
    )
    if selection_text not in (None, ""):
        publication["selection"] = deepcopy(selection_text)

    field_sources = {
        "odds": (betting.get("odds"), row.get("odds")),
        "model_probability": (
            betting.get("model_probability"),
            row.get("blinq_probability"),
            row.get("probability"),
        ),
        "edge": (betting.get("edge"), row.get("edge")),
        "expected_value": (
            betting.get("expected_value"),
            row.get("expected_value"),
        ),
        "fair_implied_probability": (
            betting.get("fair_implied_probability"),
            row.get("fair_implied_probability"),
        ),
        "captured_at": (betting.get("captured_at"), row.get("captured_at")),
        "provider_id": (betting.get("provider_id"), row.get("provider_id")),
        "betting_day": (betting.get("betting_day"), row.get("betting_day")),
    }
    for field, candidates in field_sources.items():
        for value in candidates:
            if value not in (None, ""):
                publication[field] = deepcopy(value)
                break

    # Preserve a real issuance marker if an older/newer serving schema happens
    # to carry it, but never manufacture one merely to make Results render.
    issued_at = row.get("issued_at")
    if issued_at:
        publication["issued_at"] = deepcopy(issued_at)
    return publication


def _runtime_publication_key(
    row: dict[str, Any], publication: dict[str, Any], index: int = 0
) -> str:
    event_id = _event_id(row)
    section = str(publication.get("section") or "").strip().lower()
    market = str(publication.get("market") or "match_winner").strip().lower()
    selection = str(
        publication.get("selection_id")
        or publication.get("winner_id")
        or publication.get("pick_id")
        or ""
    ).strip()
    issued_at = str(publication.get("issued_at") or "").strip()
    extra = _projection_contract_identity(publication) if market in _PROJECTION_MARKETS else ""
    if event_id and selection and issued_at:
        return f"{event_id}|{section}|{market}|{selection}|{issued_at}{extra}"
    return f"{event_id}|{section}|{market}|{selection}|{issued_at}{extra}|{index}"


def _finite_count(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and n >= 0 else None


def _grade_runtime_projection(
    row: dict[str, Any], publication: dict[str, Any], status_row: dict[str, Any]
) -> dict[str, Any] | None:
    """Apply the frozen offline market rules without importing ML dependencies.

    Only verified full-match evidence from the same event can settle a market.
    Partial provider counts and unpriced projections never invent betting ROI.
    """
    market = str(publication.get("market") or "").lower()
    scheduled = _parse_time(row.get("scheduled_at"))
    issued = _parse_time(publication.get("issued_at"))
    if scheduled is None or issued is None or issued >= scheduled:
        return None
    state = str(status_row.get("status") or "").lower()
    if state not in TERMINAL_STATUSES:
        return None
    players = {_player_id(row, "player1"), _player_id(row, "player2")}
    provider_players = {str(status_row.get("provider_home_id") or ""), str(status_row.get("provider_away_id") or "")}
    if "" in players or players != provider_players:
        return None
    base = {
        "settled_at": status_row.get("checked_at") or scheduled.isoformat(),
        "scheduled_at": scheduled.isoformat(),
        "runtime_overlay": True,
        "runtime_source": "match_status_snapshot",
    }
    if state in {"retired", "void"}:
        result = {**base, "status": "void", "reason": state,
                  "correct": None, "void": True,
                  "staked_units": 0.0, "return_units": 0.0, "profit_units": 0.0}
    else:
        stats = status_row.get("projection_stats")
        if not isinstance(stats, dict):
            return None
        actual = other = reference = None
        selected = str(publication.get("selection_id") or "")
        if market in {"aces", "double_faults"}:
            p1, p2 = _player_id(row, "player1"), _player_id(row, "player2")
            if not p1 or not p2 or p1 == p2 or selected not in {p1, p2}:
                return None
            if (str(status_row.get("projection_stats_p1_id") or "") != p1
                    or str(status_row.get("projection_stats_p2_id") or "") != p2):
                return None
            own = "p1" if selected == p1 else "p2"
            opponent = "p2" if own == "p1" else "p1"
            actual = _finite_count(stats.get(f"{own}_{market}"))
            other = _finite_count(stats.get(f"{opponent}_{market}"))
            if actual is None:
                return None
            contract = str(publication.get("price_contract") or "").lower()
            if contract == "player_total_ou":
                direction = str(publication.get("ou_side") or "").lower()
                reference = _finite_count(publication.get("market_line"))
                if reference is None or direction not in {"over", "under"}:
                    return None
                correct = actual > reference if direction == "over" else actual < reference
                equal = actual == reference
            elif contract in {"", "player_superiority"}:
                if other is None:
                    return None
                correct = actual > other
                equal = actual == other
            else:
                return None
        elif market in {"sets", "games"}:
            actual = _finite_count(stats.get("total_sets" if market == "sets" else "total_games"))
            if actual is None or actual <= 0:
                return None
            if market == "sets":
                parts = selected.lower().split(":")
                if len(parts) < 3 or parts[0] != "sets" or parts[1] not in {"over", "under"}:
                    return None
                direction = parts[1]
                reference = _finite_count(parts[2])
            else:
                direction = str(publication.get("projection_direction") or "").lower()
                if not direction and selected.lower().startswith("games:"):
                    direction = selected.lower().split(":", 1)[1]
                reference = _finite_count(publication.get("reference_projection"))
                if direction not in {"high", "low"}:
                    return None
            if reference is None:
                return None
            correct = actual > reference if direction in {"over", "high"} else actual < reference
            equal = actual == reference
        else:
            return None
        status = "void" if equal else "hit" if correct else "miss"
        result = {
            **base, "status": status, "correct": None if equal else correct,
            "void": equal, "actual_count": actual,
            "projection": publication.get("projection"),
            "projection_scope": publication.get("projection_scope") or (
                "player" if market in {"aces", "double_faults"} else "match_total"
            ),
            "projection_metric": publication.get("projection_metric") or market,
            "data_depth": publication.get("data_depth"),
        }
        if other is not None:
            result["opponent_actual_count"] = other
        if market in {"aces", "double_faults"}:
            result["opponent_projection"] = publication.get("opponent_projection")
        else:
            result["reference_projection"] = reference
        if equal:
            result.update(staked_units=0.0, return_units=0.0, profit_units=0.0)
        elif str(publication.get("price_status") or "").lower() == "priced_projection":
            odds = _finite_count(publication.get("odds"))
            if odds is not None and odds > 1:
                result.update(
                    staked_units=1.0,
                    return_units=odds if correct else 0.0,
                    profit_units=odds - 1.0 if correct else -1.0,
                )
    scored = deepcopy(publication)
    scored["result"] = result
    return scored


def runtime_settled_results(
    feed: dict[str, Any], statuses: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Overlay verified match-winner settlements onto an already-authorized feed.

    The durable prediction ledger and deployed feed remain immutable. This helper
    only builds response-time Results rows from the external match-status snapshot,
    and only for issued match-winner publications visible to this account.
    Projection markets (ACES/DF/Games/Sets) are intentionally never settled from
    a match-winner outcome.
    """
    existing_results = [
        deepcopy(row) for row in (feed.get("results") or []) if isinstance(row, dict)
    ]
    statuses = verified_terminal_statuses(statuses)
    if not statuses:
        return existing_results

    seen: set[str] = set()
    seen_identities: set[str] = set()
    for row in existing_results:
        for index, publication in enumerate(row.get("market_publications") or []):
            if isinstance(publication, dict):
                seen.add(_runtime_publication_key(row, publication, index))
                seen_identities.add(_runtime_result_identity(row, publication, index))

    runtime_rows: list[dict[str, Any]] = []
    runtime_seen: set[str] = set()
    runtime_seen_identities: set[str] = set()
    for source_key in _RUNTIME_RESULT_SOURCE_KEYS:
        rows = feed.get(source_key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            event_id = _event_id(row)
            status_row = statuses.get(event_id)
            if not isinstance(status_row, dict):
                continue
            status = str(status_row.get("status") or "").strip().lower()
            if status not in TERMINAL_STATUSES:
                continue

            expected_selection = _selection_id(row)
            overlay_publications: list[dict[str, Any]] = []
            source_publications = [
                publication
                for publication in (row.get("market_publications") or [])
                if isinstance(publication, dict)
            ]
            if not source_publications:
                deployed = (
                    deployed_priced_projection(row, feed)
                    if source_key in _PUBLIC_PROJECTION_KEYS
                    else _deployed_match_winner_publication(row, source_key)
                )
                if deployed is not None:
                    source_publications = [deployed]

            for index, publication in enumerate(source_publications):
                runtime_evidence = (
                    publication.get("runtime_publication_evidence")
                    == "deployed_daily_offer_row"
                )
                if (
                    (not publication.get("issued_at") and not runtime_evidence)
                    or publication.get("excluded_reason")
                ):
                    continue
                section = str(publication.get("section") or "").strip().lower()
                market = str(publication.get("market") or "").strip().lower()
                if not market and section in {"top200", "top_daily", "prime", "value", "doubles"}:
                    market = "match_winner"
                projection = market in _PROJECTION_MARKETS
                if market != "match_winner" and not projection:
                    continue
                publication_status = str(
                    publication.get("publication_status") or "published"
                ).strip().lower()
                if publication_status != "published":
                    continue
                selection = str(
                    publication.get("selection_id")
                    or publication.get("winner_id")
                    or publication.get("pick_id")
                    or ""
                ).strip()
                if not projection and expected_selection and selection and selection != expected_selection:
                    continue

                key = _runtime_publication_key(row, publication, index)
                identity = _runtime_result_identity(row, publication, index)
                if (
                    key in seen
                    or key in runtime_seen
                    or identity in seen_identities
                    or identity in runtime_seen_identities
                ):
                    continue

                if projection:
                    scored = _grade_runtime_projection(row, publication, status_row)
                    if scored is None:
                        continue
                    overlay_publications.append(scored)
                    runtime_seen.add(key)
                    runtime_seen_identities.add(identity)
                    continue

                result = publication.get("result")
                result = deepcopy(result) if isinstance(result, dict) else {}
                checked_at = str(status_row.get("checked_at") or "").strip()
                scheduled_at = str(row.get("scheduled_at") or row.get("date") or "").strip()
                odds_raw = publication.get("odds")
                try:
                    odds = float(odds_raw)
                except (TypeError, ValueError):
                    odds = 0.0

                if status in {"retired", "void"}:
                    result.update({
                        "status": "retired" if status == "retired" else "void",
                        "correct": None,
                        "void": True,
                        "reason": "retired" if status == "retired" else (
                            str(status_row.get("provider_status") or "void")[:120]
                        ),
                        "staked_units": 0.0,
                        "return_units": 0.0,
                        "profit_units": 0.0,
                    })
                else:
                    correct = status == "win"
                    result.update({
                        "status": "hit" if correct else "miss",
                        "correct": correct,
                    })
                    # A live status can settle W/L without odds, but financial
                    # fields are created only when the issued publication has a
                    # genuine price. This keeps ROI fail-closed.
                    if odds > 1:
                        result.update({
                            "staked_units": 1.0,
                            "return_units": odds if correct else 0.0,
                            "profit_units": (odds - 1.0) if correct else -1.0,
                        })
                for context_key in (
                    "first_set_outcome", "first_set_score",
                    "max_live_odds", "max_live_odds_at",
                    "live_odds_observations", "live_odds_scope",
                ):
                    context_value = status_row.get(context_key)
                    if context_value not in (None, ""):
                        result[context_key] = deepcopy(context_value)
                result.update({
                    "settled_at": checked_at or scheduled_at,
                    "scheduled_at": scheduled_at,
                    "runtime_overlay": True,
                    "runtime_source": "match_status_snapshot",
                })
                copy = deepcopy(publication)
                copy["result"] = result
                overlay_publications.append(copy)
                runtime_seen.add(key)
                runtime_seen_identities.add(identity)

            if overlay_publications:
                copy = deepcopy(row)
                copy["market_publications"] = overlay_publications
                copy["runtime_result_overlay"] = True
                runtime_rows.append(copy)

    combined = existing_results + runtime_rows
    combined.sort(
        key=lambda row: _parse_time(row.get("scheduled_at") or row.get("date"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return combined


def _provider_rows(payload: Any) -> list[dict[str, Any]]:
    """Extract event-shaped rows from common TennisApi wrappers."""
    found: list[dict[str, Any]] = []

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        if (
            value.get("id") is not None
            and isinstance(value.get("homeTeam"), dict)
            and isinstance(value.get("awayTeam"), dict)
        ):
            found.append(value)
            return
        for key in ("events", "data", "result", "results", "response", "matches",
                    "previousEvent", "previous", "lastEvent", "lastMatch",
                    "previousMatch", "event", "near", "last"):
            child = value.get(key)
            if isinstance(child, (list, dict)):
                walk(child, depth + 1)

    walk(payload)
    return found


def _provider_event_id(event: dict[str, Any]) -> str:
    return str(event.get("id") or event.get("eventId") or event.get("event_id") or "").strip()


def _status_text(event: dict[str, Any]) -> str:
    status = event.get("status")
    parts: list[str] = []
    if isinstance(status, dict):
        parts.extend(
            str(status.get(key) or "")
            for key in ("type", "description", "name", "reason")
        )
    elif status is not None:
        parts.append(str(status))
    parts.extend(
        str(event.get(key) or "")
        for key in (
            "statusDescription",
            "status_description",
            "reason",
            "retirementReason",
            "retirement_reason",
        )
    )
    return " ".join(parts).strip().lower()


def classify_finished_event(
    row: dict[str, Any],
    event: dict[str, Any],
    *,
    checked_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Classify a provider event as win/loss/retired for the predicted side."""
    checked_at = checked_at or datetime.now(timezone.utc)
    status_text = _status_text(event)
    retirement_markers = (
        "retired",
        "retirement",
        "ret.",
        "retd",
        "abandoned due to injury",
    )
    retired = any(marker in status_text for marker in retirement_markers)
    void = any(marker in status_text for marker in (
        "cancelled", "canceled", "walkover", "walk over", "w/o",
    ))

    winner_code = event.get("winnerCode")
    try:
        winner_code = int(winner_code)
    except (TypeError, ValueError):
        winner_code = 0

    # Some provider events expose winnerCode while the match is still live.
    # Require a confirmed terminal provider status before issuing W/L.
    if _explicitly_nonterminal_status(status_text):
        return None
    finished = any(
        marker in status_text
        for marker in ("finished", "ended", "completed", "full time")
    )
    if not finished and not retired and not void:
        return None

    base = {
        "checked_at": checked_at.isoformat(),
        "provider_status": status_text[:120],
    }
    home = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
    away = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
    # A recycled or incorrectly mapped provider ID must never mark an
    # unrelated published pick as a loss (or retirement).
    feed_players = {_player_id(row, "player1"), _player_id(row, "player2")}
    provider_players = {str(home.get("id") or "").strip(), str(away.get("id") or "").strip()}
    if "" in feed_players or "" in provider_players or feed_players != provider_players:
        return None
    base["provider_home_id"] = str(home.get("id") or "")
    base["provider_away_id"] = str(away.get("id") or "")
    if retired:
        return {**base, "status": "retired"}
    if void:
        return {**base, "status": "void"}

    provider_winner = ""
    if winner_code == 1:
        provider_winner = str(home.get("id") or "").strip()
    elif winner_code == 2:
        provider_winner = str(away.get("id") or "").strip()
    # A verified direct winner identifier is valid evidence when winnerCode is
    # absent. If both signals exist but disagree, quarantine instead of scoring.
    direct_winner = str(
        event.get("winnerId") or event.get("winner_id") or event.get("winnerTeamId") or ""
    ).strip()
    if direct_winner and direct_winner not in provider_players:
        return None
    if direct_winner and provider_winner and direct_winner != provider_winner:
        return None
    provider_winner = provider_winner or direct_winner
    if not provider_winner:
        return None

    predicted = _selection_id(row)
    if not predicted:
        return None

    first_set_outcome = ""
    first_set_score = ""
    home_score = event.get("homeScore") if isinstance(event.get("homeScore"), dict) else {}
    away_score = event.get("awayScore") if isinstance(event.get("awayScore"), dict) else {}
    try:
        home_set1 = int(home_score.get("period1"))
        away_set1 = int(away_score.get("period1"))
    except (TypeError, ValueError):
        home_set1 = away_set1 = -1
    hi, lo = max(home_set1, away_set1), min(home_set1, away_set1)
    if ((hi == 6 and 0 <= lo <= 4) or (hi == 7 and lo in {5, 6})):
        first_set_winner = (
            str(home.get("id") or "").strip()
            if home_set1 > away_set1
            else str(away.get("id") or "").strip()
        )
        if first_set_winner:
            first_set_outcome = "win" if predicted == first_set_winner else "loss"
            predicted_home = predicted == str(home.get("id") or "").strip()
            predicted_games = home_set1 if predicted_home else away_set1
            opponent_games = away_set1 if predicted_home else home_set1
            first_set_score = f"{predicted_games}:{opponent_games}"

    return {
        **base,
        "status": "win" if predicted == provider_winner else "loss",
        "winner_id": provider_winner,
        "provider_home_id": str(home.get("id") or ""),
        "provider_away_id": str(away.get("id") or ""),
        "projection_stats": _verified_final_score_stats(row, event),
        **({"first_set_outcome": first_set_outcome, "first_set_score": first_set_score}
           if first_set_outcome else {}),
    }


def _verified_final_score_stats(row: dict[str, Any], event: dict[str, Any]) -> dict[str, int]:
    """Require a complete, identity-matched, terminal tennis score.

    Incomplete period data and super-tiebreak ambiguity are left ungraded.
    Match winner and publisher identities were checked by classify_finished_event.
    """
    home = event.get("homeScore") if isinstance(event.get("homeScore"), dict) else {}
    away = event.get("awayScore") if isinstance(event.get("awayScore"), dict) else {}
    home_team = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
    away_team = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
    home_id, away_id = str(home_team.get("id") or ""), str(away_team.get("id") or "")
    if not home_id or not away_id or home_id == away_id:
        return {}
    if {home_id, away_id} != {_player_id(row, "player1"), _player_id(row, "player2")}:
        return {}
    direct_winner = str(
        event.get("winnerId") or event.get("winner_id") or event.get("winnerTeamId") or ""
    ).strip()
    try:
        winner_code = int(event.get("winnerCode"))
    except (TypeError, ValueError):
        winner_code = 0
    if winner_code not in (1, 2):
        winner_code = 1 if direct_winner == home_id else 2 if direct_winner == away_id else 0
    elif direct_winner and (home_id if winner_code == 1 else away_id) != direct_winner:
        return {}
    if winner_code not in (1, 2):
        return {}
    sets = []
    seen_gap = False
    for index in range(1, 6):
        a, b = home.get(f"period{index}"), away.get(f"period{index}")
        if a is None and b is None:
            seen_gap = True
            continue
        if seen_gap or a is None or b is None:
            return {}
        try:
            ga, gb = int(a), int(b)
        except (TypeError, ValueError):
            return {}
        if ga < 0 or gb < 0 or ga == gb:
            return {}
        high, low = max(ga, gb), min(ga, gb)
        if not ((high == 6 and low <= 4) or (high == 7 and low in (5, 6))):
            return {}
        sets.append((ga, gb))
    if len(sets) not in (2, 3, 4, 5):
        return {}
    home_wins = sum(a > b for a, b in sets)
    away_wins = len(sets) - home_wins
    target = 3 if len(sets) >= 4 or str(row.get("best_of") or "") == "5" or max(home_wins, away_wins) == 3 else 2
    if max(home_wins, away_wins) != target:
        return {}
    if (home_wins > away_wins) != (winner_code == 1):
        return {}
    if str(row.get("best_of") or "") == "3" and len(sets) > 3:
        return {}
    return {"total_sets": len(sets), "total_games": sum(a+b for a, b in sets)}


def _second_set_outcome(row: dict[str, Any], event: dict[str, Any]) -> str:
    """Return win/loss for the predicted player once set 2 is complete."""
    home_score = event.get("homeScore") if isinstance(event.get("homeScore"), dict) else {}
    away_score = event.get("awayScore") if isinstance(event.get("awayScore"), dict) else {}
    try:
        home = int(home_score.get("period2"))
        away = int(away_score.get("period2"))
    except (TypeError, ValueError):
        return ""
    hi, lo = max(home, away), min(home, away)
    if not ((hi == 6 and lo <= 4) or (hi == 7 and lo in {5, 6})):
        return ""
    home_team = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
    away_team = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
    home_id = str(home_team.get("id") or "").strip()
    away_id = str(away_team.get("id") or "").strip()
    predicted = _selection_id(row)
    if not predicted or predicted not in {home_id, away_id}:
        return ""
    set_winner = home_id if home > away else away_id
    return "win" if predicted == set_winner else "loss"



# A confirmed fixture start-time correction is presentation evidence and can
# outlive a single worker pass. A LIVE marker needs much fresher evidence.
_SCHEDULE_FRESHNESS = timedelta(hours=24)
_LIVE_FRESHNESS = timedelta(minutes=75)
_SCHEDULE_MAX_MOVE = timedelta(days=14)


def verified_schedule_observation(
    row: dict[str, Any], event: dict[str, Any], now: datetime
) -> dict[str, str] | None:
    """Display-only timing evidence, bound to exact provider event AND two player IDs.

    Do not interpret a stale scheduled time or a winnerCode as proof of kickoff.
    Published pick/odds/ledger timestamps remain immutable.
    """
    if _provider_event_id(event) != _event_id(row):
        return None
    home = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
    away = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
    identity = {_player_id(row, "player1"), _player_id(row, "player2")}
    provider_identity = {str(home.get("id") or ""), str(away.get("id") or "")}
    if "" in identity or "" in provider_identity or identity != provider_identity:
        return None
    original = _parse_time(row.get("scheduled_at") or row.get("date"))
    if original is None:
        return None
    raw = next((
        event[key] for key in ("startTimestamp", "startTime", "scheduledAt", "scheduled_at")
        if event.get(key) not in (None, "")
    ), None)
    scheduled = None
    try:
        if isinstance(raw, (int, float)) or (
            isinstance(raw, str) and raw.strip().isdigit()
        ):
            number = float(raw)
            if number > 1e12:
                number /= 1000
            scheduled = datetime.fromtimestamp(number, tz=timezone.utc)
        else:
            scheduled = _parse_time(raw)
    except (OverflowError, OSError, ValueError, TypeError):
        return None
    if scheduled is None or abs(scheduled - original) > _SCHEDULE_MAX_MOVE:
        return None
    raw_status = event.get("status")
    status_type = (
        str(raw_status.get("type") or "").strip().lower()
        if isinstance(raw_status, dict)
        else str(raw_status or "").strip().lower()
    )
    # Only an explicit tennis-provider live/finished state proves kickoff.
    # In particular, time passing, 'notstarted' and 'postponed' do NOT.
    state = (
        "live" if status_type.startswith(("inprogress", "in progress", "live", "started"))
        else "finished" if status_type in {"finished", "ended", "completed"}
        else "scheduled"
    )
    # Contradictory provider data cannot claim kickoff hours before its own
    # updated scheduled time. Prefer showing the reschedule, not false LIVE.
    if state == "live" and scheduled > now + timedelta(minutes=5):
        state = "scheduled"
    return {
        "scheduled_at": scheduled.isoformat(),
        "status": state,
        "checked_at": now.isoformat(),
        "source": "tennis_api_pro",
    }


def _fresh_verified_schedule(
    value: Any, *, now: datetime
) -> dict[str, str] | None:
    if not isinstance(value, dict) or value.get("source") != "tennis_api_pro":
        return None
    checked = _parse_time(value.get("checked_at"))
    scheduled = _parse_time(value.get("scheduled_at"))
    if (
        checked is None or scheduled is None
        or checked > now + timedelta(minutes=2)
        or now - checked > _SCHEDULE_FRESHNESS
    ):
        return None
    if value.get("status") not in {"scheduled", "live", "finished"}:
        return None
    # Retain the verified rescheduled time for a day, but never keep calling
    # a match LIVE just because a previous poll saw it in progress.
    status = value["status"]
    if status == "live" and now - checked > _LIVE_FRESHNESS:
        status = "scheduled"
    return {
        "scheduled_at": scheduled.isoformat(),
        "status": status,
        "checked_at": checked.isoformat(),
        "source": "tennis_api_pro",
    }


def apply_verified_schedule_overlay(
    feed: dict[str, Any],
    observations: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Patch only authorized RESPONSE presentation rows, never a release or ledger.

    The caller supplies an already entitlement-filtered feed. Ignore arbitrary
    generic/unpublished board events not in its published pick sections.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    allowed = set(prediction_rows(feed, now=now))
    verified = {
        str(eid): fresh for eid, value in (observations or {}).items()
        if str(eid) in allowed
        and (fresh := _fresh_verified_schedule(value, now=now)) is not None
    } if isinstance(observations, dict) else {}
    if not verified:
        return feed
    for key in (
        "top200_picks", "prime_picks", "top_daily_picks", "daily_picks",
        "value_picks", "doubles_picks", "ace_picks", "sg_picks", "upcoming",
    ):
        rows = feed.get(key)
        if not isinstance(rows, list):
            continue
        updated = []
        for row in rows:
            entry = verified.get(_event_id(row))
            if not isinstance(row, dict) or entry is None:
                updated.append(row)
                continue
            updated.append({
                **row,
                "scheduled_at": entry["scheduled_at"],
                "runtime_schedule_checked_at": entry["checked_at"],
                "runtime_schedule_source": entry["source"],
                "runtime_match_started": entry["status"] in {"live", "finished"},
            })
        feed[key] = updated
    return feed

def _provider_error_code(error: Exception) -> str:
    """Only report a safe exception class and HTTP status, never URLs or payloads."""
    kind = type(error).__name__[:48]
    code = re.search(r"\bHTTP\s+([1-5]\d\d)\b", str(error))
    return f"{kind}_HTTP_{code.group(1)}" if code else kind


def scan_match_statuses(
    feed: dict[str, Any],
    provider: Any,
    previous_snapshot: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    max_checks: int = 30,
    max_near_checks: int = 30,
    max_wall_seconds: float | None = None,
) -> dict[str, Any]:
    """Settle verified events without trusting a consistently 404ing history route.

    TennisApi's /player/{id}/events/near is an alternate compact source for
    the closest previous/next match. It is NOT guaranteed to contain every
    historical match, so a missing event is left pending, never scored.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    # Stop before the Azure HTTP gateway deadline; defer, never discard, unfinished rows.
    deadline = (time.monotonic() + max(0.0, max_wall_seconds)
                if max_wall_seconds is not None else None)
    time_budget_exhausted = False
    public_contract_present = any(key in feed for key in (_PUBLIC_MATCH_WINNER_KEYS + _PUBLIC_PROJECTION_KEYS))
    rows = prediction_rows(feed, now=now)
    prior = previous_snapshot if isinstance(previous_snapshot, dict) else {}
    prior_pending = prior.get("pending")
    prior_pending = prior_pending if isinstance(prior_pending, dict) else {}

    # Production must evaluate only the currently published betting-day cohort.
    # Never carry yesterday's pending rows into today's worker. The historical
    # fallback is retained only for legacy payloads that do not have public
    # market-section keys.
    if not public_contract_present:
        carry_cutoff = now - timedelta(hours=LEGACY_PENDING_CARRY_HOURS)
        for eid, saved in prior_pending.items():
            if eid in rows or not isinstance(saved, dict):
                continue
            scheduled = _parse_time(saved.get("t"))
            if (
                str(saved.get("p") or "") != "1"
                or scheduled is None
                or scheduled < carry_cutoff
                or not (saved.get("s") and saved.get("a") and saved.get("b"))
            ):
                continue
            rows[eid] = {
                "event_id": eid, "scheduled_at": saved["t"], "winner_id": saved["s"],
                "player1": {"id": saved["a"]}, "player2": {"id": saved["b"]},
            }

    existing = prior.get("statuses")
    existing = existing if isinstance(existing, dict) else {}
    tracked_ids = set(rows)
    prior_schedule = prior.get("schedule_updates")
    prior_schedule = prior_schedule if isinstance(prior_schedule, dict) else {}
    schedule_updates = {
        str(eid): fresh for eid, value in prior_schedule.items()
        if str(eid) in tracked_ids
        and (fresh := _fresh_verified_schedule(value, now=now)) is not None
    }
    schedule_verified_this_run = 0
    def observe(eid: str, row: dict[str, Any], event: dict[str, Any]) -> None:
        nonlocal schedule_verified_this_run
        observed = verified_schedule_observation(row, event, now)
        if observed is not None:
            schedule_updates[eid] = observed
            schedule_verified_this_run += 1

    statuses: dict[str, dict[str, Any]] = {
        str(eid): dict(value)
        for eid, value in existing.items()
        if isinstance(value, dict)
        and str(value.get("status") or "") in TERMINAL_STATUSES
        # Repair snapshots prematurely settled from 'inprogress 2nd set'.
        # They must return to the due queue for verified final evidence.
        and not _explicitly_nonterminal_status(value.get("provider_status"))
        and (not public_contract_present or str(eid) in tracked_ids)
    }

    due: list[tuple[datetime, str, dict[str, Any]]] = []
    pending: dict[str, dict[str, str]] = {}
    for eid, row in rows.items():
        if eid in statuses:
            continue
        # A recently verified postponement must supersede the old feed ETA
        # when deciding which matches merit result lookups.
        corrected = schedule_updates.get(eid)
        scheduled = _parse_time((corrected or {}).get("scheduled_at") or row.get("scheduled_at") or row.get("date"))
        player1 = _player_id(row, "player1")
        player2 = _player_id(row, "player2")
        selection = _selection_id(row)
        if scheduled is None or not (player1 and player2 and selection):
            continue
        old = prior_pending.get(eid)
        old = old if isinstance(old, dict) else {}
        previous_side = str(old.get("n") or "").strip()
        if previous_side not in {"1", "2"}:
            # Older snapshots did not persist which participant had last been
            # queried. If the row was already checked, start with player2 on
            # the next run so a tight near-call cap cannot starve that side.
            previous_side = "2" if str(old.get("c") or "").strip() else "1"
        compact = {
            "t": scheduled.isoformat(), "s": selection,
            "a": player1, "b": player2, "c": str(old.get("c") or "")[:64],
            "p": "1", "n": previous_side,
        }
        # Keep postponed fixtures in the queue, without querying future starts.
        if eid in prior_pending:
            pending[eid] = compact
        if scheduled >= now:
            continue
        due.append((scheduled, eid, row))
        pending[eid] = compact

    # Preserve the full backlog, but under severe backlog pressure prioritize
    # the current Bratislava betting day (06:00–06:00) without increasing the
    # provider-request budget. At least one history slot remains available for
    # older pending fixtures so the backlog still drains.
    due.sort(key=lambda item: (item[0], item[1]))
    priority_limit = max(0, min(120, int(max_checks)))
    local_now = now.astimezone(ZoneInfo("Europe/Bratislava"))
    betting_day_start_local = local_now.replace(hour=6, minute=0, second=0, microsecond=0)
    if local_now < betting_day_start_local:
        betting_day_start_local -= timedelta(days=1)
    betting_day_start = betting_day_start_local.astimezone(timezone.utc)
    recent_due = [item for item in due if item[0] >= betting_day_start]
    backlog_due = [item for item in due if item[0] < betting_day_start]
    priority_mode = bool(
        recent_due and backlog_due and priority_limit >= 2
        and len(due) > max(40, priority_limit * 20)
    )

    def fairness_key(item: tuple[datetime, str, dict[str, Any]]):
        _, eid, _ = item
        old = prior_pending.get(eid)
        old = old if isinstance(old, dict) else {}
        last_checked = _parse_time(old.get("c"))
        return (
            last_checked or datetime.min.replace(tzinfo=timezone.utc),
            item[0],
            eid,
        )

    prior_errors = prior.get("provider_errors")
    prior_errors = prior_errors if isinstance(prior_errors, dict) else {}
    known_history_404 = int(prior_errors.get("ProviderError_HTTP_404") or 0) >= 2
    prefer_near = prior.get("preferred_route") == "near" or (
        known_history_404 and int(prior.get("successful_history") or 0) == 0
    )
    near_method = getattr(provider, "near_player_matches_for_status", None)
    daily_method = getattr(provider, "events_for_status_day", None)
    if not callable(daily_method):
        daily_method = getattr(provider, "events_with_odds_for_status_day", None)
    near_cache: dict[str, Any] = {}
    daily_cache: dict[str, Any] = {}
    max_near_checks = max(0, min(30, int(max_near_checks)))

    provider_errors: dict[str, int] = {}
    live_by_id: dict[str, dict[str, Any]] = {}
    nominal_requests = 0
    budget_paused = False
    request_count_before = getattr(provider, "request_count", None)
    if due:
        try:
            nominal_requests += 1
            live_events = provider.live_events()
            live_by_id = {
                _provider_event_id(event): event
                for event in live_events
                if isinstance(event, dict) and _provider_event_id(event)
            }
        except Exception as exc:
            code = _provider_error_code(exc)
            provider_errors[code] = provider_errors.get(code, 0) + 1
            if type(exc).__name__ == "SharedBudgetExhausted":
                # The shared daily quota guard stopped the call before it reached
                # the tennis provider. Preserve every pending fixture and exit
                # cleanly instead of retrying the same exhausted reservation.
                budget_paused = True

    # The same 30-minute settlement worker also reconciles fixture times
    # BEFORE their original start. Previously the daily provider route was
    # queried only for overdue matches, so a 11:00 -> 15:00 delay could remain
    # invisible through the morning. One bounded calendar pass is shared with
    # this worker's existing RapidAPI budget; it never writes issued picks.
    prestart_candidates = []
    for eid, row in rows.items():
        if eid in statuses or not _player_id(row, "player1") or not _player_id(row, "player2"):
            continue
        previous_time = schedule_updates.get(eid) or {}
        starts = _parse_time(previous_time.get("scheduled_at") or row.get("scheduled_at") or row.get("date"))
        if starts is not None and now <= starts <= now + timedelta(hours=8):
            prestart_candidates.append((starts, eid, row))
    prestart_candidates.sort(key=lambda item: (item[0], item[1]))
    prestart_checked = prestart_verified = prestart_attempts = 0
    if prestart_candidates and callable(daily_method) and not budget_paused:
        first_day = prestart_candidates[0][0].date()
        day_candidates = [(eid, row) for starts, eid, row in prestart_candidates
                          if starts.date() == first_day]
        # Leave time for results reconciliation and durable save/readback.
        if deadline is None or time.monotonic() + 8.0 < deadline:
            try:
                prestart_attempts = 1
                nominal_requests += 1
                try:
                    day_payload = daily_method(
                        first_day,
                        target_event_ids={eid for eid, _ in day_candidates},
                        max_category_requests=3,
                    )
                except TypeError:
                    # Legacy test/provider compatibility; the production
                    # provider accepts both the target and the hard cap.
                    day_payload = daily_method(first_day)
                candidates_by_id = {eid: row for eid, row in day_candidates}
                prestart_checked = len(day_candidates)
                for event in _provider_rows(day_payload):
                    eid = _provider_event_id(event)
                    row = candidates_by_id.get(eid)
                    if row is None:
                        continue
                    before = schedule_updates.get(eid)
                    observe(eid, row, event)
                    if schedule_updates.get(eid) is not before:
                        prestart_verified += 1
            except Exception as exc:
                # A calendar outage must not block finished-match settlement.
                # Shared quota exhaustion must always stop new provider calls.
                code = _provider_error_code(exc)
                provider_errors[code] = provider_errors.get(code, 0) + 1
                if type(exc).__name__ in {"SharedBudgetExhausted", "SharedBudgetUnavailable"}:
                    budget_paused = True

    checked = skipped_live = successful_history = matched_events = 0
    newly_resolved = consecutive_errors = near_attempts = unmatched = 0
    daily_attempts = daily_matches = 0
    daily_errors: dict[str, int] = {}
    next_due_id = ""
    settled_events: dict[str, dict[str, str]] = {}
    max_checks = priority_limit
    cursor = str(prior.get("next_due_id") or "")
    if priority_mode:
        recent_ordered = sorted(recent_due, key=fairness_key)
        backlog_ordered = sorted(backlog_due, key=fairness_key)
        recent_quota = min(len(recent_ordered), max(1, max_checks - 1))
        backlog_quota = min(len(backlog_ordered), max_checks - recent_quota)
        # If the current day has fewer candidates than the request budget,
        # give the unused slots back to the backlog.
        if recent_quota + backlog_quota < max_checks:
            backlog_quota = min(
                len(backlog_ordered), max_checks - recent_quota
            )
        ordered = (
            recent_ordered[:recent_quota]
            + backlog_ordered[:backlog_quota]
            + recent_ordered[recent_quota:]
            + backlog_ordered[backlog_quota:]
        )
    else:
        offset = next((i for i, (_, eid, _) in enumerate(due) if eid == cursor), 0)
        ordered = due[offset:] + due[:offset]

    # One live request can settle every due fixture, including those beyond
    # the per-event request budget of thirty.
    for _, eid, row in due:
        live_event = live_by_id.get(eid)
        if live_event is None:
            continue
        observe(eid, row, live_event)
        result = classify_finished_event(row, live_event, checked_at=now)
        if result:
            statuses[eid] = result
            pending.pop(eid, None)
            newly_resolved += 1
            settled_events[eid] = {
                "event_id": eid,
                "match_status": str(result.get("status") or ""),
                "second_set_status": _second_set_outcome(row, live_event),
                "checked_at": now.isoformat(),
            }
        else:
            skipped_live += 1

    runtime_limited = False
    if budget_paused and ordered:
        next_due_id = ordered[0][1]
    for position, (scheduled, eid, row) in enumerate(ordered):
        if budget_paused:
            break
        if eid in statuses or eid in live_by_id:
            continue
        if deadline is not None and time.monotonic() >= deadline:
            runtime_limited = True
            time_budget_exhausted = True
            next_due_id = eid
            break
        if checked >= max_checks:
            next_due_id = eid
            break
        if prefer_near and near_attempts >= max_near_checks:
            next_due_id = eid
            break
        # Leave time for one provider call and durable snapshot persistence.
        if deadline is not None and time.monotonic() + 5.0 >= deadline:
            runtime_limited = True
            time_budget_exhausted = True
            next_due_id = eid
            break
        next_due_id = ordered[(position + 1) % len(ordered)][1]

        pending_state = pending.get(eid) if isinstance(pending.get(eid), dict) else {}
        near_side = str(pending_state.get("n") or "1")
        # Participant rotation is only for the compact near route. The legacy
        # previous-match route intentionally keeps player1 semantics because
        # existing backlog snapshots/tests rely on that stable lookup path.
        primary_key = (
            "player2" if prefer_near and near_side == "2" else "player1"
        )
        secondary_key = "player1" if primary_key == "player2" else "player2"
        player_id = _player_id(row, primary_key)
        checked += 1
        previous_checked_at = ""
        if eid in pending:
            previous_checked_at = str(pending[eid].get("c") or "")
            pending[eid]["c"] = now.isoformat()
        payload = None
        near_used = False

        # Prefer one exact daily event listing over two player-near calls.
        # A single cached response can settle every pick from the same date.
        event = None
        if callable(daily_method):
            day_key = scheduled.date().isoformat()
            try:
                if day_key not in daily_cache:
                    daily_attempts += 1
                    nominal_requests += 1
                    target_ids = {
                        target_eid for target_scheduled, target_eid, _ in due
                        if target_scheduled.date() == scheduled.date()
                    }
                    try:
                        daily_cache[day_key] = daily_method(
                            scheduled.date(), target_event_ids=target_ids,
                            max_category_requests=min(8, max_near_checks),
                        )
                    except TypeError:
                        # Compatibility with older/fake providers and the
                        # pre-match odds fallback while deployments roll.
                        daily_cache[day_key] = daily_method(scheduled.date())
                daily_payload = daily_cache.get(day_key)
                event = next(
                    (candidate for candidate in _provider_rows(daily_payload)
                     if _provider_event_id(candidate) == eid),
                    None,
                )
                if event is not None:
                    daily_matches += 1
                    successful_history += 1
            except Exception as exc:
                # This route is an optimization/fallback source, not a reason to
                # degrade the worker. Quota exhaustion remains authoritative.
                if type(exc).__name__ == "SharedBudgetExhausted":
                    budget_paused = True
                    checked = max(0, checked - 1)
                    if eid in pending:
                        pending[eid]["c"] = previous_checked_at
                    next_due_id = eid
                    break
                if type(exc).__name__ == "RequestBudgetExceeded":
                    next_due_id = eid
                    break
                daily_code = _provider_error_code(exc)
                daily_errors[daily_code] = daily_errors.get(daily_code, 0) + 1
                daily_cache[day_key] = None

        if event is not None:
            observe(eid, row, event)
            consecutive_errors = 0
            matched_events += 1
            result = classify_finished_event(row, event, checked_at=now)
            if result:
                statuses[eid] = result
                pending.pop(eid, None)
                newly_resolved += 1
                settled_events[eid] = {
                    "event_id": eid,
                    "match_status": str(result.get("status") or ""),
                    "second_set_status": _second_set_outcome(row, event),
                    "checked_at": now.isoformat(),
                }
                continue
            # The exact daily schedule is authoritative for a nonterminal
            # fixture ONLY after the provider player IDs match the issued
            # prediction. Do not spend two further /near calls every 30 min
            # for a postponed/interrupted match already seen on the calendar.
            # Keep it pending: the next worker run will recheck its state.
            home = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
            away = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
            feed_ids = {_player_id(row, "player1"), _player_id(row, "player2")}
            provider_ids = {str(home.get("id") or "").strip(),
                            str(away.get("id") or "").strip()}
            if (
                "" not in feed_ids and "" not in provider_ids
                and feed_ids == provider_ids
                and _explicitly_nonterminal_status(_status_text(event))
            ):
                continue

        try:
            if prefer_near:
                if player_id in near_cache:
                    payload = near_cache[player_id]
                else:
                    if near_attempts >= max_near_checks:
                        checked -= 1
                        next_due_id = eid
                        break
                    if not callable(near_method):
                        raise RuntimeError("NearStatusRouteUnavailable")
                    near_attempts += 1
                    nominal_requests += 1
                    payload = near_method(player_id)
                    near_cache[player_id] = payload
                near_used = True
            else:
                nominal_requests += 1
                payload = provider.previous_player_matches(player_id, 0)
        except Exception as exc:
            error_code = _provider_error_code(exc)
            provider_errors[error_code] = provider_errors.get(error_code, 0) + 1
            if type(exc).__name__ == "SharedBudgetExhausted":
                budget_paused = True
                checked = max(0, checked - 1)
                if eid in pending:
                    pending[eid]["c"] = previous_checked_at
                next_due_id = eid
                break
            if (
                not prefer_near and error_code.endswith("_HTTP_404")
                and callable(near_method) and near_attempts < max_near_checks
            ):
                # Do not start a second slow provider call near the deadline.
                if deadline is not None and time.monotonic() + 5.0 >= deadline:
                    runtime_limited = True
                    time_budget_exhausted = True
                    next_due_id = eid
                    break
                # Stop repeating the known 404 route once the documented
                # near-match endpoint succeeds for one real player.
                try:
                    near_attempts += 1
                    nominal_requests += 1
                    payload = near_method(player_id)
                    near_cache[player_id] = payload
                    prefer_near = True
                    near_used = True
                except Exception as fallback_exc:
                    code = _provider_error_code(fallback_exc)
                    provider_errors[code] = provider_errors.get(code, 0) + 1
                    if type(fallback_exc).__name__ == "SharedBudgetExhausted":
                        budget_paused = True
                        checked = max(0, checked - 1)
                        if eid in pending:
                            pending[eid]["c"] = previous_checked_at
                        next_due_id = eid
                        break
                    if type(fallback_exc).__name__ == "RequestBudgetExceeded":
                        break
            elif type(exc).__name__ == "RequestBudgetExceeded":
                break

        if payload is None:
            consecutive_errors += 1
            if consecutive_errors >= 3:
                break
            continue

        consecutive_errors = 0
        successful_history += 1
        event = next(
            (candidate for candidate in _provider_rows(payload)
             if _provider_event_id(candidate) == eid),
            None,
        )
        # The near endpoint only returns the closest previous/next event for one
        # player. If player1 has already played again, the target event can fall
        # out of that tiny window even though it is still the closest event for
        # player2. Try the other participant before leaving a finished match
        # permanently pending. The existing near/request caps still bound cost.
        if event is None and near_used:
            second_player_id = _player_id(row, secondary_key)
            if (
                second_player_id
                and second_player_id != player_id
                and near_attempts < max_near_checks
                and callable(near_method)
            ):
                try:
                    if second_player_id in near_cache:
                        second_payload = near_cache[second_player_id]
                    else:
                        near_attempts += 1
                        nominal_requests += 1
                        second_payload = near_method(second_player_id)
                        near_cache[second_player_id] = second_payload
                    successful_history += 1
                    event = next(
                        (candidate for candidate in _provider_rows(second_payload)
                         if _provider_event_id(candidate) == eid),
                        None,
                    )
                except Exception as exc:
                    error_code = _provider_error_code(exc)
                    provider_errors[error_code] = provider_errors.get(error_code, 0) + 1
                    if type(exc).__name__ == "SharedBudgetExhausted":
                        budget_paused = True
                        next_due_id = eid
                        break
                    if type(exc).__name__ == "RequestBudgetExceeded":
                        next_due_id = eid
                        break
        if event is None:
            if eid in pending:
                # Rotate the primary participant for the next scheduler run.
                # This guarantees both sides eventually get queried even when
                # BLINQ_MATCH_STATUS_NEAR_MAX_CHECKS equals the due-row count,
                # without increasing the per-run API ceiling.
                pending[eid]["n"] = "1" if primary_key == "player2" else "2"
            unmatched += 1
            continue
        matched_events += 1
        observe(eid, row, event)
        result = classify_finished_event(row, event, checked_at=now)
        if result:
            statuses[eid] = result
            pending.pop(eid, None)
            newly_resolved += 1
            settled_events[eid] = {
                "event_id": eid,
                "match_status": str(result.get("status") or ""),
                "second_set_status": _second_set_outcome(row, event),
                "checked_at": now.isoformat(),
            }

    # The settlement scan already cached exact daily calendars. Reuse those
    # results for future matches at zero additional provider cost. If none was
    # fetched, spend a bounded existing-budget lookup on the current day so
    # postponements become visible BEFORE the old kickoff time passes.
    if callable(daily_method) and not budget_paused:
        candidates_by_day: dict[str, set[str]] = {}
        for eid, row in rows.items():
            if eid in statuses or not _scheduled_in_current_betting_day(row, now):
                continue
            original = _parse_time(row.get("scheduled_at") or row.get("date"))
            if original is not None:
                candidates_by_day.setdefault(original.date().isoformat(), set()).add(eid)
        day_order = sorted(candidates_by_day, key=lambda day: (-len(candidates_by_day[day]), day))
        # Only one optional new day per worker tick; exact date scans already
        # performed for settlement remain fully reusable.
        optional_calls = 0
        for day in day_order:
            if day not in daily_cache:
                if optional_calls >= 1 or deadline is None or time.monotonic() + 7 >= deadline:
                    continue
                limit = getattr(provider, "request_limit", None)
                count = getattr(provider, "request_count", 0)
                if isinstance(limit, int) and isinstance(count, int) and count + 7 >= limit:
                    break
                optional_calls += 1
                try:
                    nominal_requests += 1
                    target_day = datetime.fromisoformat(day).date()
                    try:
                        daily_cache[day] = daily_method(
                            target_day, target_event_ids=candidates_by_day[day],
                            max_category_requests=5,
                        )
                    except TypeError:
                        daily_cache[day] = daily_method(target_day)
                except Exception as exc:
                    if type(exc).__name__ == "SharedBudgetExhausted":
                        budget_paused = True
                        break
                    code = _provider_error_code(exc)
                    daily_errors[code] = daily_errors.get(code, 0) + 1
                    daily_cache[day] = None
            for event in _provider_rows(daily_cache.get(day)):
                eid = _provider_event_id(event)
                row = rows.get(eid)
                if row is not None and eid in candidates_by_day[day]:
                    observe(eid, row, event)

    request_count_after = getattr(provider, "request_count", None)
    if isinstance(request_count_before, int) and isinstance(request_count_after, int):
        provider_requests = max(0, request_count_after - request_count_before)
    else:
        provider_requests = nominal_requests

    failed_history = checked - successful_history
    degraded = (
        checked > 0 and successful_history == 0 and failed_history > 0
        and not budget_paused
    )
    # Preserve a successful near-route preference, but never store private
    # provider payloads, player names or error text.
    return {
        "schema": 1,
        "updated_at": now.isoformat(),
        "statuses": statuses,
        "tracked": len(rows),
        "due": len(due),
        "window_candidates": len(due),  # Legacy diagnostic, no window cutoff.
        "window_min_age_minutes": 0,
        "window_max_age_minutes": 0,
        "priority_mode": priority_mode,
        "betting_day_start": betting_day_start.isoformat(),
        "current_betting_day_due": len(recent_due),
        "backlog_due": len(backlog_due),
        "pending_count": len(pending),
        "pending": pending,
        "checked": checked,
        "skipped_live": skipped_live,
        "provider_requests": provider_requests,
        "time_budget_exhausted": time_budget_exhausted,
        "terminal": len(statuses),
        "newly_resolved": newly_resolved,
        "successful_history": successful_history,
        "failed_history": failed_history,
        "matched_events": matched_events,
        "provider_errors": provider_errors,
        "budget_paused": budget_paused,
        "degraded": degraded,
        "preferred_route": "near" if prefer_near else "history",
        "near_attempts": near_attempts,
        "daily_attempts": daily_attempts,
        "daily_matches": daily_matches,
        "daily_errors": daily_errors,
        "unmatched": unmatched,
        "next_due_id": next_due_id if len(due) > 1 else "",
        "runtime_limited": runtime_limited,
        "settled_events": list(settled_events.values()),
        "schedule_updates": schedule_updates,
        "schedule_verified": len(schedule_updates),
        "schedule_observations_this_run": schedule_verified_this_run,
        "prestart_checked": prestart_checked,
        "prestart_verified": prestart_verified,
        "prestart_attempts": prestart_attempts,
    }
