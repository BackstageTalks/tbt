from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx

from ..config import Settings, settings
from ..errors import ConfigurationError
from ..schemas import MatchRecord, PredictionRecord
from ..utils import parse_datetime

logger = logging.getLogger(__name__)


class SupabaseRepository:
    """Small PostgREST client; keeps the runtime independent of the Supabase SDK."""

    def __init__(self, cfg: Settings = settings) -> None:
        if not cfg.supabase_url or not cfg.supabase_anon_key:
            raise ConfigurationError("SUPABASE_URL and SUPABASE_ANON_KEY are required")
        self.cfg = cfg
        self.base = f"{cfg.supabase_url}/rest/v1"
        self.client = httpx.Client(timeout=cfg.request_timeout_seconds)

    def _headers(self, write: bool = False, prefer: str | None = None) -> dict[str, str]:
        key = self.cfg.supabase_write_key if write else (self.cfg.supabase_service_role_key or self.cfg.supabase_anon_key)
        if write and not key:
            raise ConfigurationError(
                "Server-side writes require SUPABASE_SERVICE_ROLE_KEY. "
                "TBT_ALLOW_ANON_WRITES=true exists only for controlled development environments."
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
                f"Supabase {response.request.method} {response.request.url}: "
                f"HTTP {response.status_code}: {response.text[:500]}"
            )

    def upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: str) -> int:
        if not rows:
            return 0
        response = self.client.post(
            f"{self.base}/{table}",
            headers=self._headers(write=True, prefer="resolution=merge-duplicates,return=minimal"),
            params={"on_conflict": on_conflict},
            json=rows,
        )
        self._raise(response)
        return len(rows)

    def insert(self, table: str, row: dict[str, Any]) -> None:
        response = self.client.post(
            f"{self.base}/{table}",
            headers=self._headers(write=True, prefer="return=minimal"),
            json=row,
        )
        self._raise(response)

    def update(self, table: str, filters: dict[str, str], values: dict[str, Any]) -> int:
        response = self.client.patch(
            f"{self.base}/{table}",
            headers=self._headers(write=True, prefer="return=representation"),
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
        """Delete rows matching explicit PostgREST filters.

        Callers must always provide filters; an unfiltered DELETE is intentionally
        refused to protect production data.
        """
        if not filters:
            raise ValueError("Refusing unfiltered Supabase DELETE")
        response = self.client.delete(
            f"{self.base}/{table}",
            headers=self._headers(write=True, prefer="return=representation"),
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
            response = self.client.get(f"{self.base}/{table}", headers=headers, params=params)
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

    def upsert_matches(self, matches: Iterable[MatchRecord]) -> int:
        rows = [m.to_storage_dict() for m in matches]
        # provider_payload can be large; storing it is intentional for audit/re-normalisation.
        total = 0
        for start in range(0, len(rows), 250):
            total += self.upsert("matches", rows[start : start + 250], "match_id")
        return total

    @staticmethod
    def _match_from_row(row: dict[str, Any]) -> MatchRecord:
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
            tournament_level=str(row.get("tournament_level") or ""),
            round_name=str(row.get("round_name") or ""),
            player1_rank=row.get("player1_rank"),
            player2_rank=row.get("player2_rank"),
            winner_id=str(row["winner_id"]) if row.get("winner_id") else None,
            status=str(row.get("status") or ""),
            best_of=row.get("best_of"),
            indoor=row.get("indoor"),
            stats=row.get("stats") or {},
            provider_payload=row.get("provider_payload") or {},
        )

    def get_completed_matches(self, before: datetime | None = None) -> list[MatchRecord]:
        filters = {"winner_id": "not.is.null"}
        if before is not None:
            filters["scheduled_at"] = f"lt.{before.astimezone(timezone.utc).isoformat()}"
        rows = self.select_all("matches", filters=filters, order="scheduled_at.asc")
        return [self._match_from_row(row) for row in rows]

    def get_matches_for_year(self, year: int) -> list[MatchRecord]:
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        rows = self.select_all(
            "matches",
            filters={
                "scheduled_at": f"gte.{start.isoformat()}",
                "and": f"(scheduled_at.lt.{end.isoformat()},winner_id.not.is.null)",
            },
            order="scheduled_at.asc",
        )
        return [self._match_from_row(row) for row in rows]

    def upsert_predictions(self, predictions: Iterable[PredictionRecord]) -> int:
        rows = [p.to_storage_dict() for p in predictions]
        total = 0
        for start in range(0, len(rows), 250):
            total += self.upsert(
                "predictions", rows[start : start + 250], "match_id,model_version"
            )
        return total

    def delete_future_unsettled_predictions(
        self,
        model_version: str,
        start: datetime,
        end: datetime,
    ) -> int:
        """Remove replaceable future rows for one model version only.

        Settled/historical predictions are never touched. This is used immediately
        before a fresh upcoming snapshot is written, so fixtures removed or
        rescheduled by the provider cannot remain visible as stale picks.
        """
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)
        if end_utc <= start_utc:
            return 0
        return self.delete(
            "predictions",
            {
                "model_version": f"eq.{model_version}",
                "is_correct": "is.null",
                "scheduled_at": f"gte.{start_utc.isoformat()}",
                "and": f"(scheduled_at.lt.{end_utc.isoformat()})",
            },
        )

    def list_predictions(
        self,
        start: datetime,
        end: datetime,
        tour: str | None = None,
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        effective_start = max(start.astimezone(timezone.utc), now)
        filters = {
            "scheduled_at": f"gte.{effective_start.isoformat()}",
            "and": f"(scheduled_at.lt.{end.astimezone(timezone.utc).isoformat()})",
        }
        if tour:
            filters["tour"] = f"eq.{tour.lower()}"
        return self.select_all("current_predictions", filters=filters, order="scheduled_at.asc")

    def save_model_version(self, row: dict[str, Any]) -> None:
        self.upsert("model_versions", [row], "model_version")

    def latest_model_version(self) -> dict[str, Any] | None:
        rows = self.select_all(
            "model_versions", order="created_at.desc", max_rows=1, page_size=1
        )
        return rows[0] if rows else None

    def save_backtest_run(self, row: dict[str, Any]) -> None:
        self.insert("backtest_runs", row)

    def latest_backtest(self) -> dict[str, Any] | None:
        rows = self.select_all("backtest_runs", order="created_at.desc", max_rows=1, page_size=1)
        return rows[0] if rows else None

    def settle_predictions(self, matches: Iterable[MatchRecord]) -> int:
        changed = 0
        for match in matches:
            if not match.is_completed:
                continue
            rows = self.select_all(
                "predictions",
                filters={"match_id": f"eq.{match.match_id}", "is_correct": "is.null"},
                max_rows=100,
            )
            for prediction in rows:
                is_correct = str(prediction.get("predicted_winner_id")) == str(match.winner_id)
                changed += self.update(
                    "predictions",
                    {
                        "match_id": f"eq.{match.match_id}",
                        "model_version": f"eq.{prediction['model_version']}",
                    },
                    {"result_winner_id": match.winner_id, "is_correct": is_correct},
                )
        return changed
