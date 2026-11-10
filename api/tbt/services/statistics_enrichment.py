from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
import math
from datetime import datetime, timezone

from ..errors import ProviderError
from ..providers.statistics import (ConflictingStatisticsError, NoSupportedStatisticsError, complete_opponent_service_rates, parse_statistics, inventory_statistics_keys)
from ..providers.tennisapi_extra import normalize_set_statistics_home_away
from .statistics_gapfill import event_id as resolve_event_id, missing_fields, retry_due, recent_score_identity_conflict
from .tennis_response_cache import RawResponseCache
from .tennis_remote_cache_client import HttpRawResponseCache


# V3 re-reads previously count-only V2 rows to capture the provider's
# now-supported whole-match serve/return point rates.
STATISTICS_SCHEMA_VERSION = 3


_COUNT_SUFFIXES = ("_aces", "_double_faults", "_service_points_total",
                   "_return_points_total")


def _same_canonical_stat(key, current, incoming) -> bool:
    """Protect canonical precision while tolerating binary float representation.

    Count fields require *exact* numerical equality. Rates may differ by
    at most 1e-10 (absolute), far below the precision of reported tennis
    percentages; actual conflicting rates are still quarantined.
    """
    if (isinstance(current, bool) or isinstance(incoming, bool)
            or not isinstance(current, (int, float))
            or not isinstance(incoming, (int, float))):
        return False
    if not (math.isfinite(current) and math.isfinite(incoming)):
        return False
    if current == incoming:
        return True
    if key.endswith(_COUNT_SUFFIXES):
        return False
    return math.isclose(float(current), float(incoming),
                        rel_tol=0.0, abs_tol=1e-10)


class StatisticsEnricher:
    """Reuse settled statistics and verified identity to avoid redundant calls."""

    def __init__(self, provider, cache_path, *, targeted=False, break_points_focus=False):
        if break_points_focus and not targeted:
            raise ValueError('Break-point focus requires the targeted CDB statistics importer')
        self.provider = provider
        self.targeted = targeted
        self.break_points_focus = break_points_focus
        self.cache = sqlite3.connect(str(cache_path))
        self.cache.execute("CREATE TABLE IF NOT EXISTS responses (path TEXT PRIMARY KEY, fetched REAL, body TEXT)")
        self.statistics_key_counts = {name: Counter() for name in ("supported", "unsupported", "set_only")}
        self.statistics_key_responses = 0
        self.statistics_invalid_envelopes = 0
        # Aggregate diagnostics only: no identities or raw provider values.
        # These counters never authorize replacing canonical statistics.
        self.conflict_responses = 0
        self.conflict_field_counts = Counter()
        self.conflict_rejected_null_fields = Counter()
        self.conflict_difference_buckets = Counter()
        self.equivalent_numeric_fields_preserved = Counter()
        private_path = os.getenv("BLINQ_TENNIS_RAW_CACHE_SQLITE", "").strip()
        # The caller must mount a private persistent directory. A bad mount
        # fails closed rather than silently reverting to paid requests.
        remote_url = os.getenv("BLINQ_TENNIS_RAW_CACHE_URL", "").strip()
        if remote_url:
            token = os.getenv("BLINQ_SHARED_API_BUDGET_TOKEN", "").strip()
            self.durable = HttpRawResponseCache(remote_url, token)
        else:
            self.durable = RawResponseCache(private_path) if private_path else None

    def statistics_key_summary(self) -> dict:
        """Aggregate already-fetched key names, never raw values/player IDs.

        Includes durable/local cache responses as well as paid responses. It
        does not measure billable calls, create canonical fields or authorize
        schema mapping of unknown provider keys.
        """
        return {
            "schema": 1,
            "observed_response_payloads": self.statistics_key_responses,
            "invalid_envelopes": self.statistics_invalid_envelopes,
            "counts_by_key": {
                name: dict(sorted(counter.items()))
                for name, counter in self.statistics_key_counts.items()
            },
            "policy": "Aggregate key discovery from already-read payloads (paid or cache); no new API calls, no raw data, no automatic field promotion.",
        }

    def conflict_diagnostics(self) -> dict:
        """Bounded per-field evidence for safe API-yield research, no mutation.

        `rejected_null_field_candidates` are *not* approved CDB values: the
        provider response is quarantined if any existing field conflicts.
        """
        return {
            "schema": 1,
            "rejected_responses": self.conflict_responses,
            "by_conflicting_field": dict(sorted(self.conflict_field_counts.items())),
            "rejected_null_field_candidates": dict(
                sorted(self.conflict_rejected_null_fields.items())
            ),
            "numeric_difference_buckets": dict(
                sorted(self.conflict_difference_buckets.items())
            ),
            "equivalent_numeric_fields_preserved": dict(
                sorted(self.equivalent_numeric_fields_preserved.items())
            ),
            "policy": "Diagnostic only. Entire conflicting responses remain rejected; no canonical overwrite or partial import.",
        }

    def _observe_statistics_keys(self, payload) -> None:
        inventory = inventory_statistics_keys(payload)
        self.statistics_key_responses += 1
        self.statistics_invalid_envelopes += int(inventory["invalid_envelope"])
        for name, counter in self.statistics_key_counts.items():
            # Bound untrusted names and cardinality in a large historical run.
            for key in inventory[name][:100]:
                if len(key) <= 64 and (key in counter or len(counter) < 200):
                    counter[key] += 1

    def close(self):
        self.cache.close()
        if self.durable is not None and hasattr(self.durable, "close"):
            self.durable.close()

    def _get(self, path, max_age=7 * 86400):
        if self.durable is not None:
            payload = self.durable.get_or_load(
                provider="tennisapi1", host=self.provider.cfg.rapidapi_host,
                endpoint=path, kind=("finished_statistics" if path.endswith("/statistics")
                                     else "finished_detail"),
                parser_version=STATISTICS_SCHEMA_VERSION, max_age=max_age,
                loader=lambda: self.provider._get(path, enrichment=True),
            )
            if not isinstance(payload, dict):
                raise ProviderError("Expected object from event/statistics endpoint")
            return payload
        now = datetime.now(timezone.utc).timestamp()
        row = self.cache.execute("SELECT fetched, body FROM responses WHERE path=?", (path,)).fetchone()
        if row is not None and now - row[0] < max_age:
            return json.loads(row[1])
        payload = self.provider._get(path, enrichment=True)
        if not isinstance(payload, dict):
            raise ProviderError("Expected object from event/statistics endpoint")
        self.cache.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?)",
                           (path, now, json.dumps(payload)))
        self.cache.commit()
        return payload

    def enrich(self, match):
        if not match.is_completed or match.scheduled_at >= datetime.now(timezone.utc):
            return "ineligible"
        raw = match.provider_payload or {}
        event_id = resolve_event_id(match)
        if event_id is None:
            return "missing_event_id"
        # Repair existing schema-3 return-only snapshots locally before the
        # normal cache check. This requires zero provider/API requests.
        marker = raw.get("_tbt_statistics", {})
        if not isinstance(marker, dict):
            marker = {}
        if (marker.get("schema") == STATISTICS_SCHEMA_VERSION
                and marker.get("event_id") == str(event_id)
                and marker.get("status") == "available"
                and complete_opponent_service_rates(match.stats)
                and (not self.targeted or not missing_fields(
                     match, break_points_focus=self.break_points_focus))):
            return "enriched"
        legacy_available = (not self.targeted and marker.get("schema") == STATISTICS_SCHEMA_VERSION
                            and marker.get("event_id") == str(event_id)
                            and marker.get("status") == "available")
        if legacy_available or not retry_due(
                match, STATISTICS_SCHEMA_VERSION,
                break_points_focus=self.break_points_focus):
            return "cached"
        # An independently recorded score/identity mismatch cannot safely
        # yield canonical statistics. Reuse that evidence during its cooldown.
        if recent_score_identity_conflict(match):
            return "cached"
        # Resolve identity from the same event ID as the statistics. Canonical
        # match order can differ from provider home/away, including archived rows.
        identity = raw.get("_tbt_event_identity", {})
        if identity.get("event_id") == str(event_id) and identity.get("status") == "finished":
            home, away = identity.get("home"), identity.get("away")
        else:
            # Detail responses can initially report an incomplete event even
            # for a canonical completed match. Do not retain that stale status
            # in the local HTTP cache for an entire week.
            detail = self._get(f"/api/tennis/event/{event_id}", max_age=86400)
            event = detail.get("event", detail)
            home = str(event.get("homeTeam", {}).get("id", ""))
            away = str(event.get("awayTeam", {}).get("id", ""))
            if event.get("status", {}).get("type") != "finished":
                # Preserve the authoritative match status and all its values;
                # this is a provider detail coverage mismatch, not evidence
                # to mutate match identity or classify the match as ongoing.
                # Persist a reasoned cooldown so the next hourly tick cannot
                # repay the same detail request. retry_due handles recent
                # events (1 day) and older events (30 days) conservatively.
                match.provider_payload = {**raw, "_tbt_statistics": {
                    "schema": STATISTICS_SCHEMA_VERSION,
                    "event_id": str(event_id), "source": "tennisapi1",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "status": "unavailable", "reason": "provider_event_not_finished",
                }}
                return "unavailable"
        if {str(home), str(away)} != {str(match.player1_id), str(match.player2_id)} or home == away:
            # If score enrichment already recorded this SAME conflict, a
            # recheck after cooldown must not abort the entire statistics run
            # and repeatedly pay for the same impossible match each hour.
            prior = raw.get("_tbt_event_identity")
            score = raw.get("_tbt_score")
            known = (
                isinstance(prior, dict) and isinstance(score, dict)
                and prior.get("status") == "mismatch"
                and prior.get("event_id") == str(event_id)
                and score.get("status") == "identity_mismatch"
                and score.get("event_id") == str(event_id)
                and score.get("identity_verified") is False
            )
            if known:
                match.provider_payload = {**raw, "_tbt_statistics": {
                    "schema": STATISTICS_SCHEMA_VERSION,
                    "event_id": str(event_id), "source": "tennisapi1",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "status": "conflict", "reason": "provider_identity_mismatch",
                }}
                return "conflict"
            raise ProviderError("Event player identity mismatch; refusing statistics attachment")
        # Retain verified detail identity so later missing-field retries need
        # only the statistics endpoint, including after the runner is replaced.
        raw = {**raw, "_tbt_event_identity": {
            "event_id": str(event_id), "home": home, "away": away, "status": "finished",
        }}
        payload = self._get(f"/api/tennis/event/{event_id}/statistics", max_age=30 * 86400)
        self._observe_statistics_keys(payload)
        try:
            stats = parse_statistics(payload, home_is_player1=home == match.player1_id)
        except NoSupportedStatisticsError:
            # A completed event can legitimately return HTTP 200 statistics that
            # contain only fields outside our conservative Aces/DF/serve contract.
            # That is missing coverage, not a fatal provider/schema error. Preserve
            # a small key summary so a future adapter extension is diagnosable, and
            # cache the miss in canonical history for the normal monthly retry.
            keys = []
            for period in payload.get("statistics", []) if isinstance(payload, dict) else []:
                if not isinstance(period, dict) or str(period.get("period", "")).upper() != "ALL":
                    continue
                for group in period.get("groups", []) if isinstance(period.get("groups"), list) else []:
                    if not isinstance(group, dict):
                        continue
                    for item in group.get("statisticsItems", []) if isinstance(group.get("statisticsItems"), list) else []:
                        if not isinstance(item, dict):
                            continue
                        value = str(item.get("key") or item.get("name") or "").strip()
                        if value and value not in keys:
                            keys.append(value)
            match.provider_payload = {**raw, "_tbt_statistics": {
                "schema": STATISTICS_SCHEMA_VERSION, "event_id": str(event_id), "source": "tennisapi1",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "status": "unavailable", "reason": "no_supported_fields",
                "unsupported_keys": keys[:40],
            }}
            return "unavailable"
        except ConflictingStatisticsError as exc:
            # Contradictory supported ALL-period values invalidate this entire
            # event response, not the surrounding canonical batch. Preserve
            # every existing CDB cell, record a normal conflict cooldown and
            # continue with independent eligible events. Unexpected provider
            # failures and malformed envelopes remain fatal.
            self.conflict_responses += 1
            self.conflict_field_counts[exc.field] += 1
            match.provider_payload = {**raw, "_tbt_statistics": {
                "schema": STATISTICS_SCHEMA_VERSION, "event_id": str(event_id),
                "source": "tennisapi1",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "status": "conflict", "reason": "provider_internal_stat_conflict",
            }}
            return "conflict"
        except ProviderError as exc:
            # Some completed provider events expose only set-level statistics or
            # duplicate/non-canonical period labels and therefore have no single
            # trustworthy whole-match ALL block. That is an event-level coverage
            # miss, not a reason to abort a multi-thousand-match enrichment batch.
            # Keep other ProviderError cases fatal (identity and malformed
            # envelopes); event-level contradictions have a typed path above.
            if str(exc) != "Missing unambiguous ALL period in statistics":
                raise
            periods = payload.get("statistics") if isinstance(payload, dict) else None
            period_labels = []
            if isinstance(periods, list):
                for period in periods:
                    if not isinstance(period, dict):
                        continue
                    label = str(period.get("period") or "").strip()
                    if label and label not in period_labels:
                        period_labels.append(label)
            match.provider_payload = {**raw, "_tbt_statistics": {
                "schema": STATISTICS_SCHEMA_VERSION, "event_id": str(event_id), "source": "tennisapi1",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "status": "unavailable", "reason": "missing_unambiguous_all_period",
                "period_labels": period_labels[:20],
            }}
            return "unavailable"

        # A paid response is not permission to replace authoritative history.
        # Reject the entire conflicting response, including unrelated additions.
        existing_stats = match.stats or {}
        # A tiny binary-float representation difference is not a substantive
        # conflict, but it also never permits replacement of the stored value.
        self.equivalent_numeric_fields_preserved.update(
            key for key, value in stats.items()
            if existing_stats.get(key) is not None
            and existing_stats[key] != value
            and _same_canonical_stat(key, existing_stats[key], value)
        )
        conflicts = [key for key, value in stats.items()
                     if existing_stats.get(key) is not None
                     and not _same_canonical_stat(key, existing_stats[key], value)]
        if conflicts:
            self.conflict_responses += 1
            self.conflict_field_counts.update(conflicts)
            self.conflict_rejected_null_fields.update(
                key for key in stats if (match.stats or {}).get(key) is None
            )
            for key in conflicts:
                current = (match.stats or {})[key]
                try:
                    delta = abs(float(current) - float(stats[key]))
                except (TypeError, ValueError, OverflowError):
                    bucket = "non_numeric"
                else:
                    if not math.isfinite(delta):
                        bucket = "non_finite"
                    elif delta < 1e-6:
                        bucket = "lt_0.000001"
                    elif delta < 1e-3:
                        bucket = "lt_0.001"
                    elif delta < 1e-2:
                        bucket = "lt_0.01"
                    elif delta < 0.05:
                        bucket = "lt_0.05"
                    else:
                        bucket = "gte_0.05"
                self.conflict_difference_buckets[bucket] += 1
            match.provider_payload = {**raw, "_tbt_statistics": {
                "schema": STATISTICS_SCHEMA_VERSION, "event_id": str(event_id),
                "source": "tennisapi1", "fetched_at": datetime.now(timezone.utc).isoformat(),
                "status": "conflict", "reason": "existing_canonical_stat_conflict",
                "unsupported_keys": sorted(conflicts)[:40],
            }}
            return "conflict"
        if not stats:
            # Some legitimate HTTP-200 responses have no ALL-match statistics
            # at all. Explicitly label the coverage miss: previously these
            # became "unavailable_unspecified", obscuring hundreds of costly
            # provider lookups and frustrating targeted gap triage.
            match.provider_payload = {**raw, "_tbt_statistics": {
                "schema": STATISTICS_SCHEMA_VERSION, "event_id": str(event_id),
                "source": "tennisapi1", "fetched_at": datetime.now(timezone.utc).isoformat(),
                "status": "unavailable", "reason": "empty_whole_match_statistics",
            }}
            return "unavailable"
        # Reuse this already-paid verified post-match response for per-set
        # research. Do NOT map these side-labelled values into pre-match model
        # features or replace any authoritative whole-match statistics.
        try:
            per_set = normalize_set_statistics_home_away(payload)
            # A partly covered set tape may undercount ALL, never exceed it.
            for side, player in (("home", "p1" if home == match.player1_id else "p2"),
                                 ("away", "p1" if away == match.player1_id else "p2")):
                for metric in ("aces", "double_faults"):
                    official = stats.get(f"{player}_{metric}")
                    observed = sum(v.get(f"{side}_{metric}", 0)
                                   for v in per_set.values())
                    if official is not None and observed > official + 1e-6:
                        raise ProviderError("Per-set statistics exceed whole-match totals")
        except ProviderError:
            # Malformed or contradictory set-only data must not poison valid
            # whole-match CDB enrichment. No partial per-set cells are written.
            per_set = {}
        # A future retry must never replace earlier provider-side evidence
        # with fewer sets or conflicting lower-quality data. Reconciliation
        # belongs to an explicit audited, provenance-aware CDB writer.
        if per_set and "_tbt_statistics_by_set" not in raw:
            raw = {**raw, "_tbt_statistics_by_set": {
                "schema": 1, "source": "tennisapi1",
                "event_id": str(event_id), "orientation": "provider_home_away",
                "scope": "post_match_only", "sets": per_set,
            }}
        # Exact NULL-only import: preserve existing canonical values and their
        # original precision/type, including numerically equivalent rates.
        match.stats = {**existing_stats, **{
            key: value for key, value in stats.items()
            if existing_stats.get(key) is None
        }}
        match.provider_payload = {**raw, "_tbt_statistics": {
            "schema": STATISTICS_SCHEMA_VERSION, "event_id": str(event_id), "source": "tennisapi1",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status": "available",
        }}
        return "enriched"
