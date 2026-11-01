"""Stable internal Aces working price for the locally calibrated line.

The value is an operative price assumption (not an external bookmaker quote).
Keep the existing feed/issuance provider price intact for auditability.  All
current Aces consumer calculations use the same deterministic price basis.
"""
from __future__ import annotations

from typing import Mapping, Any

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

