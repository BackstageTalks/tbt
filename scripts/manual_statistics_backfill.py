"""Bounded, private TennisAPI statistics fetch. Stages raw provider data; never silently merges it."""
from __future__ import annotations
import argparse
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from _bootstrap import ROOT
from audit_environment_release import download_committed_history
from audit_statistics_inventory import _quality_ready
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities

OUT = ROOT / ".cache/tbt/manual-statistics"
API_HOST = "tennisapi1.p.rapidapi.com"
API_URL = "https://" + API_HOST + "/api/tennis/event/{event_id}/statistics"

def event_id(match):
    p = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    marker = p.get("_tbt_statistics")
    identity = p.get("_tbt_event_identity")
    event = p.get("event")
    candidates = [
        p.get("_tbt_provider_event_id"), p.get("provider_event_id"),
        (identity or {}).get("event_id") if isinstance(identity, dict) else None,
        (event or {}).get("id") if isinstance(event, dict) else None,
        p.get("event_id"), p.get("eventId"),
        (marker or {}).get("event_id") if isinstance(marker, dict) else None,
    ]
    for value in candidates:
        if value is not None and str(value).isdigit() and int(value) > 0:
            return str(value)
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-requests", type=int, required=True)
    ap.add_argument("--max-runtime-minutes", type=int, default=105)
    args = ap.parse_args()
    if not 1 <= args.max_requests <= 3000:
        ap.error("max-requests must be 1..3000")
    if not 1 <= args.max_runtime_minutes <= 105:
        ap.error("max-runtime-minutes must be 1..105")
    token = os.environ.get("RAPIDAPI_KEY", "").strip()
    gh_token = os.environ.get("GH_TOKEN", "").strip()
    if not token or not gh_token:
        raise SystemExit("RAPIDAPI_KEY and GH_TOKEN are required")
    OUT.mkdir(parents=True, exist_ok=True)
    repo = os.environ.get("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
    history = OUT / "history"
    download_committed_history(ReleaseStore(repo, "tbt-data-v1", history), history)
    matches, safety = sanitize_history_identities(load_partitions(history))
    candidates = []
    seen = set()
    skipped = Counter()
    for match in matches:
        if not match.is_completed:
            continue
        stats = match.stats if isinstance(match.stats, dict) else {}
        if _quality_ready(stats, "p1") and _quality_ready(stats, "p2"):
            skipped["already_ready"] += 1
            continue
        eid = event_id(match)
        if not eid:
            skipped["no_provider_event_id"] += 1
            continue
        if eid in seen:
            skipped["duplicate_event_id"] += 1
            continue
        seen.add(eid)
        category = 0 if _quality_ready(stats, "p1") or _quality_ready(stats, "p2") else 1 if any(v is not None for v in stats.values()) else 2
        candidates.append((category, -match.scheduled_at.timestamp(), eid, str(match.match_id), str(match.tour or "")))
    candidates.sort()
    report = {
        "schema": 1, "mode": "raw_private_staging_only", "max_requests": args.max_requests,
        "requests_attempted": 0, "http_200": 0, "responses_with_statistics": 0,
        "http_errors": {}, "candidate_events": len(candidates),
        "skipped": dict(skipped), "identity_safety": safety,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    deadline = time.monotonic() + args.max_runtime_minutes * 60
    error_counts = Counter()
    response_path = OUT / "responses.jsonl"
    try:
        with response_path.open("w", encoding="utf-8") as output:
            for _, _, eid, match_id, tour in candidates:
                if report["requests_attempted"] >= args.max_requests:
                    report["stop_reason"] = "request_cap"
                    break
                if time.monotonic() >= deadline:
                    report["stop_reason"] = "runtime_cap"
                    break
                request = urllib.request.Request(
                    API_URL.format(event_id=eid),
                    headers={"X-RapidAPI-Key": token, "X-RapidAPI-Host": API_HOST, "Accept": "application/json"},
                )
                # Count before making the HTTP request; retries are intentionally disabled.
                report["requests_attempted"] += 1
                try:
                    with urllib.request.urlopen(request, timeout=18) as response:
                        code = response.status
                        payload = json.loads(response.read(3_000_000))
                except urllib.error.HTTPError as exc:
                    code = exc.code
                    error_counts[str(code)] += 1
                    if code in (401, 403, 429):
                        report["stop_reason"] = "provider_auth_or_quota_error_" + str(code)
                        break
                    if error_counts[str(code)] >= 30:
                        report["stop_reason"] = "repeated_http_" + str(code)
                        break
                    continue
                except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                    error_counts["network_or_parse"] += 1
                    if error_counts["network_or_parse"] >= 10:
                        report["stop_reason"] = "repeated_network_or_parse_errors"
                        break
                    continue
                if code != 200:
                    error_counts[str(code)] += 1
                    continue
                report["http_200"] += 1
                data = payload.get("data") if isinstance(payload, dict) else None
                # Keep all successful payloads for schema-aware normalization after inspection.
                if isinstance(data, dict) and (data.get("statistics") or data.get("periods")):
                    report["responses_with_statistics"] += 1
                output.write(json.dumps({
                    "provider": "tennisapi1", "event_id": eid, "match_id": match_id,
                    "tour": tour, "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                    "response": payload,
                }, ensure_ascii=False) + "\n")
                output.flush()
                if report["requests_attempted"] <= 10 and report["http_200"] == 0:
                    report["stop_reason"] = "no_successful_provider_responses"
                    break
            else:
                report["stop_reason"] = "candidate_list_exhausted"
    finally:
        report["http_errors"] = dict(error_counts)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({k:v for k,v in report.items() if k != "identity_safety"}, indent=2))

if __name__ == "__main__":
    main()
