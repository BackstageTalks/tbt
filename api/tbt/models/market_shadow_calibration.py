"""Opt-in research-only Match Winner market anchor. NEVER wired into serving.

Parameters are learned outside this module on earlier, completed matches.
A two-way pre-start market quote is mandatory to apply an anchor; every
unverifiable or missing quote falls back to the original model probability.
Neither outcomes nor post-start quotes are features in this function.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any

import numpy as np
from scipy.special import expit, logit


@dataclass(frozen=True)
class MarketShadowParams:
    """Frozen research coefficients for the symmetric market-aware adapter."""

    a: float
    b: float
    c: float = 0.0

    def __post_init__(self) -> None:
        if not all(math.isfinite(float(v)) for v in (self.a, self.b, self.c)):
            raise ValueError("Market shadow coefficients must be finite")
        if self.a < 0 or self.b < 0:
            raise ValueError("Market shadow must be non-decreasing in model and market")
        if self.a == 0 and self.b == 0:
            raise ValueError("Market shadow requires an informative input")


def _as_clock(value: Any) -> datetime | None:
    """Parse strictly timezone-aware instants, never infer a missing timezone."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _vector(value: Any, n: int, *, label: str) -> list[Any]:
    """Accept scalar or exact-length timestamp list; no silent broadcasting of mismatched rows."""
    if isinstance(value, (list, tuple, np.ndarray)):
        data = list(value)
        if len(data) != n:
            raise ValueError(f"{label} timestamps do not match prediction rows")
        return data
    return [value] * n


def blend_with_market(
    p_model: Any,
    p_fair: Any,
    params: MarketShadowParams,
    *,
    captured_at: Any = None,
    issued_at: Any = None,
    scheduled_at: Any = None,
    return_fallback_mask: bool = False,
) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    """Return symmetric probabilities, with a reportable fallback mask.

    A usable price must have independently provided, timezone-aware timestamps
    satisfying captured_at <= issued_at < scheduled_at and captured_at < start.
    Missing/invalid market time evidence or fair -> original clipped model p.

    The ordinary logistic intercept makes a selected-side probability
    non-symmetric. We use the average of both player orientations instead:
      q = 0.5 * (sigmoid(z + c) + sigmoid(z - c)),
      z = a*logit(p_model) + b*logit(p_fair).
    That guarantees q(p,f)+q(1-p,1-f)=1 and monotonicity for a,b>=0.
    The form is intentionally different from unconstrained research M4:
    its predictive scores must be measured separately before shadow rollout.
    """
    if not isinstance(params, MarketShadowParams):
        raise TypeError("Expected frozen MarketShadowParams")
    raw=np.atleast_1d(np.asarray(p_model, dtype=float))
    if raw.ndim != 1 or not np.isfinite(raw).all():
        raise ValueError("Model probabilities must be a finite 1D array")
    p=np.clip(raw, .01, .99)
    if p_fair is None:
        fair=np.full(len(p),np.nan)
    else:
        fair=np.atleast_1d(np.asarray(p_fair, dtype=float))
    if fair.shape != p.shape:
        raise ValueError("Fair probability shape mismatch")
    good=np.isfinite(fair) & (fair > 0) & (fair < 1)
    result=p.copy()
    if good.any() and all(v is not None for v in (captured_at, issued_at, scheduled_at)):
        captures=_vector(captured_at,len(p),label='captured_at')
        issuances=_vector(issued_at,len(p),label='issued_at')
        starts=_vector(scheduled_at,len(p),label='scheduled_at')
        for i in np.flatnonzero(good):
            cap,iss,start=(_as_clock(captures[i]),_as_clock(issuances[i]),_as_clock(starts[i]))
            good[i]=bool(cap is not None and iss is not None and start is not None
                          and cap<=iss<start and cap<start)
        if good.any():
            z=params.a*logit(p[good])+params.b*logit(np.clip(fair[good],.01,.99))
            result[good]=np.clip(.5*(expit(z+params.c)+expit(z-params.c)),.01,.99)
    else:
        good[:]=False
    fallback=~good
    if return_fallback_mask:
        return result,fallback
    return result
