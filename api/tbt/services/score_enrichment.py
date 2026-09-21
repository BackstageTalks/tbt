from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..errors import ProviderError
from ..match_format import (
    exact_best_of_from_score_stats,
    explicit_best_of_from_event,
)
from ..providers.score import parse_event_score


SCORE_SCHEMA_VERSION = 3
EXCLUDED_STATUSES = {
    "retired", "walkover", "walk over", "cancelled", "canceled",
    "abandoned", "interrupted", "suspended", "postponed",
}


class ScoreEnricher:
    """Backfill verified whole-match set/game facts from the canonical event ID."""

    def __init__(self, provider, cache_path, *, force_refresh: bool = False):
        self.provider = provider
        self.force_refresh = bool(force_refresh)
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
        if not self.force_refresh and row is not None and now - row[0] < 30 * 86400:
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
        if not self.force_refresh and marker.get("schema") == SCORE_SCHEMA_VERSION and marker.get("event_id") == event_id:
            try:
                checked = datetime.fromisoformat(str(marker.get("fetched_at") or ""))
            except ValueError:
                checked = datetime.fromtimestamp(0, tz=timezone.utc)
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            age_seconds = (now - checked).total_seconds()
            if marker.get("status") == "available":
                return "cached_verified"
            if age_seconds < 30 * 86400:
                if marker.get("status") == "identity_mismatch":
                    return "cached_identity_mismatch"
                return "cached_verified"

        detail = self._get(f"/api/tennis/event/{event_id}")
        event = detail.get("event") if isinstance(detail.get("event"), dict) else detail
        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        status_type = str(status.get("type") or status.get("name") or event.get("status") or "").lower()
        if status_type not in {"finished", "completed", "ended", "ft", "final"}:
            return "not_finished"

        home = str((event.get("homeTeam") or {}).get("id") or "") if isinstance(event.get("homeTeam"), dict) else ""
        away = str((event.get("awayTeam") or {}).get("id") or "") if isinstance(event.get("awayTeam"), dict) else ""
        expected = {str(match.player1_id), str(match.player2_id)}
        observed = {home, away}
        if observed != expected or not home or home == away:
            # Persist the mismatch as an auditable fail-closed fact. Previously
            # this raised ProviderError after a successful/cached detail fetch,
            # so mega-data repeatedly reported thousands of generic provider
            # errors without distinguishing identity drift from network faults.
            updated_raw = dict(raw)
            updated_raw["_tbt_event_identity"] = {
                "event_id": event_id,
                "home": home,
                "away": away,
                "expected_player_ids": sorted(expected),
                "status": "mismatch",
            }
            updated_raw["_tbt_score"] = {
                "schema": SCORE_SCHEMA_VERSION,
                "event_id": event_id,
                "source": "tennisapi1_event_detail",
                "fetched_at": now.isoformat(),
                "status": "identity_mismatch",
                "best_of": None,
                "best_of_source": "identity_mismatch",
                "identity_verified": False,
                "format_verified": False,
            }
            match.provider_payload = updated_raw
            return "identity_mismatch"

        provider_best_of = explicit_best_of_from_event(event)
        try:
            # Parse the finished structured score independently first. This lets
            # us cross-check an explicit provider bestOf instead of allowing a
            # wrong format field to hide an otherwise valid final score.
            score = parse_event_score(
                event,
                home_is_player1=home == str(match.player1_id),
                best_of=None,
            )
            parser_status = "available" if score else "unavailable"
        except ProviderError:
            score = {}
            parser_status = "unsupported"

        effective_best_of = provider_best_of
        best_of_source = "provider_detail" if provider_best_of in {3, 5} else "unknown"
        score_best_of = None
        if score:
            score_best_of, score_source = exact_best_of_from_score_stats(score)
            if score_best_of not in {3, 5}:
                # A structured score that cannot prove its own match format is
                # not safe for S/G training. Preserve the audit marker, but do
                # not attach ambiguous score facts to canonical history.
                score = {}
                parser_status = "unsupported_format"
            elif provider_best_of in {3, 5} and provider_best_of != score_best_of:
                score = {}
                parser_status = "format_conflict"
                effective_best_of = None
                best_of_source = "provider_vs_finished_score_conflict"
            else:
                effective_best_of = provider_best_of or score_best_of
                best_of_source = "provider_detail" if provider_best_of else score_source
                # Re-parse with the proven format so deciding-set fields are
                # deterministic and validated.
                score = parse_event_score(
                    event,
                    home_is_player1=home == str(match.player1_id),
                    best_of=effective_best_of,
                )

        if score:
            match.stats = {**(match.stats or {}), **score}
            # Provider detail or a completed structured score is stronger than
            # any earlier pre-match inference, so canonical history is corrected
            # rather than preserving a stale guess.
            match.best_of = effective_best_of
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
            "best_of": effective_best_of,
            "best_of_source": best_of_source,
            "identity_verified": True,
            "format_verified": effective_best_of in {3, 5} and parser_status == "available",
        }
        if parser_status == "available" and effective_best_of in {3, 5}:
            updated_raw["_tbt_match_format"] = {
                "schema": 2,
                "status": "verified",
                "best_of": effective_best_of,
                "source": best_of_source,
            }
        elif parser_status == "format_conflict":
            updated_raw["_tbt_match_format"] = {
                "schema": 2,
                "status": "conflict",
                "best_of": None,
                "source": "provider_vs_finished_score",
                "provider_best_of": provider_best_of,
                "score_best_of": score_best_of,
            }
        match.provider_payload = updated_raw
        return "enriched" if score else parser_status
