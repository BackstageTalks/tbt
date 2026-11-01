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
    selection = str(selection_id or row.get("selection_id") or betting.get("selection_id")
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
