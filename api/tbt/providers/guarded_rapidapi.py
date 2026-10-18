"""Mandatory fail-closed adapter for one-off HTTP calls to RapidAPI providers.

Use this for probes that do not fit RapidTennisClient's fixed endpoint schema.
It shares the SAME provider-day atomic reservation ledger and minimum 750-call
headroom as the canonical TennisAPI client. No direct request is permitted.
"""
from __future__ import annotations

import os
import time
from urllib.parse import urlsplit

import httpx

from .budget import RequestBudgetExceeded
from .rapidapi import (
    DEFAULT_PROVIDER_REQUEST_RESERVE,
    _enforce_provider_day_hard_stop,
    _provider_request_reserve,
)
from .shared_budget import SharedBudgetUnavailable, from_environment


class GuardedRapidApiHttp:
    def __init__(self, key: str, host: str, *, budget=None, timeout: float = 20.0):
        self.key = str(key or "").strip()
        self.host = str(host or "").strip().lower()
        if not self.key or not self.host.endswith(".p.rapidapi.com"):
            raise ValueError("A RapidAPI subscription key and approved host are required")
        self.budget = budget if budget is not None else from_environment()
        if self.budget is None:
            raise SharedBudgetUnavailable("Paid RapidAPI calls require an atomic shared budget")
        self.client = httpx.Client(timeout=timeout)
        self.attempts = 0
        self.remaining = None
        self._last_request_at = 0.0

    def close(self):
        try:
            self.client.close()
        finally:
            self.budget.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def get(self, url: str, *, params=None, timeout: float | None = None):
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.netloc.lower() != self.host
                or not parts.path.startswith("/")):
            raise ValueError("Paid RapidAPI request outside configured HTTPS provider host")
        _enforce_provider_day_hard_stop()
        reserve = _provider_request_reserve()
        if self.remaining is not None and self.remaining <= reserve:
            raise RequestBudgetExceeded("Provider remaining reserve reached")
        # Never spend without an atomic ETag-backed reservation, including
        # manual research, provider probes and retries.
        self.budget()
        # Upstream plan is limited to 6 requests/second.
        interval = 0.25 - (time.monotonic() - self._last_request_at)
        if interval > 0:
            time.sleep(interval)
        self._last_request_at = time.monotonic()
        self.attempts += 1
        options = {"params": params}
        if timeout is not None:
            options["timeout"] = timeout
        response = self.client.get(
            url,
            headers={
                "X-RapidAPI-Key": self.key,
                "X-RapidAPI-Host": self.host,
                "Accept": "application/json",
            },
            **options,
        )
        remaining = response.headers.get("x-ratelimit-requests-remaining")
        try:
            if remaining is None or not str(remaining).strip().isdigit():
                raise ValueError("Missing or invalid provider quota")
            self.remaining = int(remaining)
        except (ValueError, TypeError) as exc:
            raise RequestBudgetExceeded(
                "Provider remaining-call header unavailable or malformed"
            ) from exc
        # Current billable attempt has already happened. Never allow another
        # request once the provider has reached the safety reserve.
        if self.remaining <= reserve:
            raise RequestBudgetExceeded("Provider remaining reserve reached")
        return response
