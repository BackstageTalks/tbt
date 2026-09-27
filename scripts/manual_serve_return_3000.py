"""Manual, capped serve/return fetch. Stages raw provider responses only; never mutates production."""
from __future__ import annotations
import argparse
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from _bootstrap import ROOT
from audit_environment_release import download_committed_history
from audit_statistics_inventory import _quality_ready
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities

def event_id(match):
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    for key in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    event = payload.get("event")
    if isinstance(event, dict) and event.get("id") not in (None, ""):
        return str(event["id"])
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--history-dir", default=".cache/tbt/manual-serve-return/history")
    ap.add_argument("--out-dir", default=".cache/tbt/manual-serve-return/output")
    ap.add_argument("--previous-dir", default=".cache/tbt/manual-serve-return/previous")
    args = ap.parse_args()
    if not 1 <= args.limit <= 3000:
        raise SystemExit("Request cap must be between 1 and 3000")
    token = os.environ.get("RAPIDAPI_KEY", "").strip()
    host = os.environ.get("TENNISAPI_RAPIDAPI_HOST", "").strip()
    template = os.environ.get("TENNISAPI_STATS_URL_TEMPLATE", "").strip()
    if not token or not host or not template or "{event_id}" not in template or not template.startswith("https://"):
        raise SystemExit("Missing RAPIDAPI_KEY, TENNISAPI_RAPIDAPI_HOST or HTTPS TENNISAPI_STATS_URL_TEMPLATE containing {event_id}; no paid requests made.")
    repository = os.environ.get("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
    directory = Path(args.history_dir)
    download_committed_history(ReleaseStore(repository, "tbt-data-v1", directory), directory)
    matches, safety = sanitize_history_identities(load_partitions(directory))
    candidates = []
    seen = set()
    counts = Counter()
    for m in matches:
        if not m.is_completed or (_quality_ready(m.stats or {}, "p1") and _quality_ready(m.stats or {}, "p2")):
            continue
        eid = event_id(m)
        if not eid:
            counts["missing_provider_event_id"] += 1
            continue
        if eid in seen:
            counts["duplicate_event_id"] += 1
            continue
        seen.add(eid)
        candidates.append((m, eid))
    # Highest yield: partial quality first, then recent finished matches.
    candidates.sort(key=lambda pair: (
        -int(_quality_ready(pair[0].stats or {}, "p1") or _quality_ready(pair[0].stats or {}, "p2")),
        -sum(v is not None for v in (pair[0].stats or {}).values()),
        -pair[0].scheduled_at.timestamp(),
    ))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "provider_responses.jsonl"
    summary = out / "summary.json"
    # Previous artifacts are cumulative. Reuse raw responses privately and skip paid re-fetches.
    previous_files = sorted(Path(args.previous_dir).rglob("provider_responses.jsonl"))
    previous = {}
    for previous_file in previous_files:
        for line in previous_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            eid = str(row.get("event_id", "")).strip()
            if not eid or "provider_response" not in row:
                raise SystemExit(f"Invalid previous staging row in {previous_file}; refusing paid calls")
            previous.setdefault(eid, row)
    counts["reused_previous_responses"] = len(previous)
    candidates = [(m, eid) for m, eid in candidates if eid not in previous]
    calls = 0
    session = requests.Session()
    headers = {"X-RapidAPI-Key": token, "X-RapidAPI-Host": host, "Accept": "application/json"}
    # Stay below the provider limit of 6 requests/second.
    min_interval = 0.25  # 4 requests/second
    last_request_at = 0.0
    # Paid cap includes retries.
    try:
        with raw.open("w", encoding="utf-8") as stream:
            for row in previous.values():
                stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\\n")
            stream.flush()
            for match, eid in candidates:
                if calls >= args.limit:
                    break
                url = template.replace("{event_id}", quote(eid, safe=""))
                try:
                    response = None
                    for retry in range(3):
                        if calls >= args.limit:
                            break
                        delay = min_interval - (time.monotonic() - last_request_at)
                        if delay > 0:
                            time.sleep(delay)
                        last_request_at = time.monotonic()
                        calls += 1
                        counts["paid_requests_attempted"] = calls
                        response = session.get(url, headers=headers, timeout=25)
                        counts[f"http_{response.status_code}"] += 1
                        if response.status_code != 429:
                            break
                        counts["rate_limit_retries"] += 1
                        if retry < 2 and calls < args.limit:
                            retry_after = response.headers.get("Retry-After", "")
                            try:
                                wait = max(1.0, min(float(retry_after), 120.0))
                            except ValueError:
                                wait = min(15.0 * (2 ** retry), 60.0)
                            print(f"HTTP 429: waiting {wait:g}s before retry", flush=True)
                            time.sleep(wait)
                    if response is None:
                        break
                    status = response.status_code
                    if status in (401, 403, 429):
                        counts["stopped_on_auth_or_rate_limit"] += 1
                        break
                    if status >= 500:
                        # Do not retry: retries would consume quota.
                        continue
                    if status != 200:
                        continue
                    payload = response.json()
                    if payload in (None, {}, [], ""):
                        counts["empty_response"] += 1
                        continue
                    # Do not assume provider schema: raw staging needs explicit parser validation before import.
                    stream.write(json.dumps({
                        "match_id": str(match.match_id), "event_id": eid,
                        "tour": str(match.tour), "scheduled_at": match.scheduled_at.isoformat(),
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "provider_response": payload,
                    }, ensure_ascii=False, default=str) + "\n")
                    stream.flush()
                    counts["staged_nonempty_responses"] += 1
                except (requests.RequestException, ValueError) as exc:
                    counts["request_or_json_error"] += 1
                    print(f"Event {eid}: {type(exc).__name__}", flush=True)
                if calls % 100 == 0:
                    print(f"Attempted {calls}/{args.limit}; staged {counts['staged_nonempty_responses']}", flush=True)
    finally:
        report = {
            "schema": 1, "production_mutated": False, "import_ready": False,
            "hard_cap": args.limit, "paid_requests_attempted": calls,
            "candidate_count": len(candidates), "reused_previous_responses": len(previous),
            "total_staged_responses": len(previous) + counts["staged_nonempty_responses"],
            "identity_safety": safety,
            "counts": dict(counts), "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": "Raw provider responses require schema validation and canonical matching before private history import.",
        }
        summary.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, default=str), flush=True)

if __name__ == "__main__":
    main()
