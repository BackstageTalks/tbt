"""Read-only, opt-in client for private BlinQ charting profiles.

No prediction code imports this module by default. Requires an explicitly
configured server-side token; never expose the token in browser responses.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_REPO = "BackstageTalks/tbt-data"
_BASE = f"https://api.github.com/repos/{_REPO}/contents/tennis/charting/"
_PROFILE = re.compile(r"^profiles/(atp|wta)/(atp|wta)-[a-z0-9-]+\.json\.gz$")
_MAX_BYTES = 8 * 1024 * 1024


class ChartingUnavailable(RuntimeError):
    """Optional charting source cannot be read safely."""


class ChartingClient:
    def __init__(self, token: str | None = None, ref: str = "main", ttl_seconds: int = 3600):
        self._token = token if token is not None else os.getenv("BLINQ_CHARTING_GITHUB_TOKEN", "")
        if not re.fullmatch(r"[a-zA-Z0-9._/-]{1,100}", ref):
            raise ValueError("Invalid charting ref")
        self._ref = ref
        self._ttl = max(0, ttl_seconds)
        self._cache: dict[str, tuple[float, object]] = {}

    def _load(self, path: str, *, compressed: bool = False):
        if not self._token:
            raise ChartingUnavailable("Charting token not configured")
        cached = self._cache.get(path)
        if cached and time.monotonic() - cached[0] < self._ttl:
            return cached[1]
        # GitHub raw media type returns the file bytes, including gzip profiles.
        url = _BASE + path + "?ref=" + self._ref
        request = Request(url, headers={
            "Authorization": "Bearer " + self._token,
            "Accept": "application/vnd.github.raw+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "BlinQ-charting-backend",
        })
        try:
            with urlopen(request, timeout=12) as response:
                payload = response.read(_MAX_BYTES + 1)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ChartingUnavailable("Charting repository unavailable") from exc
        if len(payload) > _MAX_BYTES:
            raise ChartingUnavailable("Charting file exceeds size limit")
        try:
            if compressed:
                # Bound decompressed data as well to prevent gzip bombs.
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
                    payload = stream.read(_MAX_BYTES + 1)
                if len(payload) > _MAX_BYTES:
                    raise ChartingUnavailable("Expanded charting profile exceeds size limit")
            value = json.loads(payload)
        except (ValueError, OSError, EOFError) as exc:
            raise ChartingUnavailable("Invalid charting JSON") from exc
        self._cache[path] = (time.monotonic(), value)
        return value

    def manifest(self) -> dict:
        result = self._load("manifest.json")
        if not isinstance(result, dict) or result.get("schema_version") != 1:
            raise ChartingUnavailable("Unsupported charting manifest")
        return result

    def players(self) -> list[dict]:
        result = self._load("players.json")
        if not isinstance(result, list):
            raise ChartingUnavailable("Invalid player index")
        return result

    def profile(self, path: str) -> dict:
        if not _PROFILE.fullmatch(path):
            raise ValueError("Invalid profile path")
        tour = path.split("/")[1]
        if not path.split("/")[-1].startswith(tour + "-"):
            raise ValueError("Profile tour mismatch")
        result = self._load(path, compressed=True)
        if not isinstance(result, dict):
            raise ChartingUnavailable("Invalid player profile")
        return result
