"""Read-only BlinQ user-statistics price for the *Most Aces* contract.

The user-approved 1.50–1.70 price band is a local model presentation value,
not a bookmaker offer, a made-up API response or an implied ROI contract.
The separate ESÁ player-total Over/Under price remains unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import math
from typing import Mapping, Any

PRICE_BASIS = "blinq_user_most_aces_confidence_band_v1"
MIN_PRICE = 1.50
MAX_PRICE = 1.70
MIN_CONFIDENCE = 0.60
MAX_CONFIDENCE = 0.93


def _valid_subject(row: Mapping[str, Any], player_id: str) -> bool:
    sides = (row.get("player1"), row.get("player2"))
    if not all(isinstance(side, Mapping) and side.get("id") and side.get("name")
               for side in sides):
        return False
    ids = [str(side["id"]) for side in sides]
    return ids[0] != ids[1] and player_id in ids


def statistical_most_aces_odds(
    row: Mapping[str, Any], *, ball_player_id: str | None = None,
) -> float | None:
    """Conservative monotonic mapping of frozen CDB-derived confidence to 1.50–1.70.

    For the ordinary Most Aces pick, selection_id is the selected player's ID.
    For Telegram's ESÁ tennis-ball marker, pass the *independently verified*
    ball player ID. Never reuse the potentially different Over/Under selection.
    """
    if not isinstance(row, Mapping):
        return None
    market = str(row.get("market") or "").strip().lower()
    if market not in {"most_aces", "aces"}:
        return None
    if market == "most_aces":
        if ball_player_id is not None:
            return None
        if (row.get("price_contract") != "player_superiority"
                or row.get("price_status") != "projection_only"
                or row.get("odds") is not None):
            return None
        player_id = str(row.get("selection_id") or "")
    else:
        # The caller must have already reconciled the visible ball marker.
        if ball_player_id is None:
            return None
        player_id = str(ball_player_id)
    if not player_id or not row.get("event_id") or not _valid_subject(row, player_id):
        return None
    if str(row.get("projection_model") or "") != "ace-count-projection-v4":
        return None
    try:
        scheduled = datetime.fromisoformat(str(row["scheduled_at"]).replace("Z", "+00:00"))
        projection = float(row["projection"])
        opponent = float(row["opponent_projection"])
        confidence = float(row["projection_confidence"])
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    if (scheduled.tzinfo is None
            or not all(math.isfinite(x) for x in (projection, opponent, confidence))
            or projection <= opponent or opponent < 0
            or not MIN_CONFIDENCE <= confidence <= MAX_CONFIDENCE):
        return None
    # A larger calibrated superiority confidence implies a shorter local price.
    # This is a bounded quote within the owner's range, not 1/p or an EV claim.
    fraction = (confidence - MIN_CONFIDENCE) / (MAX_CONFIDENCE - MIN_CONFIDENCE)
    return round(MAX_PRICE - (MAX_PRICE - MIN_PRICE) * fraction + 1e-10, 2)


def verified_api_pro_most_aces_odds(row: Mapping[str, Any]) -> float | None:
    """Only an explicitly source-marked exact provider-1 Most Aces player quote.

    Does not recover prices from O/U, and never guesses a bookmaker source.
    The source importer is responsible for confirming both offered market sides.
    """
    if (not isinstance(row, Mapping)
            or str(row.get("market") or "") != "most_aces"
            or str(row.get("price_contract") or "") != "player_superiority"
            or row.get("price_status") != "priced_projection"
            or row.get("odds_source") != "rapidapi"
            or row.get("provider_id") != 1
            or not row.get("captured_at")
            or not _valid_subject(row, str(row.get("selection_id") or ""))):
        return None
    name = str(row.get("odds_market_name") or "").lower()
    if (not "ace" in name
            or not any(word in name for word in ("most", "more", "winner", "higher"))
            or any(word in name for word in ("total", "over", "under", "handicap", "set", "period"))):
        return None
    try:
        captured = datetime.fromisoformat(str(row["captured_at"]).replace("Z", "+00:00"))
        scheduled = datetime.fromisoformat(str(row["scheduled_at"]).replace("Z", "+00:00"))
        quote = float(row["odds"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if (captured.tzinfo is None or scheduled.tzinfo is None
            or captured >= scheduled or not math.isfinite(quote)
            or not 1.01 <= quote <= 100):
        return None
    return round(quote, 3)


def annotate_most_aces_offer(feed: dict) -> dict:
    """Decorate only the authorized *current* offer; leave results/ledger immutable."""
    if not isinstance(feed, dict) or not isinstance(feed.get("ace_picks"), list):
        return feed
    result = dict(feed)
    out = []
    for source in feed["ace_picks"]:
        if not isinstance(source, dict) or source.get("market") != "most_aces":
            out.append(source)
            continue
        row = deepcopy(source)
        row.pop("statistical_more_aces_odds", None)
        row.pop("statistical_more_aces_price_basis", None)
        price = statistical_most_aces_odds(row)
        if price is not None:
            row["statistical_more_aces_odds"] = price
            row["statistical_more_aces_price_basis"] = PRICE_BASIS
        out.append(row)
    result["ace_picks"] = out
    return result
