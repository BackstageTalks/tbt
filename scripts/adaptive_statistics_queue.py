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
    RECENT_MATCH_WINDOW = 96
    # A repeated paid provider miss must not consume the fixed exploration
    # share indefinitely. Require evidence from at least 20 separate matches;
    # still sample weak cohorts every twelfth baseline selection.
    LOW_YIELD_MIN_REQUESTS = 24
    LOW_YIELD_MIN_MATCHES = 20
    LOW_YIELD_SAMPLE_EVERY = 12

    def __init__(self, candidates, bucket_coverage=None, *, verified_prior=None):
        self._order = {}
        self._pending = defaultdict(deque)
        self._populated = set()
        for position, match in enumerate(candidates):
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
            self._order[identity] = position
            self._pending[group].append(match)
        self._remaining = len(candidates)
        self._active = {}
        self._selected = set()
        self._served = 0
        self._total_paid = 0
        self._paid = Counter()
        self._reward = Counter()
        # A lifetime average can keep favoring a cohort long after its
        # high-yield backlog is exhausted. Score only the latest paid matches
        # while retaining lifetime counters for independent CDB audit.
        self._recent = defaultdict(deque)
        self._recent_requests = Counter()
        self._recent_reward = Counter()
        self._recent_values = Counter()
        self._recent_quality = Counter()
        self._values = Counter()
        self._quality = Counter()
        self._ace_df = Counter()
        self._baseline_choices = Counter()
        self._adaptive_choices = Counter()
        self._baseline_draws = 0
        self._low_yield_deferrals = 0
        self._low_yield_samples = 0
        self._reference_year = max(
            (int(row.scheduled_at.year) for queue in self._pending.values()
             for row in queue), default=2026
        )
        # Previously persisted evidence is bounded and separately tracked;
        # never add it to the current run's paid requests or CDB value totals.
        self._verified_prior = verified_prior or {}
        self._prior_paid = Counter()
        self._prior_reward = Counter()
        for group in self._pending:
            item = self._verified_prior.get(group, {})
            if not isinstance(item, dict):
                continue
            requests = int(item.get('api_requests', 0))
            fields = int(item.get('new_fields', 0))
            ready = int(item.get('full_serve_return_rows', 0))
            if requests >= self.MIN_COHORT_REQUESTS and 0 <= ready <= fields and fields >= 0:
                # Bound historical influence; latest in-run observations win.
                scale = min(requests, self.RECENT_MATCH_WINDOW) / requests
                self._prior_paid[group] = min(requests, self.RECENT_MATCH_WINDOW)
                self._prior_reward[group] = scale * (16 * ready + 0.75 * fields)
        self._coverage = {}
        for group in self._pending:
            bucket = group.rsplit(":", 1)[0]
            item = (bucket_coverage or {}).get(bucket, {})
            rate = item.get("quality_ready_rate", 0.5)
            self._coverage[group] = min(1.0, max(0.0, float(rate)))

    def __iter__(self):
        return self

    def _low_yield(self, group):
        """Use only recent paid evidence; a recovering cohort resumes normally."""
        requests = self._recent_requests[group]
        return (
            requests >= self.LOW_YIELD_MIN_REQUESTS
            and len(self._recent[group]) >= self.LOW_YIELD_MIN_MATCHES
            and self._recent_quality[group] == 0
            and 4 * self._recent_values[group] <= requests
        )

    def _baseline_pick(self):
        # Adaptive choices remove rows from per-cohort FIFOs. Finding the
        # next baseline choice by scanning the original global deque would
        # repeatedly walk stale adaptive selections and could accidentally
        # let a weak cohort consume the entire baseline share. Select the
        # lowest original-rank *current cohort head* instead (O(cohorts)).
        heads = sorted(
            (self._order[id(rows[0])], group, rows[0])
            for group, rows in self._pending.items() if rows
        )
        if not heads:
            raise RuntimeError("Adaptive queue exhausted before its declared count")
        probe = self._baseline_draws % self.LOW_YIELD_SAMPLE_EVERY == (
            self.LOW_YIELD_SAMPLE_EVERY - 1
        )
        selected = heads[0]
        if not probe and self._low_yield(selected[1]):
            selected = next(
                (item for item in heads if not self._low_yield(item[1])),
                selected,
            )
        if selected != heads[0]:
            self._low_yield_deferrals += 1
        _, group, match = selected
        if self._low_yield(group):
            self._low_yield_samples += 1
        self._baseline_draws += 1
        self._baseline_choices[group] += 1
        return group, match

    def _eligible(self):
        return [group for group in sorted(self._pending)
                if self._pending[group] and
                self._paid[group] + self._prior_paid[group] >= self.MIN_COHORT_REQUESTS]

    def _score(self, group):
        # Use paid, retry-adjusted recent yield as the dominant signal.
        # A bounded recency factor shifts comparable-yield work to the latest
        # three seasons, while very productive older cohorts can still win.
        reward = self._recent_reward[group] + self._prior_reward[group]
        per_call = (18.0 + reward) / (6.0 + self._recent_requests[group] + self._prior_paid[group])
        age = max(0, self._reference_year - int(group.split(":")[1]))
        recency = (1.25 if age == 0 else 1.30 if age == 1 else
                   1.32 if age == 2 else 0.94 if age == 3 else 0.82)
        return per_call * (1.0 + 0.25 * (1.0 - self._coverage[group])) * recency

    def __next__(self):
        if not self._remaining:
            raise StopIteration
        # A previous independently verified, parser-compatible cohort sample
        # may unlock early exploitation, but exploration remains >=25%.
        prior_total = sum(self._prior_paid.values())
        eligible = self._eligible() if (
            self._total_paid >= self.MIN_TOTAL_REQUESTS
            or prior_total >= self.MIN_TOTAL_REQUESTS) else []
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
        gain = 16 * quality + 0.75 * values + 0.25 * ace_df
        self._reward[group] += gain
        # Keep a bounded sample of paid attempts. Weight by actual provider
        # requests (including retries) so low-yield and retry-heavy cohorts
        # lose selection priority promptly rather than consuming the day.
        window = self._recent[group]
        window.append((requests, gain, values, quality))
        self._recent_requests[group] += requests
        self._recent_reward[group] += gain
        self._recent_values[group] += values
        self._recent_quality[group] += quality
        if len(window) > self.RECENT_MATCH_WINDOW:
            prev_requests, prev_gain, prev_values, prev_quality = window.popleft()
            self._recent_requests[group] -= prev_requests
            self._recent_reward[group] -= prev_gain
            self._recent_values[group] -= prev_values
            self._recent_quality[group] -= prev_quality

    def summary(self):
        groups = sorted(self._pending)
        return {
            "policy": "bounded_online_observed_cdb_yield_v1",
            "no_extra_api_calls": True,
            "min_paid_requests": self.MIN_TOTAL_REQUESTS,
            "min_cohort_paid_requests": self.MIN_COHORT_REQUESTS,
            "minimum_baseline_exploration_fraction": 1 / self.EXPLORE_EVERY,
            "low_yield_cohort_policy": "bounded_recent_paid_yield_with_recovery_probes",
            "low_yield_min_paid_requests": self.LOW_YIELD_MIN_REQUESTS,
            "low_yield_min_paid_matches": self.LOW_YIELD_MIN_MATCHES,
            "low_yield_probe_every_baseline_selections": self.LOW_YIELD_SAMPLE_EVERY,
            "low_yield_baseline_deferrals": self._low_yield_deferrals,
            "low_yield_baseline_samples": self._low_yield_samples,
            "selection_value_policy": "quality_ready_and_new_fields_recent_paid_window",
            "recency_score_policy": "bounded_latest_three_seasons_after_paid_yield",
            "recency_reference_year": self._reference_year,
            "recent_paid_match_window": self.RECENT_MATCH_WINDOW,
            "candidate_rows": self._served + self._remaining,
            "selected_rows": self._served,
            "remaining_rows": self._remaining,
            "observed_paid_requests": self._total_paid,
            "verified_prior_used": bool(self._prior_paid),
            "verified_prior_paid_requests_bounded": sum(self._prior_paid.values()),
            "baseline_choices": sum(self._baseline_choices.values()),
            "adaptive_choices": sum(self._adaptive_choices.values()),
            "online_adaptation_used": bool(self._adaptive_choices),
            "cohorts": {
                group: {
                    "paid_requests": self._paid[group],
                    "new_statistic_values": self._values[group],
                    "new_quality_ready_rows": self._quality[group],
                    "new_ace_df_values": self._ace_df[group],
                    "recent_paid_matches": len(self._recent[group]),
                    "recent_paid_requests": self._recent_requests[group],
                    "recent_new_statistic_values": self._recent_values[group],
                    "recent_new_quality_ready_rows": self._recent_quality[group],
                    "baseline_choices": self._baseline_choices[group],
                    "adaptive_choices": self._adaptive_choices[group],
                }
                for group in groups
                if (self._paid[group] or self._baseline_choices[group]
                    or self._adaptive_choices[group])
            },
        }
