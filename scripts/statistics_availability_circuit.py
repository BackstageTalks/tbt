"""Fail-safe, evidence-based pause for an unproductive paid statistics route.

This is an in-run *request selection* guard, not a CDB writer or a provider
quota. It never changes the model, source identity, retry markers or stored
statistics. The existing native importer still owns all write/read-back gates.
"""
from __future__ import annotations

from collections import Counter, deque


class StatisticsAvailabilityCircuit:
    """Stop only after broad, recent, paid, independently empty observations.

    A cohort with no statistics is not sufficient evidence of a provider-wide
    outage. Require both tours and three materially sampled tour/year cohorts.
    Only paid observations count; cache hits and unspent allocations do not.
    """

    WINDOW = 160
    MIN_PAID_MATCHES = 120
    MIN_PAID_ATTEMPTS = 120
    MIN_COHORT_MATCHES = 8
    MIN_COHORTS = 3
    MIN_TOURS = 2
    MIN_EMPTY_FRACTION = 0.95
    EMPTY_REASONS = frozenset({
        "empty_whole_match_statistics", "no_supported_fields",
        "missing_unambiguous_all_period",
    })

    def __init__(self):
        self.samples = deque(maxlen=self.WINDOW)
        self.paid_attempts_observed = 0
        self.paid_matches_observed = 0
        self.tripped = False
        self.trigger = None

    def observe(self, match, status: str, paid_attempts: int, value_change: dict) -> bool:
        if self.tripped:
            return True
        if type(paid_attempts) is not int or paid_attempts < 0:
            raise ValueError("Paid attempt count must be a nonnegative integer")
        if not paid_attempts:
            return False
        added = value_change.get("new_statistic_values", 0)
        if type(added) is not int or added < 0:
            raise ValueError("Canonical gain must be a nonnegative integer")
        tour = str(match.tour or "unknown").strip().lower()
        year = int(match.scheduled_at.year)
        marker = (match.provider_payload or {}).get("_tbt_statistics")
        reason = marker.get("reason") if isinstance(marker, dict) else None
        empty = status == "unavailable" and reason in self.EMPTY_REASONS
        self.samples.append((tour, year, paid_attempts, bool(empty), added))
        self.paid_matches_observed += 1
        self.paid_attempts_observed += paid_attempts

        # Check a bounded *recent* window, so previously productive hours do
        # not conceal a now-empty route, and old empty hours do not veto recovery.
        window = list(self.samples)[-self.MIN_PAID_MATCHES:]
        if len(window) < self.MIN_PAID_MATCHES:
            return False
        attempts = sum(row[2] for row in window)
        cohorts = Counter((row[0], row[1]) for row in window)
        eligible_cohorts = {key for key, count in cohorts.items()
                            if count >= self.MIN_COHORT_MATCHES}
        tours = {key[0] for key in eligible_cohorts if key[0] in {"atp", "wta"}}
        empty_matches = sum(int(row[3]) for row in window)
        new_fields = sum(row[4] for row in window)
        if (attempts >= self.MIN_PAID_ATTEMPTS
                and len(eligible_cohorts) >= self.MIN_COHORTS
                and len(tours) >= self.MIN_TOURS
                and new_fields == 0
                and empty_matches / len(window) >= self.MIN_EMPTY_FRACTION):
            self.tripped = True
            self.trigger = {
                "reason": "cross_tour_paid_statistics_unavailable",
                "recent_paid_matches": len(window),
                "recent_paid_attempts": attempts,
                "recent_unavailable_matches": empty_matches,
                "recent_new_canonical_fields": new_fields,
                "sampled_cohorts": len(eligible_cohorts),
                "sampled_tours": len(tours),
                "scope": "current_high_yield_statistics_run_only",
            }
        return self.tripped

    def summary(self) -> dict:
        return {
            "schema": 1,
            "tripped": self.tripped,
            "paid_matches_observed": self.paid_matches_observed,
            "paid_attempts_observed": self.paid_attempts_observed,
            "window_matches": min(len(self.samples), self.MIN_PAID_MATCHES),
            "trigger": self.trigger,
            "policy": ("Paid, recent, cross-tour observations; no change to "
                       "CDB import, shared quota, manual/BP modes or external cron"),
        }
