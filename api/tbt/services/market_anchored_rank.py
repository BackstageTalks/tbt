"""Flag-gated market-anchored Match Winner ordering. NEVER promotes a model.

Only ranks already-qualified TOP, PRIME and VALUE offers. The emergency TOP
fill is a separate, default-OFF product-policy experiment.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import os
from typing import Any, Callable, Iterable

PARAMS_VERSION = "market_anchored_rank_v1_2026-11-21"
# Research-only ATP figures supplied with candidate ZIP; historical fit and
# point-in-time opener provenance NOT independently reproduced, WTA unverified.
CAL_SLOPE = 1.102
CAL_INTERCEPT = -0.009
W_MARKET = 0.8
CLIP_LO, CLIP_HI = 0.01, 0.99

MODE_MODEL = "model"
MODE_MARKET = "market_anchored"
ENV_RANK = "TBT_RANK_SOURCE"
ENV_FILL = "TBT_TOP_EMERGENCY_FILL"
ENV_TOP_SIDE = "TBT_TOP_REQUIRE_MARKET_SIDE"
TOP_REJECT_REASON = "market_favours_opponent"
EMERGENCY_MIN_FAIR = 0.50
EMERGENCY_MIN_MODEL_NO_FAIR = 0.55
EMERGENCY_TIER = "emergency_fill"


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _logit(x: float) -> float:
    x = min(max(x, CLIP_LO), CLIP_HI)
    return math.log(x / (1.0 - x))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _ts(value: Any) -> datetime | None:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if out.tzinfo is None:
        return None
    return out.astimezone(timezone.utc)


def rank_mode(env: dict[str, str] | None = None) -> str:
    """Default to the champion's unchanged model ordering."""
    raw = (os.environ if env is None else env).get(ENV_RANK, "")
    return MODE_MARKET if str(raw).strip().lower() == MODE_MARKET else MODE_MODEL


def emergency_fill_enabled(env: dict[str, str] | None = None) -> bool:
    raw = (os.environ if env is None else env).get(ENV_FILL, "")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def calibrated_market(fair: float) -> float:
    """Unverified ATP market-only research transform, never live model p."""
    return _sigmoid(CAL_SLOPE * _logit(fair) + CAL_INTERCEPT)


def valid_prestart_fair(card: dict[str, Any]) -> float | None:
    """Use market fair only when quote has independent pre-start capture time."""
    betting = card.get("betting") if isinstance(card.get("betting"), dict) else {}
    fair = _num(card.get("fair_implied_probability"))
    if fair is None:
        fair = _num(betting.get("fair_implied_probability"))
    if fair is None or not 0.0 < fair < 1.0:
        return None
    start = _ts(card.get("scheduled_at"))
    captured = _ts(betting.get("captured_at"))
    if start is None or captured is None or captured >= start:
        return None
    return fair


def compute_rank_probability(card: dict[str, Any]) -> tuple[float, str]:
    """(rank, source). Invalid market evidence gets pure model-p fallback."""
    model_p = _num(card.get("probability")) or 0.0
    fair = valid_prestart_fair(card)
    if fair is None or not 0.0 < model_p < 1.0:
        return model_p, "model_fallback"
    z = W_MARKET * _logit(calibrated_market(fair)) + (1.0 - W_MARKET) * _logit(model_p)
    return _sigmoid(z), "market_anchored"


def annotate_rank_probability(card: dict[str, Any]) -> dict[str, Any]:
    value, source = compute_rank_probability(card)
    card["rank_probability"] = value
    card["rank_source"] = source
    card["rank_params_version"] = PARAMS_VERSION
    return card


def rank_value(card: dict[str, Any]) -> float:
    """Use candidate score only when explicitly enabled and already annotated."""
    if rank_mode() == MODE_MARKET:
        value = _num(card.get("rank_probability"))
        if value is not None:
            return value
    return _num(card.get("probability")) or 0.0


def emergency_eligible(card: dict[str, Any]) -> bool:
    """Independent TOP emergency-fill experiment (not approved for activation)."""
    model_p = _num(card.get("probability")) or 0.0
    fair = valid_prestart_fair(card)
    if fair is not None:
        return fair >= EMERGENCY_MIN_FAIR and model_p >= 0.5
    return model_p >= EMERGENCY_MIN_MODEL_NO_FAIR


def emergency_fill(
    selected: list[dict[str, Any]],
    pool: Iterable[dict[str, Any]],
    *,
    minimum: int,
    identity: Callable[[dict[str, Any]], str],
    rank_key: Callable[[dict[str, Any]], Any],
) -> list[dict[str, Any]]:
    """Optional TOP floor supplement; untouched when emergency flag is off."""
    out = list(selected)
    if not emergency_fill_enabled() or len(out) >= int(minimum):
        return out
    used = {identity(card) for card in out}
    for card in sorted((c for c in pool if emergency_eligible(c)),
                       key=rank_key, reverse=True):
        ident = identity(card)
        if not ident or ident in used:
            continue
        tagged = dict(card)
        tagged["selection_tier"] = EMERGENCY_TIER
        tagged["emergency_fill"] = True
        out.append(tagged)
        used.add(ident)
        if len(out) >= int(minimum):
            break
    return out

def top_require_market_side_enabled(env: dict[str, str] | None = None) -> bool:
    """Separate opt-in TOP market-side veto, default OFF."""
    raw = (os.environ if env is None else env).get(ENV_TOP_SIDE, "")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def top_market_side_violation(card: dict[str, Any]) -> bool:
    """Veto only a TOP underdog supported by genuine pre-start fair.

    Missing/invalid quote cannot prove disagreement and never vetoes. This
    optional rule changes TOP eligibility; it is not part of rank ordering.
    """
    if not top_require_market_side_enabled():
        return False
    fair = valid_prestart_fair(card)
    return fair is not None and fair < 0.5
