from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx

from ..config import Settings, settings
from ..data.provider_context import environment_from_payload, minimize_provider_payload
from ..errors import ConfigurationError
from ..schemas import MatchRecord, PredictionRecord
from ..utils import parse_datetime

logger = logging.getLogger(__name__)

HOT_TIER_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _allow_cold_read() -> bool:
    return str(os.getenv("TBT_ALLOW_SUPABASE_COLD_READ") or "").strip().lower() in {
        "1", "true", "yes", "on"
    }


class SupabaseRepository:
    """Small PostgREST client; keeps the runtime independent of the Supabase SDK."""

    def __init__(self, cfg: Settings = settings) -> None:
        if not cfg.supabase_url or not cfg.supabase_anon_key:
            raise ConfigurationError(
                "SUPABASE_URL and SUPABASE_ANON_KEY are required"
            )

        self.cfg = cfg
        self.base = f"{cfg.supabase_url}/rest/v1"
        self.client = httpx.Client(timeout=cfg.request_timeout_seconds)

    def _headers(
        self,
        write: bool = False,
        prefer: str | None = None,
    ) -> dict[str, str]:
        key = (
            self.cfg.supabase_write_key
            if write
            else (
                self.cfg.supabase_service_role_key
                or self.cfg.supabase_anon_key
            )
        )

        if write and not key:
            raise ConfigurationError(
                "Server-side writes require SUPABASE_SERVICE_ROLE_KEY. "
                "TBT_ALLOW_ANON_WRITES=true exists only for controlled "
                "development environments."
            )

        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

        if prefer:
            headers["Prefer"] = prefer

        return headers

    def _raise(self, response: httpx.Response) -> None:
        if response.is_error:
            raise RuntimeError(
                f"Supabase {response.request.method} "
                f"{response.request.url}: "
                f"HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

    def upsert(
        self,
        table: str,
        rows: list[dict[str, Any]],
        on_conflict: str,
    ) -> int:
        if not rows:
            return 0

        response = self.client.post(
            f"{self.base}/{table}",
            headers=self._headers(
                write=True,
                prefer="resolution=merge-duplicates,return=minimal",
            ),
            params={"on_conflict": on_conflict},
            json=rows,
        )

        self._raise(response)
        return len(rows)

    def insert(
        self,
        table: str,
        row: dict[str, Any],
    ) -> None:
        response = self.client.post(
            f"{self.base}/{table}",
            headers=self._headers(
                write=True,
                prefer="return=minimal",
            ),
            json=row,
        )

        self._raise(response)

    def update(
        self,
        table: str,
        filters: dict[str, str],
        values: dict[str, Any],
    ) -> int:
        response = self.client.patch(
            f"{self.base}/{table}",
            headers=self._headers(
                write=True,
                prefer="return=representation",
            ),
            params=filters,
            json=values,
        )

        self._raise(response)

        data = response.json() if response.content else []
        return len(data) if isinstance(data, list) else 0

    def delete(
        self,
        table: str,
        filters: dict[str, str],
    ) -> int:
        """
        Delete rows matching explicit PostgREST filters.

        Callers must always provide filters; an unfiltered DELETE is
        intentionally refused to protect production data.
        """

        if not filters:
            raise ValueError("Refusing unfiltered Supabase DELETE")

        response = self.client.delete(
            f"{self.base}/{table}",
            headers=self._headers(
                write=True,
                prefer="return=representation",
            ),
            params=filters,
        )

        self._raise(response)

        data = response.json() if response.content else []
        return len(data) if isinstance(data, list) else 0

    def select_all(
        self,
        table: str,
        filters: dict[str, str] | None = None,
        select: str = "*",
        order: str | None = None,
        page_size: int = 1000,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0

        while True:
            end = offset + page_size - 1

            headers = self._headers(write=False)
            headers["Range"] = f"{offset}-{end}"

            params: dict[str, str] = {"select": select}
            params.update(filters or {})

            if order:
                params["order"] = order

            response = self.client.get(
                f"{self.base}/{table}",
                headers=headers,
                params=params,
            )

            self._raise(response)

            chunk = response.json()

            if not isinstance(chunk, list):
                break

            rows.extend(chunk)

            if len(chunk) < page_size:
                break

            if max_rows is not None and len(rows) >= max_rows:
                return rows[:max_rows]

            offset += page_size

        return rows[:max_rows] if max_rows is not None else rows

    def upsert_matches(
        self,
        matches: Iterable[MatchRecord],
    ) -> int:
        materialized = list(matches)
        now = datetime.now(timezone.utc).isoformat()
        rows: list[dict[str, Any]] = []
        environments: list[dict[str, Any]] = []

        for match in materialized:
            row = match.to_storage_dict()
            payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
            environment = environment_from_payload(payload)

            # V20.5: Supabase is the lean operational tier. Never store the raw
            # TennisApi response here again; it was the source of the ~1 GB TOAST
            # growth. Environment has its own table so even compact provider
            # context stays stable and small.
            row["provider_payload"] = minimize_provider_payload(
                payload,
                include_environment=False,
            )
            row["updated_at"] = now
            rows.append(row)

            if environment:
                environments.append(
                    {
                        "match_id": str(match.match_id),
                        "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                        "environment": environment,
                        "updated_at": now,
                    }
                )

        total = 0
        for start in range(0, len(rows), 250):
            total += self.upsert(
                "matches",
                rows[start : start + 250],
                "match_id",
            )

        for start in range(0, len(environments), 250):
            self.upsert(
                "match_environment",
                environments[start : start + 250],
                "match_id",
            )

        return total

    @staticmethod
    def _match_from_row(
        row: dict[str, Any],
    ) -> MatchRecord:
        return MatchRecord(
            match_id=str(row["match_id"]),
            tour=str(row.get("tour") or "").lower(),
            scheduled_at=parse_datetime(row.get("scheduled_at")),
            player1_id=str(row.get("player1_id") or ""),
            player1_name=str(row.get("player1_name") or ""),
            player2_id=str(row.get("player2_id") or ""),
            player2_name=str(row.get("player2_name") or ""),
            surface=str(row.get("surface") or "unknown"),
            tournament=str(row.get("tournament") or ""),
            tournament_id=str(row.get("tournament_id") or ""),
            tournament_level=str(
                row.get("tournament_level") or ""
            ),
            round_name=str(row.get("round_name") or ""),
            player1_rank=row.get("player1_rank"),
            player2_rank=row.get("player2_rank"),
            winner_id=(
                str(row["winner_id"])
                if row.get("winner_id")
                else None
            ),
            status=str(row.get("status") or ""),
            best_of=row.get("best_of"),
            indoor=row.get("indoor"),
            stats=row.get("stats") or {},
            provider_payload=row.get("provider_payload") or {},
        )

    @staticmethod
    def _provider_event_id(
        match: MatchRecord,
    ) -> str | None:
        """
        Return the real provider event id when present.

        No fuzzy player/date matching is used here. If a provider event id
        cannot be established, the match is left untouched by deduplication.
        """

        payload = (
            match.provider_payload
            if isinstance(match.provider_payload, dict)
            else {}
        )

        # Prefer explicit event-id fields.
        for key in (
            "_tbt_provider_event_id",
            "provider_event_id",
            "event_id",
            "eventId",
        ):
            value = payload.get(key)

            if value not in (None, ""):
                return str(value)

        # Some stored payloads contain the original event nested here.
        event = payload.get("event")

        if isinstance(event, dict):
            value = event.get("id")

            if value not in (None, ""):
                return str(value)

        # TennisApi event payloads may also store event id at root.
        value = payload.get("id")

        if value not in (None, ""):
            return str(value)

        return None

    @staticmethod
    def _canonical_match_priority(
        match: MatchRecord,
    ) -> tuple[int, int, int, int, str]:
        """
        Rank duplicate representations of the same provider event.

        Prefer the normalized category-based row produced by the current
        ingestion pipeline and then prefer the richer provider payload.
        """

        payload = (
            match.provider_payload
            if isinstance(match.provider_payload, dict)
            else {}
        )

        source_category_id = payload.get(
            "_tbt_source_category_id"
        )

        tournament = (
            payload.get("tournament")
            if isinstance(payload.get("tournament"), dict)
            else {}
        )

        unique_tournament = (
            tournament.get("uniqueTournament")
            if isinstance(
                tournament.get("uniqueTournament"),
                dict,
            )
            else {}
        )

        richness = sum(
            int(bool(value))
            for value in (
                source_category_id,
                unique_tournament.get("id"),
                unique_tournament.get("name"),
                tournament.get("id"),
                tournament.get("name"),
                match.tournament_id,
                match.round_name,
                match.stats,
            )
        )

        try:
            payload_size = len(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    default=str,
                )
            )
        except Exception:
            payload_size = 0

        return (
            int(source_category_id is not None),
            int(bool(unique_tournament.get("id"))),
            richness,
            payload_size,
            str(match.match_id),
        )

    @classmethod
    def _dedupe_completed_matches(
        cls,
        matches: Iterable[MatchRecord],
    ) -> list[MatchRecord]:
        """
        Canonical deduplication for completed historical matches.

        Only matches sharing the same real provider_event_id are collapsed.

        Matches without provider_event_id are preserved exactly as-is.
        Nothing is deleted from Supabase.
        """

        original = list(matches)

        if not original:
            return []

        by_provider_event: dict[str, list[MatchRecord]] = {}
        without_provider_event: list[MatchRecord] = []

        for match in original:
            provider_event_id = cls._provider_event_id(match)

            if provider_event_id is None:
                without_provider_event.append(match)
                continue

            by_provider_event.setdefault(
                provider_event_id,
                [],
            ).append(match)

        canonical: list[MatchRecord] = []

        for group in by_provider_event.values():
            if len(group) == 1:
                canonical.append(group[0])
                continue

            winner = max(
                group,
                key=cls._canonical_match_priority,
            )

            canonical.append(winner)

        canonical.extend(without_provider_event)

        # Preserve deterministic chronological replay required by
        # FeatureBuilder/backtests.
        canonical.sort(
            key=lambda match: (
                match.scheduled_at,
                str(match.match_id),
            )
        )

        removed = len(original) - len(canonical)

        if removed:
            logger.info(
                "Historical canonical dedupe: "
                "%d -> %d completed matches "
                "(%d duplicate rows ignored)",
                len(original),
                len(canonical),
                removed,
            )

        return canonical

    def get_matches_between(
        self,
        start: datetime,
        end: datetime,
        completed_only: bool = False,
    ) -> list[MatchRecord]:
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)

        if start_utc < HOT_TIER_START and not _allow_cold_read():
            raise RuntimeError(
                "V20.5 egress guard: Supabase match reads before 2025-01-01 are disabled. "
                "Use private GitHub history partitions. Set TBT_ALLOW_SUPABASE_COLD_READ=1 "
                "only for explicit disaster recovery."
            )

        if end_utc <= start_utc:
            return []

        and_parts = [
            f"scheduled_at.lt.{end_utc.isoformat()}"
        ]

        if completed_only:
            and_parts.append("winner_id.not.is.null")

        rows = self.select_all(
            "matches",
            filters={
                "scheduled_at": (
                    f"gte.{start_utc.isoformat()}"
                ),
                "and": (
                    f"({','.join(and_parts)})"
                ),
            },
            order="scheduled_at.asc",
        )

        matches = [self._match_from_row(row) for row in rows]
        matches = self._hydrate_environments(matches)

        if completed_only:
            return self._dedupe_completed_matches(matches)

        return matches

    def upsert_match_environment(
        self,
        match_id: str,
        scheduled_at: datetime,
        environment: dict[str, Any],
    ) -> int:
        if not isinstance(environment, dict) or not environment:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        return self.upsert(
            "match_environment",
            [
                {
                    "match_id": str(match_id),
                    "scheduled_at": scheduled_at.astimezone(timezone.utc).isoformat(),
                    "environment": environment,
                    "updated_at": now,
                }
            ],
            "match_id",
        )

    def update_match_provider_payload(
        self,
        match_id: str,
        provider_payload: dict[str, Any],
    ) -> int:
        """Compatibility shim: compact context in matches, environment separately."""
        environment = environment_from_payload(provider_payload)
        changed = self.update(
            "matches",
            {"match_id": f"eq.{match_id}"},
            {
                "provider_payload": minimize_provider_payload(
                    provider_payload,
                    include_environment=False,
                ),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        if environment:
            rows = self.select_all(
                "matches",
                filters={"match_id": f"eq.{match_id}"},
                select="scheduled_at",
                max_rows=1,
                page_size=1,
            )
            if rows:
                self.upsert_match_environment(
                    match_id,
                    parse_datetime(rows[0].get("scheduled_at")),
                    environment,
                )
        return changed

    def _environment_map(self, match_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        ids = [str(value) for value in match_ids if value]
        if not ids:
            return {}
        result: dict[str, dict[str, Any]] = {}
        try:
            for start in range(0, len(ids), 100):
                chunk = ids[start : start + 100]
                rows = self.select_all(
                    "match_environment",
                    filters={"match_id": f"in.({','.join(chunk)})"},
                    select="match_id,environment",
                    page_size=200,
                )
                for row in rows:
                    env = row.get("environment")
                    if isinstance(env, dict) and env:
                        result[str(row.get("match_id") or "")] = env
        except RuntimeError as exc:
            # Transitional compatibility while the migration has not yet been run.
            text = str(exc).lower()
            if "match_environment" in text or "schema cache" in text:
                logger.warning("match_environment is not available yet; using embedded environment only")
                return {}
            raise
        return result

    def _hydrate_environments(
        self,
        matches: Iterable[MatchRecord],
    ) -> list[MatchRecord]:
        materialized = list(matches)
        env_map = self._environment_map(str(match.match_id) for match in materialized)
        for match in materialized:
            env = env_map.get(str(match.match_id))
            if not env:
                continue
            payload = (
                dict(match.provider_payload)
                if isinstance(match.provider_payload, dict)
                else {}
            )
            payload["_tbt_environment"] = env
            match.provider_payload = payload
        return materialized

    def get_completed_matches(
        self,
        before: datetime | None = None,
    ) -> list[MatchRecord]:
        # Production/operational repository reads are intentionally hot-tier only.
        # Full history belongs to private GitHub partitions; this prevents a forgotten
        # legacy workflow from downloading the old 1 GB matches table again.
        filters: dict[str, str] = {
            "winner_id": "not.is.null",
            "scheduled_at": f"gte.{HOT_TIER_START.isoformat()}",
        }

        if before is not None:
            filters["and"] = (
                f"(scheduled_at.lt.{before.astimezone(timezone.utc).isoformat()})"
            )

        rows = self.select_all(
            "matches",
            filters=filters,
            order="scheduled_at.asc",
        )

        matches = [self._match_from_row(row) for row in rows]
        matches = self._hydrate_environments(matches)
        return self._dedupe_completed_matches(matches)

    def get_completed_matches_since(
        self,
        after: datetime,
        before: datetime | None = None,
    ) -> list[MatchRecord]:
        after_utc = after.astimezone(timezone.utc)
        filters: dict[str, str] = {
            "winner_id": "not.is.null",
            "scheduled_at": f"gte.{after_utc.isoformat()}",
        }
        if before is not None:
            filters["and"] = (
                f"(scheduled_at.lt.{before.astimezone(timezone.utc).isoformat()})"
            )
        rows = self.select_all(
            "matches",
            filters=filters,
            order="scheduled_at.asc",
        )
        matches = [self._match_from_row(row) for row in rows]
        matches = self._hydrate_environments(matches)
        return self._dedupe_completed_matches(matches)

    def get_matches_for_year(
        self,
        year: int,
    ) -> list[MatchRecord]:
        if int(year) < 2025 and not _allow_cold_read():
            raise RuntimeError(
                "V20.5 egress guard: pre-2025 history is stored in private GitHub partitions, "
                "not Supabase."
            )
        start = datetime(
            year,
            1,
            1,
            tzinfo=timezone.utc,
        )

        end = datetime(
            year + 1,
            1,
            1,
            tzinfo=timezone.utc,
        )

        rows = self.select_all(
            "matches",
            filters={
                "scheduled_at": (
                    f"gte.{start.isoformat()}"
                ),
                "and": (
                    f"(scheduled_at.lt.{end.isoformat()},"
                    "winner_id.not.is.null)"
                ),
            },
            order="scheduled_at.asc",
        )

        matches = [self._match_from_row(row) for row in rows]
        matches = self._hydrate_environments(matches)
        return self._dedupe_completed_matches(matches)

    def upsert_predictions(
        self,
        predictions: Iterable[PredictionRecord],
    ) -> int:
        rows = [
            p.to_storage_dict()
            for p in predictions
        ]

        total = 0

        for start in range(0, len(rows), 250):
            total += self.upsert(
                "predictions",
                rows[start : start + 250],
                "match_id,model_version",
            )

        return total

    def delete_future_unsettled_predictions(
        self,
        model_version: str,
        start: datetime,
        end: datetime,
    ) -> int:
        """
        Remove replaceable future rows for one model version only.

        Settled/historical predictions are never touched. This is used
        immediately before a fresh upcoming snapshot is written, so fixtures
        removed or rescheduled by the provider cannot remain visible as
        stale picks.
        """

        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)

        if end_utc <= start_utc:
            return 0

        return self.delete(
            "predictions",
            {
                "model_version": (
                    f"eq.{model_version}"
                ),
                "is_correct": "is.null",
                "scheduled_at": (
                    f"gte.{start_utc.isoformat()}"
                ),
                "and": (
                    f"(scheduled_at.lt."
                    f"{end_utc.isoformat()})"
                ),
            },
        )

    def list_predictions(
        self,
        start: datetime,
        end: datetime,
        tour: str | None = None,
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)

        effective_start = max(
            start.astimezone(timezone.utc),
            now,
        )

        filters = {
            "scheduled_at": (
                f"gte.{effective_start.isoformat()}"
            ),
            "and": (
                f"(scheduled_at.lt."
                f"{end.astimezone(timezone.utc).isoformat()})"
            ),
        }

        if tour:
            filters["tour"] = (
                f"eq.{tour.lower()}"
            )

        return self.select_all(
            "current_predictions",
            filters=filters,
            order="scheduled_at.asc",
        )

    def save_model_version(
        self,
        row: dict[str, Any],
    ) -> None:
        self.upsert(
            "model_versions",
            [row],
            "model_version",
        )

    def latest_model_version(
        self,
    ) -> dict[str, Any] | None:
        rows = self.select_all(
            "model_versions",
            order="created_at.desc",
            max_rows=1,
            page_size=1,
        )

        return rows[0] if rows else None

    def champion_model_version(
        self,
    ) -> dict[str, Any] | None:
        rows = self.select_all(
            "model_versions",
            filters={
                "lifecycle_status": "eq.champion",
            },
            order="promoted_at.desc",
            max_rows=1,
            page_size=1,
        )

        return rows[0] if rows else None

    def latest_challenger_model_version(
        self,
    ) -> dict[str, Any] | None:
        rows = self.select_all(
            "model_versions",
            filters={
                "lifecycle_status": "eq.challenger",
            },
            order="created_at.desc",
            max_rows=1,
            page_size=1,
        )

        return rows[0] if rows else None

    def promote_model(
        self,
        model_version: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if not model_version:
            raise ValueError(
                "model_version is required"
            )

        response = self.client.post(
            f"{self.base}/rpc/promote_model_version",
            headers=self._headers(
                write=True,
            ),
            json={
                "p_model_version": model_version,
                "p_reason": reason,
            },
        )

        self._raise(response)

        data = (
            response.json()
            if response.content
            else {}
        )

        if not isinstance(
            data,
            dict,
        ):
            raise RuntimeError(
                "Unexpected response from "
                "promote_model_version RPC"
            )

        return data

    def reject_model(
        self,
        model_version: str,
        reason: str | None = None,
    ) -> int:
        if not model_version:
            raise ValueError(
                "model_version is required"
            )

        rows = self.select_all(
            "model_versions",
            filters={
                "model_version": (
                    f"eq.{model_version}"
                ),
            },
            max_rows=1,
            page_size=1,
        )

        if not rows:
            raise ValueError(
                f"Unknown model version: "
                f"{model_version}"
            )

        status = str(
            rows[0].get(
                "lifecycle_status"
            )
            or ""
        ).lower()

        if status == "champion":
            raise ValueError(
                "Refusing to reject the active "
                "champion directly. Promote an "
                "approved challenger instead."
            )

        if status == "rejected":
            return 0

        if status != "challenger":
            raise ValueError(
                "Only challenger models may be "
                f"rejected; got status={status!r}"
            )

        now = datetime.now(
            timezone.utc
        ).isoformat()

        return self.update(
            "model_versions",
            {
                "model_version": (
                    f"eq.{model_version}"
                ),
                "lifecycle_status": (
                    "eq.challenger"
                ),
            },
            {
                "lifecycle_status": "rejected",
                "rejected_at": now,
                "promotion_reason": (
                    reason
                    or "Rejected after challenger evaluation"
                ),
            },
        )

    def save_backtest_run(
        self,
        row: dict[str, Any],
    ) -> None:
        self.insert(
            "backtest_runs",
            row,
        )

    def latest_backtest(
        self,
    ) -> dict[str, Any] | None:
        rows = self.select_all(
            "backtest_runs",
            order="created_at.desc",
            max_rows=1,
            page_size=1,
        )

        return rows[0] if rows else None

    def settle_predictions(
        self,
        matches: Iterable[MatchRecord],
    ) -> int:
        changed = 0

        for match in matches:
            if not match.is_completed:
                continue

            rows = self.select_all(
                "predictions",
                filters={
                    "match_id": (
                        f"eq.{match.match_id}"
                    ),
                    "is_correct": "is.null",
                },
                max_rows=100,
            )

            for prediction in rows:
                is_correct = (
                    str(
                        prediction.get(
                            "predicted_winner_id"
                        )
                    )
                    == str(match.winner_id)
                )

                changed += self.update(
                    "predictions",
                    {
                        "match_id": (
                            f"eq.{match.match_id}"
                        ),
                        "model_version": (
                            "eq."
                            f"{prediction['model_version']}"
                        ),
                    },
                    {
                        "result_winner_id": (
                            match.winner_id
                        ),
                        "is_correct": is_correct,
                    },
                )

        return changed
