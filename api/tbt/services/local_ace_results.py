"""Read-only flat-unit valuation of BlinQ's approved frozen local Aces prices.

The 1.60-1.80 local price is a first-class Results/ROI quote from the Nov 1
betting-day cutover. Keep its source provenance and original ledger immutable.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

_CUTOVER = datetime(2026, 11, 1, 5, tzinfo=timezone.utc)
_BASIS = "local_aces_statistical_v1"


def local_ace_result_odds(row: dict, publication: dict) -> float | None:
    if not isinstance(row, dict) or not isinstance(publication, dict):
        return None
    if str(publication.get("market") or "").lower() != "aces":
        return None
    if str(publication.get("price_contract") or "").lower() != "player_total_ou":
        return None
    if str(publication.get("ou_side") or "").lower() not in {"over", "under"}:
        return None
    try:
        line = float(publication.get("market_line"))
        issued = datetime.fromisoformat(str(publication["issued_at"]).replace("Z", "+00:00"))
        scheduled = datetime.fromisoformat(str(row["scheduled_at"]).replace("Z", "+00:00"))
    except (ValueError, TypeError, KeyError, OverflowError):
        return None
    if (not math.isfinite(line) or line < 0 or issued.tzinfo is None
            or scheduled.tzinfo is None or issued < _CUTOVER
            or issued >= scheduled or publication.get("excluded_reason")):
        return None
    status = str(publication.get("price_status") or "").lower()
    if status not in {"priced_projection", "projection_only"}:
        return None
    # A verified independent provider quote takes precedence.
    if (publication.get("odds_contract_version") == "ace_df_real_api_v1"
            and publication.get("captured_at")
            and publication.get("provider_id")):
        return None
    event = str(row.get("event_id") or row.get("match_id") or row.get("id") or "")
    selection = str(publication.get("selection_id") or "")
    if not event or not selection:
        return None
    if publication.get("price_basis") == _BASIS:
        try:
            issued_quote = float(publication.get("odds"))
        except (TypeError, ValueError, OverflowError):
            issued_quote = float("nan")
        if math.isfinite(issued_quote) and 1.60 <= issued_quote <= 1.80:
            return issued_quote
    # Only the frozen player O/U contract is eligible. Derive the same stable
    # local price used on the published Aces card, never the raw 2.00 value.
    if status == "priced_projection" and publication.get("price_basis") not in {_BASIS, None, ""}:
        return None
    encoded = (event + "|" + selection).encode("utf-16-le", errors="surrogatepass")
    h = 2166136261
    for i in range(0, len(encoded), 2):
        h ^= encoded[i] | (encoded[i + 1] << 8)
        h = (h * 16777619) & 0xFFFFFFFF
    return (160 + h % 21) / 100
