"""Locally statistically grounded ACES working odds (1.60–1.80).

The approved range comes from local statistical analysis: these are local
statistical odds, NOT placeholders. The exact cents within the range are
assigned deterministically by frozen event/selection identity, not calculated
as a separate bookmaker or per-pick probability estimate. Never present them
as externally quoted bookmaker odds. Keep the source feed, API evidence and
immutable issuance ledger intact. Web, Telegram and statistical presentation
reuse this same price basis.
"""
from __future__ import annotations

from typing import Mapping, Any
from datetime import datetime, timezone
from math import isfinite

PRICE_BASIS = "local_aces_statistical_v1"


def working_ace_odds(row: Mapping[str, Any], *, selection_id: str | None = None) -> float | None:
    """1.60–1.80 inclusive in cent increments, stable per event and selection.

    Hash UTF-16 code units to match the JavaScript implementation exactly.
    No mutable random state, so a reload/retry cannot change a frozen pick.
    """
    if not isinstance(row, Mapping):
        return None
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    event = str(row.get("event_id") or row.get("match_id") or row.get("id") or "")
    # The frozen Telegram contract uses betting.selection_id first.
    selection = str(selection_id or betting.get("selection_id") or row.get("selection_id")
                    or row.get("winner_id") or row.get("pick") or row.get("selection") or "")
    if not event and not selection:
        return None
    identity = event + "|" + selection
    encoded = identity.encode("utf-16-le", errors="surrogatepass")
    hash_value = 2166136261
    for index in range(0, len(encoded), 2):
        code = encoded[index] | (encoded[index + 1] << 8)
        hash_value ^= code
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return (160 + hash_value % 21) / 100

# Provider prices are already matched to the exact Aces contract by the
# existing API Pro -> PropLine enrichment. Only consume verified evidence.
def verified_ace_odds(row: Mapping[str, Any]) -> float | None:
    if not isinstance(row, Mapping) or str(row.get("market") or "aces").lower() != "aces":
        return None
    if (row.get("price_status") != "priced_projection"
            or row.get("odds_contract_version") != "ace_df_real_api_v1"
            or not row.get("captured_at")):
        return None
    try:
        provider = int(row.get("provider_id") or 0)
        raw = row.get("odds")
        if isinstance(raw, bool):
            return None
        odds = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    from math import isfinite
    if not isfinite(odds) or not 1.50 <= odds <= 100:
        return None
    # Until independently bettable Aces API quotes are reliable, treat the
    # legacy exact-2.00 feed value as an unverified placeholder, regardless
    # of its old "priced_projection" marker. This is a permanent fallback
    # for future offers; preserve raw provider prices and immutable ledgers.
    if odds == 2.0:
        return None
    source = str(row.get("odds_source") or "").lower()
    valid = ((source == "rapidapi" and provider == 1)
             or (source == "propline" and provider == 2
                 and bool(row.get("odds_bookmaker")))
             or (source == "moviodds" and provider == 3
                 and row.get("odds_bookmaker") == "bet365"))
    if not valid:
        return None
    if row.get("price_contract") == "player_total_ou":
        if str(row.get("ou_side") or "").lower() not in ("over", "under"):
            return None
        try:
            line = float(row.get("market_line"))
            if not isfinite(line) or line < 0:
                return None
        except (TypeError, ValueError, OverflowError):
            return None
    return odds


def selected_ace_odds(row: Mapping[str, Any], *,
                      selection_id: str | None = None) -> tuple[float | None, bool]:
    """Provider quote first; otherwise stable local 1.60-1.80 working price."""
    actual = verified_ace_odds(row)
    if actual is not None:
        return actual, True
    return working_ace_odds(row, selection_id=selection_id), False



# The previous 1.50-1.70 Results-only formula is historical before the
# 2026-11-01 06:00 Europe/Bratislava betting-day boundary. New Aces without
# an exact provider contract use this separately approved local price basis.
NEW_ACES_START_UTC = datetime(2026, 11, 1, 5, tzinfo=timezone.utc)


def eligible_local_ace_projection(row: Mapping[str, Any]) -> bool:
    """Publish only model-qualified new Aces projections, never fake provider odds.

    The immutable publication retains odds=None / projection_only. The UI and
    Telegram independently compute the stable statistical display value.
    """
    if not isinstance(row, Mapping):
        return False
    if str(row.get("market") or "").lower() != "aces":
        return False
    if row.get("price_status") != "projection_only" or row.get("odds") is not None:
        return False
    if row.get("projection_model") != "ace-count-projection-v4":
        return False
    p1 = row.get("player1") if isinstance(row.get("player1"), Mapping) else {}
    p2 = row.get("player2") if isinstance(row.get("player2"), Mapping) else {}
    if not row.get("event_id") or str(row.get("selection_id") or "") not in {
        str(p1.get("id") or ""), str(p2.get("id") or ""),
    }:
        return False
    if not row.get("selection_id"):
        return False
    try:
        scheduled = datetime.fromisoformat(str(row.get("scheduled_at") or "").replace("Z", "+00:00"))
        projection = float(row.get("projection"))
        opponent = float(row.get("opponent_projection"))
        confidence = float(row.get("projection_confidence"))
    except (TypeError, ValueError, OverflowError):
        return False
    return (
        scheduled.tzinfo is not None
        and scheduled.astimezone(timezone.utc) >= NEW_ACES_START_UTC
        and all(isfinite(value) for value in (projection, opponent, confidence))
        and projection >= 0 and opponent >= 0
        and 0.60 <= confidence <= 1.0
        and working_ace_odds(row) is not None
    )
