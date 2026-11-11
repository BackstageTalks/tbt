"""TOP evidence and competition classification. Guards are not a backtest claim.

No model fitting, probability rewriting, outcome access or ace-price changes.
Competition must be explicit: engine ``tour=ATP`` includes male ITF/UTR too.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re

POLICY = "priority_tours_top_v20"
# Owner-authorized 65% floor applies to ATP/WTA first, then verified ITF/Challenger fallback.
MIN_PROBABILITY = .65
# TOP only: ITF fallback prices are capped, ATP/WTA and Challenger unchanged.
MIN_ODDS = 1.50
ITF_MAX_ODDS = 1.70
# Temporary TOP-only evidence hold; not an odds ceiling or calibrated profitability claim.
TOP_MARKET_OUTSIDER_CONFLICT_GAP = .25


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def competition_group(row):
    """Fail closed on ambiguous levels; never treat gender/tour as competition."""
    level = str(row.get("competition") or row.get("tournament_level") or "").strip().lower()
    level = " ".join(level.replace("_", " ").replace("-", " ").split())
    name = str(row.get("tournament") or "").lower()
    combined = level + " " + name
    if "itf" in combined or "futures" in combined:
        return "ITF"
    if "utr" in combined:
        return "UTR"
    if "challenger" in combined:
        return "Challenger"
    if re.search(r"wta\s*125", combined):
        return "WTA 125"
    if any(word in combined for word in ("doubles", "wheelchair", "junior", "exhibition")):
        return "other"
    if level in {"atp", "atp 250", "atp 500", "atp 1000", "masters 1000", "atp finals"}:
        return "ATP" if str(row.get("tour") or "").upper() == "ATP" else "unknown"
    if level in {"wta", "wta 250", "wta 500", "wta 1000", "wta finals"}:
        return "WTA" if str(row.get("tour") or "").upper() == "WTA" else "unknown"
    if level in {"grand slam", "grand slams"}:
        tour = str(row.get("tour") or "").upper()
        return tour if tour in {"ATP", "WTA"} else "unknown"
    return "unknown"


def is_itf_m15_m25(row):
    """Exact ITF M15/M25 label guard; a generic ATP gender tag is insufficient."""
    if competition_group(row) != "ITF":
        return False
    labels = " ".join(str(row.get(key) or "") for key in (
        "competition", "tournament_level", "tournament"
    )).lower()
    return bool(re.search(r"(?<![a-z0-9])m[\s-]?(?:15|25)(?![a-z0-9])", labels))




def qualified_itf_w35plus_evidence(card):
    """Fail-closed: ITF women W35+ with paired PIT stats on overall and surface.

    A generic WTA tour/gender label is not grade evidence. M-level men's ITF,
    unknown/wrong ITF grades and missing pre-match feature flags cannot enter TOP.
    """
    if competition_group(card) != "ITF":
        return False
    labels = " ".join(str(card.get(k) or "") for k in (
        "competition", "tournament_level", "tournament")).lower()
    if not re.search(r"(?<![a-z0-9])w[\s-]?(?:35|50|60|75|80|100)(?![a-z0-9])", labels):
        return False
    q = card.get("quality") if isinstance(card.get("quality"), dict) else {}
    ev = q.get("feature_evidence") if isinstance(q.get("feature_evidence"), dict) else {}
    return (ev.get("serve_return_known_both") is True
            and ev.get("surface_serve_return_known_both") is True)


def unverified_top_market_outsider(card):
    """Hold severe ITF TOP-only market/model favorite inversion for review.

    Requires the original two-way, no-vig price evidence. A high-priced pick
    which the bookmaker still favors is not automatically rejected; nor do
    we rewrite the model or previously issued selections. Re-entry requires
    independent prospective calibration, not one favorable outcome.
    """
    bet = card.get("betting") if isinstance(card.get("betting"), dict) else {}
    # Scope this temporary constraint to ITF. ATP/WTA/Challenger existing
    # validated and explicitly authorized policies remain unchanged.
    if competition_group(card) != "ITF" or bet.get("market") != "match_winner":
        return False
    public = number(card.get("probability"))
    fair = number(bet.get("fair_implied_probability"))
    return bool(public is not None and .5 <= public < 1
                and fair is not None and 0 < fair < .5
                and public - fair > TOP_MARKET_OUTSIDER_CONFLICT_GAP + 1e-12)


def rejection_reasons(card, *, min_probability=.65, min_depth=.80, min_surface=5, min_odds=1.50):
    from .price_integrity import extreme_winner_price_inversion, unsubstantiated_high_confidence_winner

    reasons = []
    group = competition_group(card)
    if group not in {"ATP", "WTA", "Challenger", "ITF"}:
        reasons.append("competition_not_approved")
    # Temporary TOP-only hold pending independently graded M15/M25 calibration.
    # This changes neither issued selections nor VALUE/PRIME or model probabilities.
    if is_itf_m15_m25(card):
        reasons.append("itf_m15_m25_top_hold_pending_calibration")
    if group == "ITF" and not qualified_itf_w35plus_evidence(card):
        reasons.append("itf_top_requires_verified_w35plus")
    if unverified_top_market_outsider(card):
        reasons.append("top_unverified_market_outsider_conflict")
    if card.get("prediction_family") == "doubles":
        reasons.append("not_singles")
    bet = card.get("betting") if isinstance(card.get("betting"), dict) else {}
    players = [card.get(side) if isinstance(card.get(side), dict) else {} for side in ("player1", "player2")]
    ids = [str(player.get("id") or "") for player in players]
    selection = str(bet.get("selection_id") or "")
    if (not str(card.get("event_id") or "").strip() or not all(ids) or ids[0] == ids[1]
            or selection not in ids or selection != str(card.get("winner_id") or "")
            or bet.get("market") != "match_winner"):
        reasons.append("invalid_selection_identity")
    ps = [number(player.get("probability")) for player in players]
    raw, public = number(bet.get("model_probability")), number(card.get("probability"))
    depth, odds = number(card.get("data_depth")), number(card.get("odds"))
    valid = (all(p is not None and 0 < p < 1 for p in ps)
             and abs(sum(ps) - 1) <= .005 and raw is not None and .5 <= raw < 1
             and public is not None and .5 <= public < 1 and selection in ids
             and abs(ps[ids.index(selection)] - raw) <= .005
             and depth is not None and 0 <= depth <= 1
             and abs(public - (.5 + (raw - .5) * depth)) <= .005)
    if not valid:
        reasons.append("inconsistent_probability_evidence")
    # Same candidate floor across approved groups; selection priority is
    # handled separately. Count-depth does NOT establish calibrated reliability.
    if public is None or public < max(MIN_PROBABILITY, min_probability):
        reasons.append("probability_below_fixed_floor")
    if group == "ITF" and public is not None and public <= .65:
        reasons.append("itf_probability_not_above_65")
    if depth is None or not min_depth <= depth <= 1:
        reasons.append("insufficient_data_depth")
    quality = card.get("quality") if isinstance(card.get("quality"), dict) else {}
    counts = [number((quality.get(side) or {}).get("surface_matches"))
              if isinstance(quality.get(side), dict) else None for side in ("player1", "player2")]
    if any(n is None or n < min_surface for n in counts):
        reasons.append("insufficient_surface_history")
    if odds is None or odds < max(MIN_ODDS, min_odds):
        reasons.append("missing_or_low_odds")
    if group == "ITF" and odds is not None and odds > ITF_MAX_ODDS + 1e-12:
        reasons.append("itf_odds_above_1_70")
    start, created, captured = (timestamp(card.get("scheduled_at")),
                                timestamp(card.get("created_at")), timestamp(bet.get("captured_at")))
    if not start or not created or created >= start or not str(card.get("model_version") or "").strip():
        reasons.append("missing_prematch_prediction_evidence")
    if not start or not captured or captured >= start:
        reasons.append("missing_prematch_quote_evidence")
    if extreme_winner_price_inversion(public, odds) or unsubstantiated_high_confidence_winner(card):
        reasons.append("price_integrity_quarantine")
    return reasons
