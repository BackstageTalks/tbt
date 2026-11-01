"""No-paid-request activation probe for private Tennis API raw cache.

Only enable the authenticated remote cache after the deployed Azure runtime
has successfully read its private store. Missing *undeployed* optional route
keeps the previous guarded collector; a broken deployed service fails closed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError


class CacheCapabilityError(RuntimeError):
    pass


class DenyWorkerTokenRedirect(HTTPRedirectHandler):
    """Never forward the internal worker token to a redirected host."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def cache_endpoint(budget_url, explicit=""):
    budget = urlsplit(str(budget_url))
    if (budget.scheme != "https" or not budget.netloc
            or budget.path != "/api/v1/internal/api-budget/reserve"
            or budget.query or budget.fragment):
        raise CacheCapabilityError("Invalid configured budget endpoint")
    target = urlunsplit((budget.scheme, budget.netloc,
                         "/api/v1/internal/tennis-raw-cache", "", ""))
    if explicit and str(explicit) != target:
        raise CacheCapabilityError("Cache endpoint is not the approved budget origin")
    return target


def verify_cache_service(endpoint, token, *, explicit=False, opener=None):
    if opener is None:
        opener = build_opener(DenyWorkerTokenRedirect()).open
    if not token:
        raise CacheCapabilityError("Missing internal worker credential")
    req = Request(endpoint + "?key=" + "0" * 64 + "&max_age=0",
                  method="GET",
                  headers={"X-Blinq-Worker-Token": token, "Accept": "application/json"})
    try:
        with opener(req, timeout=7) as resp:
            status = int(getattr(resp, "status", 0))
            content = resp.read(4096)
    except HTTPError as exc:
        if exc.code == 404 and not explicit:
            return False
        raise CacheCapabilityError("Private raw cache endpoint unavailable") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise CacheCapabilityError("Private raw cache network unavailable") from exc
    if status != 200:
        if status == 404 and not explicit:
            return False
        raise CacheCapabilityError("Private cache endpoint did not verify")
    try:
        data = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise CacheCapabilityError("Invalid cache capability envelope") from exc
    if (not isinstance(data, dict) or data.get("ok") is not True
            or data.get("status") != "miss"):
        raise CacheCapabilityError("Private cache storage readback unavailable")
    return True


def main():
    explicit = os.getenv("BLINQ_TENNIS_RAW_CACHE_URL", "").strip()
    endpoint = cache_endpoint(os.getenv("BLINQ_SHARED_API_BUDGET_URL", ""), explicit)
    token = os.getenv("BLINQ_SHARED_API_BUDGET_TOKEN", "").strip()
    verified = verify_cache_service(endpoint, token, explicit=bool(explicit))
    if not verified:
        print("Private raw cache endpoint not yet deployed; keeping guarded original collector.")
        return
    env_file = os.getenv("GITHUB_ENV", "").strip()
    if not env_file:
        raise CacheCapabilityError("Missing GitHub environment file")
    with Path(env_file).open("a", encoding="utf-8") as out:
        out.write(f"BLINQ_TENNIS_RAW_CACHE_URL={endpoint}\n")
        # The raw endpoint is introduced after the globally paced budget
        # server. A stale budget runtime must now fail closed, not allow 6/s
        # bypass by old clients during a staged rollout.
        out.write("BLINQ_SHARED_RPS_REQUIRED=true\n")
    print("Private raw cache and shared 6/s server capability verified (zero provider calls).")


if __name__ == "__main__":
    main()
