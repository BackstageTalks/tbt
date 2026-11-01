"""Load prior hourly adaptation only from independent, persisted CDB evidence.

The previous GitHub Actions artifact contains no raw provider body or API key.
Missing or incompatible evidence safely falls back to the deterministic queue.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

GROUP = re.compile(r"^(atp|wta):(20(?:1[6-9]|2[0-6])):(serve_return|ace_df)$")
WINDOW = timedelta(days=7)


def validated_prior(data, *, parser_version, now=None):
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("Unrecognized prior evidence")
    if data.get("status") not in ("VERIFIED_CDB_GAIN", "VERIFIED_NO_GAIN"):
        raise ValueError("Prior CDB readback is not verified")
    if data.get("parser_version") != parser_version:
        raise ValueError("Prior evidence from different parser version")
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise ValueError("Naive now")
    try:
        stamped = datetime.fromisoformat(str(data["reported_at_utc"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise ValueError("Prior evidence lacks an acquisition timestamp") from exc
    if stamped.tzinfo is None or not timedelta(0) <= observed - stamped <= WINDOW:
        raise ValueError("Stale or future prior evidence")
    try:
        total_calls = int(data["requests_including_retries"])
        total_fields = int(data["persisted_new_statistic_values"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Missing prior evidence totals") from exc
    if min(total_calls, total_fields) < 0:
        raise ValueError("Negative prior totals")
    cohorts = data.get("cohorts")
    if not isinstance(cohorts, list):
        raise ValueError("No cohort evidence")
    parsed = {}
    for item in cohorts:
        if not isinstance(item, dict):
            raise ValueError("Corrupt cohort evidence")
        name = item.get("cohort")
        if not isinstance(name, str) or not GROUP.fullmatch(name) or name in parsed:
            raise ValueError("Invalid or duplicated cohort identity")
        try:
            calls = int(item["api_requests"])
            fields = int(item["new_fields"])
            ready = int(item["full_serve_return_rows"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid cohort yield") from exc
        if min(calls, fields, ready) < 0 or (fields > 0 and calls == 0) or ready > fields:
            raise ValueError("Impossible cohort yield")
        parsed[name] = {"api_requests": calls, "new_fields": fields,
                        "full_serve_return_rows": ready}
    if sum(x["api_requests"] for x in parsed.values()) != total_calls:
        raise ValueError("Provider calls mismatch")
    if sum(x["new_fields"] for x in parsed.values()) != total_fields:
        raise ValueError("Persisted CDB fields mismatch")
    return parsed


def read_prior(path, *, parser_version):
    if not path:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return validated_prior(raw, parser_version=parser_version)
