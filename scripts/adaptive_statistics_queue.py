"""In-run adaptive allocation for the existing guarded TennisApi statistics queue.

No provider calls or CDB writes happen here. The ordinary deterministic gap
queue supplies exploration order; only *observed paid* requests and actually
new cells / full serve-return transitions change subsequent priorities.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque

from audit_statistics_inventory import _quality_ready


class AdaptiveStatisticsQueue:
    """Exploit proven CDB gain without starving under-covered cohorts.

    Starts from the existing missing-field, identity-checked, cooldown-checked
    order. At least one in four selections remains in that original order.
    Within-run exploitation only starts after 80 paid requests and two
    independently sampled cohorts (12 paid calls each). Nothing is learned
    from cache hits, candidate counts, or unverified model performance.
    """

    MIN_TOTAL_REQUESTS = 80
    MIN_COHORT_REQUESTS = 12
    EXPLORE_EVERY = 4

    def __init__(self, candidates, bucket_coverage=None):
        self._baseline = deque()
        self._pending = defaultdict(deque)
        self._populated = set()
        for match in candidates:
            identity = id(match)
            if identity in self._populated:
                raise ValueError("Duplicate statistics queue object")
            self._populated.add(identity)
            tour = str(match.tour or "unknown").lower()
            year = int(match.scheduled_at.year)
            stats = match.stats if isinstance(match.stats, dict) else {}
            kind = ("ace_df" if _quality_ready(stats, "p1")
                    and _quality_ready(stats, "p2") else "serve_return")
            group = f"{tour}:{year}:{kind}"
            self._baseline.append((group, match))
            self._pending[group].append(match)
        self._remaining = len(candidates)
        self._active = {}
        self._selected = set()
        self._served = 0
        self._total_paid = 0
        self._paid = Counter()
        self._reward = Counter()
        self._values = Counter()
        self._quality = Counter()
        self._ace_df = Counter()
        self._baseline_choices = Counter()
        self._adaptive_choices = Counter()
        self._coverage = {}
        for group in self._pending:
            bucket = group.rsplit(":", 1)[0]
            item = (bucket_coverage or {}).get(bucket, {})
            rate = item.get("quality_ready_rate", 0.5)
            self._coverage[group] = min(1.0, max(0.0, float(rate)))

    def __iter__(self):
        return self

    def _baseline_pick(self):
        while self._baseline and id(self._baseline[0][1]) in self._selected:
            self._baseline.popleft()
        if not self._baseline:
            raise RuntimeError("Adaptive queue exhausted before its declared count")
        group, match = self._baseline.popleft()
        if not self._pending[group] or self._pending[group][0] is not match:
            raise RuntimeError("Statistics queue identity/order mismatch")
        self._baseline_choices[group] += 1
        return group, match

    def _eligible(self):
        return [group for group in sorted(self._pending)
                if self._pending[group] and self._paid[group] >= self.MIN_COHORT_REQUESTS]

    def _score(self, group):
        # Six virtual neutral requests damp early noise. Serve/return readiness
        # transitions are more valuable than raw counts. Incomplete seasons
        # receive a small bonus, not an overriding priority.
        reward = self._reward[group]
        per_call = (18.0 + reward) / (6.0 + self._paid[group])
        return per_call * (1.0 + 0.25 * (1.0 - self._coverage[group]))

    def __next__(self):
        if not self._remaining:
            raise StopIteration
        eligible = self._eligible() if self._total_paid >= self.MIN_TOTAL_REQUESTS else []
        adaptive = (self._served % self.EXPLORE_EVERY != 0 and len(eligible) >= 2)
        if adaptive:
            # sorted eligibility makes equal-score results deterministic.
            group = max(eligible, key=self._score)
            match = self._pending[group][0]
            self._adaptive_choices[group] += 1
        else:
            group, match = self._baseline_pick()
        popped = self._pending[group].popleft()
        if popped is not match or id(match) in self._selected:
            raise RuntimeError("Adaptive statistics selected a row twice")
        self._selected.add(id(match))
        self._active[id(match)] = group
        self._remaining -= 1
        self._served += 1
        return match

    def record(self, match, requests, value_change):
        """Record only paid, verified-field deltas for the row just attempted."""
        group = self._active.pop(id(match), None)
        if group is None:
            raise ValueError("Feedback does not match a selected statistics event")
        requests = int(requests)
        if requests < 0:
            raise ValueError("Negative API request delta")
        if requests == 0:
            return  # local/cached gains must never change the empirical score
        values = int(value_change.get("new_statistic_values", 0))
        quality = int(value_change.get("new_quality_ready_rows", 0))
        ace_df = int(value_change.get("new_ace_df_values", 0))
        if min(values, quality, ace_df) < 0 or ace_df > values or quality > 1:
            raise ValueError("Invalid observed statistics gain")
        self._paid[group] += requests
        self._total_paid += requests
        self._values[group] += values
        self._quality[group] += quality
        self._ace_df[group] += ace_df
        self._reward[group] += 16 * quality + 0.75 * values + 0.25 * ace_df

    def summary(self):
        groups = sorted(self._pending)
        return {
            "policy": "bounded_online_observed_cdb_yield_v1",
            "no_extra_api_calls": True,
            "min_paid_requests": self.MIN_TOTAL_REQUESTS,
            "min_cohort_paid_requests": self.MIN_COHORT_REQUESTS,
            "minimum_baseline_exploration_fraction": 1 / self.EXPLORE_EVERY,
            "candidate_rows": self._served + self._remaining,
            "selected_rows": self._served,
            "remaining_rows": self._remaining,
            "observed_paid_requests": self._total_paid,
            "baseline_choices": sum(self._baseline_choices.values()),
            "adaptive_choices": sum(self._adaptive_choices.values()),
            "online_adaptation_used": bool(self._adaptive_choices),
            "cohorts": {
                group: {
                    "paid_requests": self._paid[group],
                    "new_statistic_values": self._values[group],
                    "new_quality_ready_rows": self._quality[group],
                    "new_ace_df_values": self._ace_df[group],
                    "baseline_choices": self._baseline_choices[group],
                    "adaptive_choices": self._adaptive_choices[group],
                }
                for group in groups
                if (self._paid[group] or self._baseline_choices[group]
                    or self._adaptive_choices[group])
            },
        }
