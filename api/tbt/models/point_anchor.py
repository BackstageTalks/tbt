"""Anchor the service-point split to the frozen candidate after adjusting its mean."""
from functools import lru_cache
from math import isfinite

from .point_rules import STANDARD
from .point_simulation import _winner_only

CANDIDATE = "blinq-candidate-frozen-45525499354-1"
MODEL_SHA = "f94e8feb5e5ef2726dd4409f623e14cda4383c9df20f76684385b2403c766acc"


@lru_cache(maxsize=8192)
def anchored_rates(mean, candidate, best_of, deciding, rules=STANDARD):
    if not isfinite(mean) or not .01 < mean < .99 or not 0 < candidate < 1:
        raise ValueError("Invalid service mean or candidate probability")
    if candidate == .5:
        return mean, mean
    target = max(candidate, 1 - candidate)
    lo, hi = 0., min(mean - .010001, .989999 - mean)
    for _ in range(22):
        delta = (lo + hi) / 2
        points = (mean + delta, mean - delta)
        estimated = _winner_only(points, best_of, deciding, rules)
        if abs(estimated - target) < .00005:
            break
        if estimated < target:
            lo = delta
        else:
            hi = delta
    if abs(estimated - target) > .005:
        raise ValueError("Candidate outside feasible fixed-sum range")
    return points if candidate > .5 else points[::-1]


def calibrated_mean(mean, offset):
    return max(.45, min(.80, mean + offset))
