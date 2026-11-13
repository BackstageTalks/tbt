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
    # Only a prior *independently CDB-verified* cross-tour zero-gain sample
    # allows a short recovery check. First-time routes keep the full guard.
    PRIOR_RECHECK_MATCHES = 24
    PRIOR_MIN_COHORT_REQUESTS = 24
    PRIOR_MIN_TOTAL_REQUESTS = 100
    EMPTY_REASONS = frozenset({
        "empty_whole_match_statistics", "no_supported_fields",
        "missing_unambiguous_all_period",
    })

    def __init__(self, *, verified_prior=None, eligible_cohorts=None):
        self.samples = deque(maxlen=self.WINDOW)
        self.paid_cohort_counts = Counter()
        self.paid_attempts_observed = 0
        self.paid_matches_observed = 0
        self.tripped = False
        self.trigger = None
        self._run_had_gain = False
        # Already checked by adaptive_verified_prior.validated_prior. This
        # is evidence from the immediately preceding *successful CDB
        # read-back*, not speculative candidate or cache counts. Distinct
        # tour/season keys prevent ace_df and serve_return double-counting.
        prior_eligible = {}
        for name, sample in (verified_prior or {}).items():
            tour, year, _kind = name.split(":")
            paid = int(sample["api_requests"])
            new_fields = int(sample["new_fields"])
            new_ready = int(sample["full_serve_return_rows"])
            if (tour in {"atp", "wta"} and paid >= self.PRIOR_MIN_COHORT_REQUESTS
                    and new_fields == 0 and new_ready == 0):
                prior_eligible[(tour, int(year))] = (
                    prior_eligible.get((tour, int(year)), 0) + paid)
        prior_tours = {key[0] for key in prior_eligible}
        # No early exit when today's *eligible* CDB queue has other seasons
        # that might yield usable values. The initial proof applies only
        # when all currently eligible tour/year groups were already sampled.
        current = (frozenset(eligible_cohorts)
                   if eligible_cohorts is not None else frozenset())
        self._short_recheck_cohorts = (
            frozenset(prior_eligible)
            if (current and current.issubset(prior_eligible)
                and len(prior_eligible) >= self.MIN_COHORTS
                and len(prior_tours) >= self.MIN_TOURS
                and sum(prior_eligible.values()) >= self.PRIOR_MIN_TOTAL_REQUESTS)
            else frozenset()
        )

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
        self.paid_cohort_counts[(tour, year)] += 1
        self.paid_matches_observed += 1
        self.paid_attempts_observed += paid_attempts
        self._run_had_gain = self._run_had_gain or added > 0

        # Recheck a previously empty provider route with a small fresh,
        # cross-tour paid sample. Any new canonical gain disables the shortcut
        # for this run; the ordinary 120-match circuit remains in force.
        # Do not call this a provider outage merely because CDB fields stayed
        # NULL or identities conflicted: require fresh, reasoned empty bodies.
        if (self._short_recheck_cohorts and not self._run_had_gain
                and self.paid_matches_observed >= self.PRIOR_RECHECK_MATCHES):
            recent = list(self.samples)[-self.PRIOR_RECHECK_MATCHES:]
            counts = Counter((r[0], r[1]) for r in recent
                             if (r[0], r[1]) in self._short_recheck_cohorts)
            sampled = {key for key, count in counts.items()
                       if count >= self.MIN_COHORT_MATCHES}
            if (len(sampled) >= self.MIN_COHORTS
                    and len({key[0] for key in sampled}) >= self.MIN_TOURS
                    and all(r[3] and r[4] == 0 for r in recent)
                    and all((r[0], r[1]) in self._short_recheck_cohorts
                            for r in recent)):
                self.tripped = True
                self.trigger = {
                    "reason": "verified_prior_zero_gain_cross_tour_recheck",
                    "recent_paid_matches": len(recent),
                    "recent_paid_attempts": sum(r[2] for r in recent),
                    "recent_unavailable_matches": len(recent),
                    "recent_new_canonical_fields": 0,
                    "sampled_cohorts": len(sampled),
                    "sampled_tours": len({key[0] for key in sampled}),
                    "scope": "current_high_yield_statistics_run_only",
                    "prior_evidence": "independently_verified_previous_CDB_readback",
                }
                return True

        # Check a bounded *recent* window, so previously productive hours do
        # not conceal a now-empty route, and old empty hours do not veto recovery.
        window = list(self.samples)[-self.MIN_PAID_MATCHES:]
        if len(window) < self.MIN_PAID_MATCHES:
            return False
        attempts = sum(row[2] for row in window)
        # Prove cross-tour availability from ALL paid samples in this run;
        # adaptive selection may put >75% of the most recent window in one
        # cohort, making a purely rolling cross-tour test ineffective.
        eligible_cohorts = {key for key, count in self.paid_cohort_counts.items()
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
            "prior_zero_gain_recheck_eligible": bool(self._short_recheck_cohorts),
            "prior_zero_gain_cohorts": len(self._short_recheck_cohorts),
            "prior_recheck_paid_matches": self.PRIOR_RECHECK_MATCHES,
            "trigger": self.trigger,
            "policy": ("Paid, recent, cross-tour observations; no change to "
                       "CDB import, shared quota, manual/BP modes or external cron"),
        }
