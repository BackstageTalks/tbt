"""Quota-safe read-only client for Live Tennis API endpoints.

The same server-side key can be used across FREE and paid plans. Historical
point-by-point acquisition remains a separate research workflow; this runtime
client keeps conservative defaults for live/upcoming use.

Safety rules:
- server-side key only (LIVE_TENNIS_API_KEY);
- query the quota-exempt /usage endpoint before billable work;
- keep a configurable daily reserve;
- enforce a strict per-process call cap;
- no automatic retries for billable requests;
- fail closed when quota state cannot be verified.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

from ..errors import ConfigurationError, ProviderError
from .budget import RequestBudgetExceeded

BASE_URL = "https://api.livetennisapi.com/api/public/v1"
DEFAULT_DAILY_RESERVE = 20
DEFAULT_MAX_CALLS = 20
MAX_CONFIGURED_DAILY_CALLS = 1000
DEFAULT_USAGE_TTL_SECONDS = 60.0


class LiveTennisApiClient:
    """Conservative plan-aware adapter for Live Tennis API."""

    def __init__(
        self,
        key: str | None = None,
        *,
        max_calls: int = DEFAULT_MAX_CALLS,
        daily_reserve: int = DEFAULT_DAILY_RESERVE,
        usage_ttl_seconds: float = DEFAULT_USAGE_TTL_SECONDS,
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.key = (key if key is not None else os.getenv("LIVE_TENNIS_API_KEY", "")).strip()
        if not self.key:
            raise ConfigurationError("LIVE_TENNIS_API_KEY is required")

        self.max_calls = max(0, min(MAX_CONFIGURED_DAILY_CALLS, int(max_calls)))
        self.daily_reserve = max(0, min(MAX_CONFIGURED_DAILY_CALLS - 1, int(daily_reserve)))
        self.usage_ttl_seconds = max(0.0, float(usage_ttl_seconds))
        self.request_count = 0

        self.client = client or httpx.Client(timeout=httpx.Timeout(timeout_seconds))
        self._owns_client = client is None
        self._usage_cache: dict[str, Any] | None = None
        self._usage_checked_at = 0.0
        self._usage_request_count_snapshot = 0

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "LiveTennisApiClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.key,
            "Accept": "application/json",
            "User-Agent": "BlinQ-live-tennis/1.0",
        }

    @staticmethod
    def _json(response: httpx.Response, path: str) -> Any:
        if response.status_code == 401:
            raise ConfigurationError("Live Tennis API key is missing, unknown, or disabled")
        if response.status_code == 403:
            raise ProviderError(f"Live Tennis API plan does not allow {path}")
        if response.status_code == 429:
            retry = response.headers.get("Retry-After")
            suffix = f"; retry after {retry}" if retry else ""
            raise RequestBudgetExceeded(f"Live Tennis API rate/quota limit reached{suffix}")
        if response.status_code >= 400:
            raise ProviderError(
                f"Live Tennis API HTTP {response.status_code} for {path}: "
                f"{response.text[:300]}"
            )
        try:
            return response.json() if response.content else {}
        except ValueError as exc:
            raise ProviderError(f"Invalid Live Tennis API JSON for {path}") from exc

    def _get(self, path: str, params: dict[str, Any] | None = None, *, quota_exempt: bool = False) -> Any:
        if not path.startswith("/"):
            raise ValueError("Live Tennis API path must start with /")

        if not quota_exempt:
            self._ensure_budget()

        try:
            response = self.client.get(
                BASE_URL + path,
                headers=self.headers,
                params=params or {},
            )
        except httpx.HTTPError as exc:
            if not quota_exempt:
                self.request_count += 1
            raise ProviderError(f"Live Tennis API request failed for {path}") from exc

        if not quota_exempt:
            self.request_count += 1
        return self._json(response, path)

    def usage(self, *, force: bool = False) -> dict[str, Any]:
        """Return provider usage. /usage is documented as quota-exempt."""
        now = time.monotonic()
        if (
            not force
            and self._usage_cache is not None
            and now - self._usage_checked_at < self.usage_ttl_seconds
        ):
            return self._usage_cache

        payload = self._get("/usage", quota_exempt=True)
        if not isinstance(payload, dict):
            raise ProviderError("Invalid Live Tennis API usage payload")

        today = payload.get("today")
        limits = payload.get("limits")
        if not isinstance(today, dict) or not isinstance(limits, dict):
            raise ProviderError("Live Tennis API usage payload lacks quota fields")
        try:
            remaining = int(today["remaining_day"])
            per_day = int(limits["per_day"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("Live Tennis API usage payload lacks daily quota values") from exc
        if remaining < 0 or per_day <= 0 or remaining > per_day:
            raise ProviderError("Live Tennis API usage payload has invalid daily quota values")

        self._usage_cache = payload
        self._usage_checked_at = now
        self._usage_request_count_snapshot = self.request_count
        return payload

    def remaining_day(self) -> int:
        usage = self.usage()
        provider_remaining = int(usage["today"]["remaining_day"])
        local_since_usage = max(0, self.request_count - self._usage_request_count_snapshot)
        return max(0, provider_remaining - local_since_usage)

    def _ensure_budget(self) -> None:
        if self.request_count >= self.max_calls:
            raise RequestBudgetExceeded("Live Tennis API per-process request cap reached")
        remaining = self.remaining_day()
        if remaining <= self.daily_reserve:
            raise RequestBudgetExceeded(
                f"Live Tennis API daily reserve reached; keeping {self.daily_reserve} calls unused"
            )

    @staticmethod
    def _rows(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def list_matches(self, status: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Live/upcoming board. One provider call."""
        status = str(status or "").strip().lower()
        if status not in {"live", "upcoming"}:
            raise ValueError("status must be live or upcoming")
        limit = max(1, min(100, int(limit)))
        return self._rows(self._get("/matches", {"status": status, "limit": limit}))

    def live_matches(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.list_matches("live", limit=limit)

    def upcoming_matches(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.list_matches("upcoming", limit=limit)

    def fixtures(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Fixture directory. One provider call."""
        limit = max(1, min(100, int(limit)))
        offset = max(0, int(offset))
        return self._rows(self._get("/fixtures", {"limit": limit, "offset": offset}))


    def history_coverage(self) -> dict[str, Any]:
        """Paid history completeness rollup. One provider call."""
        payload = self._get("/history/coverage")
        if not isinstance(payload, dict):
            raise ProviderError("Invalid Live Tennis API history coverage payload")
        return payload

    def history_matches(
        self,
        *,
        from_date: str,
        to_date: str,
        tour: str,
        draw: str = "singles",
        points_complete: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List completed paid-history matches for a controlled research sweep."""
        tour = str(tour or "").strip().lower()
        if tour not in {"atp", "wta", "challenger", "itf", "juniors"}:
            raise ValueError("Unsupported history tour")
        draw = str(draw or "").strip().lower()
        if draw not in {"singles", "doubles"}:
            raise ValueError("Unsupported history draw")
        payload = self._get(
            "/history/matches",
            {
                "from": str(from_date),
                "to": str(to_date),
                "tour": tour,
                "draw": draw,
                "points_complete": "true" if points_complete else "false",
                "limit": max(1, min(100, int(limit))),
                "offset": max(0, int(offset)),
            },
        )
        if not isinstance(payload, dict):
            raise ProviderError("Invalid Live Tennis API history list payload")
        return payload

    def history_tape(self, match_id: int | str, *, complete: bool = True) -> dict[str, Any]:
        """Fetch one paid history tape; complete=True requests the complete basis."""
        token = str(match_id).strip()
        if not token.isdigit() or int(token) <= 0:
            raise ValueError("match_id must be a positive integer")
        params = {"points": "complete"} if complete else {}
        payload = self._get(f"/history/matches/{token}", params)
        if not isinstance(payload, dict):
            raise ProviderError("Invalid Live Tennis API history tape payload")
        return payload

    def match_score(self, match_id: int | str) -> dict[str, Any]:
        """Point-in-time score snapshot. One provider call."""
        token = str(match_id).strip()
        if not token.isdigit() or int(token) <= 0:
            raise ValueError("match_id must be a positive integer")
        payload = self._get(f"/matches/{token}/score")
        if not isinstance(payload, dict):
            raise ProviderError("Invalid Live Tennis API score payload")
        return payload
