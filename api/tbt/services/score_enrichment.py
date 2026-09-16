from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..errors import ProviderError
from ..providers.score import parse_event_score


SCORE_SCHEMA_VERSION = 1
EXCLUDED_STATUSES = {
    "retired", "walkover", "walk over", "cancelled", "canceled",
    "abandoned", "interrupted", "suspended", "postponed",
}


class ScoreEnricher:
    """Backfill verified whole-match set/game facts from the canonical event ID."""

    def __init__(self, provider, cache_path):
        self.provider = provider
        self.cache = sqlite3.connect(str(cache_path))
        self.cache.execute(
            "CREATE TABLE IF NOT EXISTS responses (path TEXT PRIMARY KEY, fetched REAL, body TEXT)"
        )

    def close(self):
        self.cache.close()

    def _get(self, path):
        now = datetime.now(timezone.utc).timestamp()
        row = self.cache.execute(
            "SELECT fetched, body FROM responses WHERE path=?", (path,)
        ).fetchone()
        if row is not None and now - row[0] < 30 * 86400:
            return json.loads(row[1])
        payload = self.provider._get(path, enrichment=True)
        if not isinstance(payload, dict):
            raise ProviderError("Expected object from event detail endpoint")
        self.cache.execute(
            "INSERT OR REPLACE INTO responses VALUES (?, ?, ?)",
            (path, now, json.dumps(payload)),
        )
        self.cache.commit()
        return payload

    def enrich(self, match):
        now = datetime.now(timezone.utc)
        if not match.is_completed or match.scheduled_at >= now:
            return "ineligible"
        if str(match.status or "").strip().lower() in EXCLUDED_STATUSES:
            return "excluded_status"

        raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
        event_id = next(
            (
                raw.get(key)
                for key in (
                    "_tbt_provider_event_id", "provider_event_id", "event_id",
                    "eventId", "id",
                )
                if raw.get(key) not in (None, "")
            ),
            None,
        )
        if event_id is None or not str(event_id).isascii() or not str(event_id).isdigit():
            return "missing_event_id"
        event_id = str(event_id)

        marker = raw.get("_tbt_score", {}) if isinstance(raw.get("_tbt_score"), dict) else {}
        if marker.get("schema") == SCORE_SCHEMA_VERSION and marker.get("event_id") == event_id:
            try:
                checked = datetime.fromisoformat(str(marker.get("fetched_at") or ""))
            except ValueError:
                checked = datetime.fromtimestamp(0, tz=timezone.utc)
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            if marker.get("status") == "available" or (now - checked).total_seconds() < 30 * 86400:
                return "cached"

        detail = self._get(f"/api/tennis/event/{event_id}")
        event = detail.get("event") if isinstance(detail.get("event"), dict) else detail
        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        status_type = str(status.get("type") or status.get("name") or event.get("status") or "").lower()
        if status_type not in {"finished", "completed", "ended", "ft", "final"}:
            return "not_finished"

        home = str((event.get("homeTeam") or {}).get("id") or "") if isinstance(event.get("homeTeam"), dict) else ""
        away = str((event.get("awayTeam") or {}).get("id") or "") if isinstance(event.get("awayTeam"), dict) else ""
        if {home, away} != {str(match.player1_id), str(match.player2_id)} or not home or home == away:
            raise ProviderError("Event player identity mismatch; refusing score attachment")

        try:
            score = parse_event_score(
                event,
                home_is_player1=home == str(match.player1_id),
                best_of=match.best_of,
            )
            parser_status = "available" if score else "unavailable"
        except ProviderError:
            score = {}
            parser_status = "unsupported"

        if score:
            match.stats = {**(match.stats or {}), **score}
        updated_raw = dict(raw)
        updated_raw["_tbt_event_identity"] = {
            "event_id": event_id,
            "home": home,
            "away": away,
            "status": "finished",
        }
        updated_raw["_tbt_score"] = {
            "schema": SCORE_SCHEMA_VERSION,
            "event_id": event_id,
            "source": "tennisapi1_event_detail",
            "fetched_at": now.isoformat(),
            "status": parser_status,
        }
        match.provider_payload = updated_raw
        return "enriched" if score else parser_status
