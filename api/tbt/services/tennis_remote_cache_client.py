"""Authenticated HTTP adapter for private Azure raw cache across GitHub jobs."""
from __future__ import annotations

import os
import time
import uuid

import httpx

from .tennis_response_cache import RawCacheUnavailable, cache_identity, MAX_AGE


class HttpRawResponseCache:
    def __init__(self, endpoint, token):
        if (not isinstance(endpoint, str) or not endpoint.startswith("https://")
                or "/api/v1/internal/tennis-raw-cache" not in endpoint or not token):
            raise RawCacheUnavailable("Remote raw cache requires authenticated HTTPS")
        self.url = endpoint
        self.token = token
        self.client = httpx.Client(timeout=7.0)
        self.metrics = {"cache_hits": 0, "upstream_loads": 0,
                        "inflight_wait_polls": 0, "negative_not_cached": 0,
                        "oversized_not_cached": 0}

    def close(self):
        self.client.close()

    def _request(self, method, *, params=None, body=None):
        try:
            resp = self.client.request(
                method, self.url, params=params, json=body,
                headers={"X-Blinq-Worker-Token": self.token},
            )
            if resp.status_code != 200:
                raise RawCacheUnavailable("Private remote cache service unavailable")
            data = resp.json()
            if not isinstance(data, dict) or data.get("ok") is not True:
                raise RawCacheUnavailable("Unverified remote cache response")
            status = data.get("status")
            if status not in {"hit", "miss", "busy", "claimed", "stored", "aborted", "oversize"}:
                raise RawCacheUnavailable("Unknown remote cache state")
            return data
        except RawCacheUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise RawCacheUnavailable("Private raw cache coordination failed") from exc

    def get_or_load(self, *, provider, host, endpoint, params=None,
                    kind="finished_statistics", parser_version="unknown",
                    loader, max_age=None, wait_seconds=15):
        if kind not in MAX_AGE:
            raise ValueError("Unknown cache freshness class")
        ttl = MAX_AGE[kind] if max_age is None else min(MAX_AGE[kind], max_age)
        if ttl <= 0:
            self.metrics["upstream_loads"] += 1
            return loader()
        key, _ = cache_identity(provider, host, endpoint, params)
        owner = uuid.uuid4().hex
        remote = self._request("GET", params={"key": key, "max_age": ttl})
        if remote["status"] == "hit":
            self.metrics["cache_hits"] += 1
            return remote["payload"]
        if remote["status"] == "miss":
            remote = self._request("POST", body={
                "action": "claim", "key": key, "owner": owner,
                "max_age": ttl,
            })
        if remote["status"] == "hit":
            self.metrics["cache_hits"] += 1
            return remote["payload"]
        if remote["status"] == "busy":
            deadline = time.monotonic() + max(0.0, wait_seconds)
            while time.monotonic() < deadline:
                time.sleep(0.3)
                self.metrics["inflight_wait_polls"] += 1
                current = self._request("GET", params={"key": key, "max_age": ttl})
                if current["status"] == "hit":
                    self.metrics["cache_hits"] += 1
                    return current["payload"]
            raise RawCacheUnavailable("Remote raw request already in progress")
        if remote["status"] != "claimed":
            raise RawCacheUnavailable("Private raw cache lease not granted")
        try:
            self.metrics["upstream_loads"] += 1
            payload = loader()
            if not isinstance(payload, (dict, list)):
                raise RawCacheUnavailable("Non-JSON provider response")
            if kind == "finished_statistics" and (
                    not isinstance(payload, dict) or not payload.get("statistics")):
                self.metrics["negative_not_cached"] += 1
                self._request("POST", body={"action": "abort", "key": key, "owner": owner})
                return payload
            saved = self._request("POST", body={
                "action": "publish", "key": key, "owner": owner,
                "parser_version": str(parser_version), "payload": payload,
            })
            if saved["status"] == "oversize":
                self.metrics["oversized_not_cached"] += 1
                self._request("POST", body={"action": "abort", "key": key, "owner": owner})
            elif saved["status"] != "stored":
                raise RawCacheUnavailable("Unverified remote raw persistence")
            return payload
        except BaseException:
            try:
                self._request("POST", body={"action": "abort", "key": key, "owner": owner})
            except RawCacheUnavailable:
                pass  # Lease expiry is deliberately conservative.
            raise
