#!/usr/bin/env python3
"""One-night, checkpointed BlinQ data collection; no model promotion.

The existing history-writer GitHub concurrency lock MUST surround this runner.
Only an observed RapidAPI remaining-quota header authorizes spending, never an
assumed daily reset. Each underlying history collector publishes checkpoints.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from _bootstrap import ROOT

OUT = ROOT / ".cache/tbt/overnight-20260926"
HISTORY = ROOT / ".cache/tbt/history"
INVENTORY = ROOT / ".cache/tbt/production/statistics_inventory_report.json"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    temp.replace(path)


def budget(confirmed_remaining: int | None, used: int, *, max_spend: int, reserve: int) -> int:
    """No assumed quota; reserve enough requests for the next serving refresh."""
    if confirmed_remaining is None:
        return 0
    return max(0, min(max_spend - used, confirmed_remaining - used - reserve))


def useful_gain(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    return {
        "both_quality": max(0, int(after.get("both_players_quality_ready") or 0)
                            - int(before.get("both_players_quality_ready") or 0)),
        "any_stats": max(0, int(after.get("any_stats_matches") or 0)
                         - int(before.get("any_stats_matches") or 0)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deadline", default="2026-09-27T03:15:00Z")
    ap.add_argument("--max-spend", type=int, default=6000)
    ap.add_argument("--reserve", type=int, default=1200)
    ap.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    args = ap.parse_args()
    deadline = datetime.fromisoformat(args.deadline.replace("Z", "+00:00"))
    if not 0 <= args.max_spend <= 8000 or not 1000 <= args.reserve <= 5000:
        ap.error("Unsafe operator spending bounds")
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema": 1, "purpose": "one-night-resumable-no-promotion",
        "started_utc": utcnow().isoformat(), "deadline_utc": deadline.isoformat(),
        "max_spend": args.max_spend, "serving_reserve": args.reserve,
        "phases": [], "requests_used": 0, "quota_observed": None,
        "paid_collection_attempted": False, "warnings": [],
    }

    def save():
        write_json(OUT / "overnight_report.json", report)

    def run(name: str, command: list[str], *, minutes: int = 45, required: bool = False) -> bool:
        available = (deadline - utcnow()).total_seconds()
        # Allow a report write / final audits after a collector times out.
        duration = min(minutes * 60, max(1, int(available - 100)))
        if duration < 30:
            report["warnings"].append(f"{name}: deadline reached")
            save()
            return False
        entry: dict[str, Any] = {
            "name": name, "started_utc": utcnow().isoformat(),
            "command": [str(s) for s in command if s not in ("--token",)],
        }
        report["phases"].append(entry)
        save()
        log = OUT / f"{name}.log"
        print(f"[OVERNIGHT] {name}: {' '.join(command)}", flush=True)
        try:
            with log.open("w", encoding="utf-8") as handle:
                result = subprocess.run(command, cwd=ROOT, stdout=handle,
                                        stderr=subprocess.STDOUT, timeout=duration, check=False)
            entry["exit_code"] = result.returncode
        except subprocess.TimeoutExpired:
            entry["exit_code"] = 124
            entry["timeout"] = True
        entry["finished_utc"] = utcnow().isoformat()
        try:
            last = log.read_text(errors="replace").splitlines()[-8:]
            entry["last_log_lines"] = last
            print("\n".join(last[-4:]), flush=True)
        except OSError:
            pass
        if entry["exit_code"] != 0:
            report["warnings"].append(f"{name} failed: {entry['exit_code']}")
        save()
        if required and entry["exit_code"] != 0:
            raise RuntimeError(f"Required phase {name} failed; no paid collection")
        return entry["exit_code"] == 0

    def inventory(name: str) -> dict[str, Any]:
        run(name, [sys.executable, "scripts/audit_statistics_inventory.py",
                   "--history-dir", str(HISTORY),
                   "--out", str(INVENTORY)], minutes=15, required=True)
        snap = read_json(INVENTORY)
        write_json(OUT / f"{name}.json", snap)
        return snap

    def probe(name: str) -> int | None:
        """One subscribed TennisApi request; require provider-supplied quota header."""
        snippet = """
import json
from datetime import datetime, timezone
from tbt.providers.rapidapi import RapidTennisClient
c=RapidTennisClient(request_budget=None)
c.request_limit=1
try:
    events=c.calendar_categories(datetime.now(timezone.utc).date())
    print(json.dumps({"quota":c.rate_limit_remaining,"calls":c.request_count,"categories":len(events)}))
finally:
    c.close()
"""
        ok = run(name, [sys.executable, "-c", snippet], minutes=3)
        report["requests_used"] += 1
        if not ok:
            save()
            return None
        try:
            payload = json.loads((OUT / f"{name}.log").read_text().splitlines()[-1])
            remaining = payload.get("quota")
            if isinstance(remaining, int) and remaining >= 0:
                report["quota_observed"] = remaining
                save()
                return remaining
        except (OSError, ValueError, TypeError):
            pass
        report["warnings"].append("Provider quota header unavailable; refusing paid backfill")
        save()
        return None

    def paid(name: str, command: list[str], cap: int, report_path: Path,
             request_key: str, minutes: int = 65) -> int:
        if cap < 1 or (deadline - utcnow()).total_seconds() < 28 * 60:
            return 0
        report["paid_collection_attempted"] = True
        ok = run(name, command + ["--max-requests", str(cap)],
                 minutes=minutes)
        details = read_json(report_path)
        actual = int(details.get(request_key) or cap)
        # Missing report after a failed collector counts as the ENTIRE cap,
        # even if an earlier phase likely used fewer. Never overspend on guess.
        actual = min(cap, max(0, actual))
        if not details:
            actual = cap
            report["warnings"].append(f"{name}: no usage report, charged full cap in ledger")
        report["requests_used"] += actual
        if not ok:
            report["warnings"].append(f"{name}: partial history may already be committed")
        save()
        return actual

    # Preserve a baseline from the latest private *committed* bundle.
    try:
        run("download_inputs", [sys.executable,
            "scripts/download_production_preflight_inputs.py"], minutes=22, required=True)
        before = inventory("inventory_before")
        report["baseline"] = {
            "completed": before.get("completed"),
            "both_quality": before.get("both_players_quality_ready"),
            "any_stats": before.get("any_stats_matches"),
        }
        save()

        # A fresh history job may have introduced new fixtures with a proven
        # location in existing partitions. Cache-only must never use Open-Meteo.
        run("offline_environment", [
            sys.executable, "scripts/enrich_environment_snapshot.py",
            "--data-repository", args.data_repository,
            "--start", "2021-01-01",
            "--end", (utcnow() - timedelta(minutes=5)).isoformat(),
            "--limit", "0", "--cache-only", "--static-only", "--complete-static",
            "--max-requests", "1", "--max-runtime-minutes", "24"
        ], minutes=32)
        # Cache-only publishes its own checkpoints. Refresh the local release
        # before collecting or computing changes against it.
        run("reload_after_environment", [sys.executable,
            "scripts/download_production_preflight_inputs.py"], minutes=20, required=True)

        if (deadline - utcnow()).total_seconds() > 70 * 60 and args.max_spend > 0:
            remaining = probe("quota_probe_initial")
            if remaining is None or budget(remaining, report["requests_used"],
                                            max_spend=args.max_spend, reserve=args.reserve) < 350:
                # RapidAPI billing reset may occur at UTC midnight. Check once
                # after midnight, but never assume the reset actually happened.
                retry_at = datetime(2026, 9, 27, 0, 7, tzinfo=timezone.utc)
                if utcnow() < retry_at < deadline - timedelta(minutes=70):
                    while utcnow() < retry_at:
                        time.sleep(min(60, max(1, (retry_at - utcnow()).total_seconds())))
                    remaining = probe("quota_probe_after_midnight")
            available = budget(remaining, report["requests_used"],
                               max_spend=args.max_spend, reserve=args.reserve)
            if available >= 350:
                # Short yield pilot first: no repeated expensive calls to a
                # source that only exposes Aces/DF or HTTP 200 empty statistics.
                cap = min(400, available)
                paid("quality_pilot_2025_2026", [
                    sys.executable, "scripts/download_tennis_history.py",
                    "--publish", "--data-repository", args.data_repository,
                    "--mode", "statistics", "--start", "2025-01-01",
                    "--lookback-days", "730"
                ], cap, HISTORY / "download_report.json",
                   "requests_including_retries", minutes=58)
                mid = inventory("inventory_after_pilot")
                gain = useful_gain(before, mid)
                report["pilot_gain"] = gain
                save()
                available = budget(remaining, report["requests_used"],
                                   max_spend=args.max_spend, reserve=args.reserve)
                # Require actual new full serve+return for both players.
                if gain["both_quality"] >= 8 and available >= 500:
                    quality_cap = min(4000, max(0, int(available * .76)))
                    if quality_cap >= 400:
                        paid("quality_bulk_2025_2026", [
                            sys.executable, "scripts/download_tennis_history.py",
                            "--publish", "--data-repository", args.data_repository,
                            "--mode", "statistics", "--start", "2025-01-01",
                            "--lookback-days", "730"
                        ], quality_cap, HISTORY / "download_report.json",
                           "requests_including_retries", minutes=125)
                        inventory("inventory_after_quality")
                else:
                    report["warnings"].append(
                        "Low pilot yield; no additional bulk spend on serve/return")
                    save()
                available = budget(remaining, report["requests_used"],
                                   max_spend=args.max_spend, reserve=args.reserve)
                if available >= 500 and (deadline - utcnow()).total_seconds() > 85 * 60:
                    sg_cap = min(1250, max(0, int(available * .67)))
                    if sg_cap >= 250:
                        paid("set_game_history", [
                            sys.executable, "scripts/enrich_sg_history.py",
                            "--data-repository", args.data_repository,
                            "--lookback-days", "730", "--target-samples", "24",
                        ], sg_cap, ROOT / ".cache/tbt/sg-history/sg_run_summary.json",
                           "requests", minutes=60)
                available = budget(remaining, report["requests_used"],
                                   max_spend=args.max_spend, reserve=args.reserve)
                if available >= 300 and (deadline - utcnow()).total_seconds() > 52 * 60:
                    ace_cap = min(950, available)
                    paid("ace_df_current_players", [
                        sys.executable, "scripts/enrich_ace_history.py",
                        "--data-repository", args.data_repository,
                        "--lookback-days", "550", "--target-samples", "18"
                    ], ace_cap, ROOT / ".cache/tbt/ace-history/ace_run_summary.json",
                       "requests", minutes=55)
            else:
                report["warnings"].append(
                    "Provider quota below reserve or not verifiable; zero further paid requests")
                save()

        # Only the committed private release counts. A collector's local
        # uncommitted partial response is never presented as training-ready.
        run("final_preflight", [sys.executable,
            "scripts/run_production_preflight.py"], minutes=55)
        final = read_json(ROOT / ".cache/tbt/production/statistics_inventory_report.json")
        if final:
            report["final_inventory"] = {
                "completed": final.get("completed"),
                "any_stats": final.get("any_stats_matches"),
                "both_quality": final.get("both_players_quality_ready"),
                "both_quality_rate": final.get("both_players_quality_ready_rate"),
            }
        ready = read_json(ROOT / ".cache/tbt/production/readiness_report.json")
        report["readiness"] = {
            "status": ready.get("status"),
            "blockers": ready.get("blockers"),
            "candidate_training": ready.get("candidate_training"),
        }
        report["finished_utc"] = utcnow().isoformat()
        save()
        print(json.dumps({
            "requests_used": report["requests_used"],
            "max_spend": report["max_spend"],
            "final_inventory": report.get("final_inventory"),
            "readiness": report["readiness"],
            "warnings": report["warnings"],
        }, ensure_ascii=False, indent=2), flush=True)
    except Exception as error:
        report["fatal_error"] = f"{type(error).__name__}: {error}"
        report["finished_utc"] = utcnow().isoformat()
        save()
        raise


if __name__ == "__main__":
    main()
