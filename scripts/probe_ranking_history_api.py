"""Probe TennisAPI ranking-history endpoint shapes with strict shared-budget accounting.

This intentionally uses a tiny, fixed request set against one known ATP player.
It never writes production data and disables provider retries to keep the probe
request count deterministic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.providers.rapidapi import RapidTennisClient


def _shape(value):
    if isinstance(value, dict):
        return {
            "type": "dict",
            "keys": sorted(str(k) for k in value.keys())[:40],
            "sample": {
                str(k): _shape(v)
                for k, v in list(value.items())[:8]
            },
        }
    if isinstance(value, list):
        return {
            "type": "list",
            "len": len(value),
            "first": _shape(value[0]) if value else None,
        }
    return {"type": type(value).__name__}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--player-id", type=int, default=275923)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-requests", type=int, default=8)
    args = ap.parse_args()

    pid = int(args.player_id)
    candidates = [
        f"/api/tennis/player/{pid}/rankings",
        f"/api/tennis/player/{pid}/rankings/history",
        f"/api/tennis/player/{pid}/ranking-history",
        f"/tennis/v2/ranking/atp/player/{pid}/history",
        f"/api/tennis/ranking/atp/player/{pid}/history",
        f"/api/tennis/player/{pid}/rankings?months=24",
    ]

    client = RapidTennisClient()
    client.retry_attempts = 1
    client.request_limit = max(1, min(int(args.max_requests), 8))
    results = []
    try:
        for raw in candidates:
            if client.request_count >= client.request_limit:
                break
            path, _, query = raw.partition("?")
            params = {}
            if query:
                for part in query.split("&"):
                    key, _, value = part.partition("=")
                    if key:
                        params[key] = value
            row = {"path": path, "params": params}
            try:
                payload = client._get(path, params=params or None, enrichment=True)
                row["ok"] = payload is not None
                row["shape"] = _shape(payload)
            except Exception as exc:
                row["ok"] = False
                row["error_type"] = type(exc).__name__
                row["error"] = str(exc)[:300]
            results.append(row)
    finally:
        remaining = client.rate_limit_remaining
        count = client.request_count
        client.close()

    report = {
        "schema": 1,
        "player_id": pid,
        "request_count": count,
        "provider_remaining_header": remaining,
        "rapidapi_requests": count,
        "production_mutated": False,
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
