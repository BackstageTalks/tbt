from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..errors import ProviderError
from ..providers.statistics import NoSupportedStatisticsError, parse_statistics


STATISTICS_SCHEMA_VERSION = 2


class StatisticsEnricher:
    """Reuse settled statistics and verified identity to avoid redundant calls."""

    def __init__(self, provider, cache_path):
        self.provider = provider
        self.cache = sqlite3.connect(str(cache_path))
        self.cache.execute("CREATE TABLE IF NOT EXISTS responses (path TEXT PRIMARY KEY, fetched REAL, body TEXT)")

    def close(self):
        self.cache.close()

    def _get(self, path):
        now = datetime.now(timezone.utc).timestamp()
        row = self.cache.execute("SELECT fetched, body FROM responses WHERE path=?", (path,)).fetchone()
        if row is not None and now - row[0] < 7 * 86400:
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
        event_id = next((raw.get(k) for k in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id") if raw.get(k)), None)
        if event_id is None or not str(event_id).isascii() or not str(event_id).isdigit():
            return "missing_event_id"
        marker = raw.get("_tbt_statistics", {})
        if marker.get("schema") == STATISTICS_SCHEMA_VERSION and marker.get("event_id") == str(event_id):
            checked = datetime.fromisoformat(marker["fetched_at"])
            # Completed historical statistics persist in Parquet, not just the
            # ephemeral runner cache. Missing coverage gets a monthly retry.
            if marker.get("status") == "available" or (datetime.now(timezone.utc) - checked).total_seconds() < 30 * 86400:
                return "cached"
        # Resolve identity from the same event ID as the statistics. Canonical
        # match order can differ from provider home/away, including archived rows.
        identity = raw.get("_tbt_event_identity", {})
        if identity.get("event_id") == str(event_id) and identity.get("status") == "finished":
            home, away = identity.get("home"), identity.get("away")
        else:
            detail = self._get(f"/api/tennis/event/{event_id}")
            event = detail.get("event", detail)
            home = str(event.get("homeTeam", {}).get("id", ""))
            away = str(event.get("awayTeam", {}).get("id", ""))
            if event.get("status", {}).get("type") != "finished":
                return "not_finished"
        if {home, away} != {match.player1_id, match.player2_id} or home == away:
            raise ProviderError("Event player identity mismatch; refusing statistics attachment")
        payload = self._get(f"/api/tennis/event/{event_id}/statistics")
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

        match.stats = {**match.stats, **stats}
        match.provider_payload = {**raw, "_tbt_statistics": {
            "schema": STATISTICS_SCHEMA_VERSION, "event_id": str(event_id), "source": "tennisapi1",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status": "available" if stats else "unavailable",
        }}
        return "enriched" if stats else "unavailable"
