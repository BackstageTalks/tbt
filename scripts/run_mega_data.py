"""Run high-value tennis backfills under one global RapidAPI budget.

The run is deliberately defensive and data-driven:
1. provider capability probe (tiny/read-only; doubles + market/stat discovery)
2. read-only canonical history audit + small incremental history safety sync
3. zero-API baseline statistics inventory
4. generic event-statistics sweep
5. targeted Sets/Games score enrichment (launch priority)
6. targeted Aces/Double-Fault enrichment (launch priority)
7. statistics tail consumes every request left by earlier phases
8. zero-API post-run inventory + history audit

All writer phases are serialized by the GitHub workflow.  Unused request headroom
rolls forward, so a healthy history costs almost nothing and its reserved budget
falls through to event statistics.  Doubles remain probe-only until provider
payloads confirm stable pair/member identity and odds/statistics coverage; doubles
are never mixed into the singles history/model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from _bootstrap import ROOT


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _run(name: str, args: list[str], *, optional: bool = False) -> dict[str, Any]:
    print(f"\n=== MEGA DATA: {name} ===", flush=True)
    print("$ " + " ".join(args), flush=True)
    completed = subprocess.run(args, cwd=ROOT, env=os.environ.copy(), check=False)
    result = {"name": name, "returncode": int(completed.returncode), "optional": bool(optional)}
    if completed.returncode and not optional:
        raise SystemExit(f"Mega-data phase {name!r} failed with exit code {completed.returncode}")
    if completed.returncode and optional:
        result["warning"] = f"optional phase failed with exit code {completed.returncode}"
    return result


def _budget(total: int) -> dict[str, int]:
    """Launch-day allocation: finish SG/ESA while preserving data safety.

    Unused caps roll forward. History is now a small incremental safety sync;
    integrity mutation is never automatic inside mega-data.
    """
    probe = min(120, max(80, int(total * 0.01)))
    remaining = max(0, total - probe)

    history = min(700, max(150, int(total * 0.05)))
    history = min(history, remaining)
    remaining -= history

    sg = min(4000, max(800, int(total * 0.35)))
    sg = min(sg, remaining)
    remaining -= sg

    ace = min(2800, max(500, int(total * 0.23)))
    ace = min(ace, remaining)
    remaining -= ace

    statistics_primary = max(0, remaining)
    return {
        "provider_probe": probe,
        "history": history,
        "statistics_primary": statistics_primary,
        "sg": sg,
        "ace": ace,
    }


def _actual_requests(phase: str) -> int:
    if phase == "provider_probe":
        return int(_read_json(ROOT / ".cache/tbt/provider-probe/provider_probe_report.json").get("requests_used") or 0)
    if phase in {"history", "statistics"}:
        return int(_read_json(ROOT / ".cache/tbt/history/download_report.json").get("requests_including_retries") or 0)
    if phase == "ace":
        return int(_read_json(ROOT / ".cache/tbt/ace-history/ace_run_summary.json").get("requests") or 0)
    if phase == "sg":
        return int(_read_json(ROOT / ".cache/tbt/sg-history/sg_run_summary.json").get("requests") or 0)
    return 0



def _snapshot_report(source: Path, target: Path) -> dict[str, Any]:
    payload = _read_json(source)
    if payload:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    ap.add_argument("--max-requests", type=int, required=True, help="Global Tennis RapidAPI cap across all phases")
    ap.add_argument("--lookback-days", type=int, default=1095)
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--ace-target-samples", type=int, default=18)
    ap.add_argument("--ace-lookback-days", type=int, default=550)
    ap.add_argument("--sg-target-samples", type=int, default=24)
    ap.add_argument("--sg-lookback-days", type=int, default=730)
    args = ap.parse_args()

    if not 500 <= args.max_requests <= 12000:
        ap.error("mega-data max-requests must be 500..12000")

    report_dir = ROOT / ".cache/tbt/mega-data"
    report_dir.mkdir(parents=True, exist_ok=True)
    planned = _budget(args.max_requests)
    phases: list[dict[str, Any]] = []
    used_total = 0
    carry = 0

    def remaining() -> int:
        return max(0, args.max_requests - used_total)

    def finish_phase(phase: dict[str, Any], cap: int, kind: str) -> int:
        nonlocal used_total, carry
        actual = min(cap, max(0, _actual_requests(kind)))
        used_total += actual
        carry = max(0, cap - actual)
        phase.update({"cap": cap, "requests": actual, "unused_headroom": carry})
        phases.append(phase)
        return actual

    def stats_cmd(cap: int) -> list[str]:
        cmd = [
            sys.executable, "scripts/download_tennis_history.py", "--publish",
            "--data-repository", args.data_repository, "--mode", "statistics",
            "--lookback-days", str(args.lookback_days), "--max-requests", str(cap),
        ]
        if args.start:
            cmd += ["--start", args.start]
        if args.end:
            cmd += ["--end", args.end]
        return cmd

    # 1) Read-only capability probe. Optional: a temporary provider shape issue
    # must not block the expensive writer phases.
    probe_cap = min(planned["provider_probe"], remaining())
    if probe_cap:
        phase = _run(
            "provider-probe",
            [
                sys.executable, "scripts/probe_tennis_provider.py",
                "--max-requests", str(probe_cap),
                "--days-back", "4", "--days-ahead", "3",
                "--odds-samples", "16", "--stats-samples", "10",
            ],
            optional=True,
        )
        finish_phase(phase, probe_cap, "provider_probe")

    # 2) Verify history read-only first. Do not mutate a clean canonical bundle
    # automatically. The incremental sync then catches only genuinely new/gap days.
    _run("history-audit-before", [sys.executable, "scripts/audit_history_data.py", "--data-repository", args.data_repository])
    history_cap = min(planned["history"] + carry, remaining())
    carry = 0
    if history_cap:
        cmd = [
            sys.executable, "scripts/download_tennis_history.py", "--publish",
            "--data-repository", args.data_repository, "--mode", "history",
            "--lookback-days", str(args.lookback_days), "--max-requests", str(history_cap),
        ]
        if args.start:
            cmd += ["--start", args.start]
        if args.end:
            cmd += ["--end", args.end]
        phase = _run("history", cmd)
        finish_phase(phase, history_cap, "history")
        _snapshot_report(
            ROOT / ".cache/tbt/history/download_report.json",
            report_dir / "history_download_report.json",
        )

    # Baseline inventory is free and makes the mega artifact show real gains.
    inventory_before_path = report_dir / "statistics_inventory_before.json"
    if (ROOT / ".cache/tbt/history").is_dir():
        _run(
            "baseline-statistics-inventory",
            [
                sys.executable, "scripts/audit_statistics_inventory.py",
                "--history-dir", ".cache/tbt/history",
                "--out", str(inventory_before_path.relative_to(ROOT)),
            ],
            optional=True,
        )

    # 3) Largest current gap: event statistics / serve-return quality.
    stats_cap = min(planned["statistics_primary"] + carry, remaining())
    carry = 0
    if stats_cap:
        phase = _run("statistics-primary", stats_cmd(stats_cap))
        finish_phase(phase, stats_cap, "statistics")
        _snapshot_report(
            ROOT / ".cache/tbt/history/download_report.json",
            report_dir / "statistics_primary_report.json",
        )

    # 4) Structured set/game samples for current-board players.
    sg_cap = min(planned["sg"] + carry, remaining())
    carry = 0
    if sg_cap:
        phase = _run("sg-scores", [
            sys.executable, "scripts/enrich_sg_history.py",
            "--data-repository", args.data_repository,
            "--lookback-days", str(args.sg_lookback_days),
            "--target-samples", str(args.sg_target_samples),
            "--max-requests", str(sg_cap),
        ])
        finish_phase(phase, sg_cap, "sg")

    # 5) ESA topping-up.  ACE/DF already have a useful corpus, so this remains
    # smaller than generic stats and SG.
    ace_cap = min(planned["ace"] + carry, remaining())
    carry = 0
    if ace_cap:
        phase = _run("ace-statistics", [
            sys.executable, "scripts/enrich_ace_history.py",
            "--data-repository", args.data_repository,
            "--lookback-days", str(args.ace_lookback_days),
            "--target-samples", str(args.ace_target_samples),
            "--max-requests", str(ace_cap),
        ])
        finish_phase(phase, ace_cap, "ace")

    # 6) Spend every request left on the highest-value generic statistics sweep.
    stats_tail_cap = remaining()
    carry = 0
    if stats_tail_cap:
        phase = _run("statistics-tail", stats_cmd(stats_tail_cap))
        finish_phase(phase, stats_tail_cap, "statistics")
        _snapshot_report(
            ROOT / ".cache/tbt/history/download_report.json",
            report_dir / "statistics_tail_report.json",
        )

    # 8) Zero-Tennis-API inventory + integrity audit from the latest canonical release.
    inventory_path = report_dir / "statistics_inventory_after.json"
    if (ROOT / ".cache/tbt/history").is_dir():
        _run(
            "post-run-statistics-inventory",
            [
                sys.executable, "scripts/audit_statistics_inventory.py",
                "--history-dir", ".cache/tbt/history",
                "--out", str(inventory_path.relative_to(ROOT)),
            ],
            optional=True,
        )
    inventory = _read_json(inventory_path)
    inventory_before = _read_json(report_dir / "statistics_inventory_before.json")
    probe = _read_json(ROOT / ".cache/tbt/provider-probe/provider_probe_report.json")

    # Audit is read-only and does not consume Tennis API quota.  Keep it optional
    # so an audit artifact issue cannot erase the expensive enrichment work.
    audit_phase = _run(
        "post-run-history-audit",
        [sys.executable, "scripts/audit_history_data.py", "--data-repository", args.data_repository],
        optional=True,
    )
    phases.append(audit_phase)
    history_audit = _snapshot_report(
        ROOT / ".cache/tbt/history-audit/history_audit_report.json",
        report_dir / "history_audit_after.json",
    )

    payload = {
        "schema": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request_cap": args.max_requests,
        "requests_used": used_total,
        "requests_unused": max(0, args.max_requests - used_total),
        "planned_caps": planned,
        "phases": phases,
        "statistics_inventory_before": inventory_before,
        "history_audit": history_audit,
        "post_run_statistics": {
            "rows": inventory.get("rows"),
            "any_stats_matches": inventory.get("any_stats_matches"),
            "any_stats_rate": inventory.get("any_stats_rate"),
            "quality_capable_matches": inventory.get("quality_capable_matches"),
            "quality_capable_rate": inventory.get("quality_capable_rate"),
            "ace_df_only_matches": inventory.get("ace_df_only_matches"),
            "stat_key_counts": inventory.get("stat_key_counts"),
        },
        "doubles": {
            "status": "probe_only",
            "reason": "Separate doubles collector/model is gated on stable pair/member identity and odds coverage.",
            "probe_summary": probe.get("summary"),
            "market_capabilities": (probe.get("market_capabilities") or {}).get("doubles"),
        },
    }
    (report_dir / "mega_data_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md = [
        "# BlinQ mega-data report", "",
        f"Global Tennis API cap: **{args.max_requests}**",
        f"Requests used: **{used_total}**",
        f"Unused: **{max(0, args.max_requests - used_total)}**", "",
        "## Phases", "",
    ]
    for phase in phases:
        md.append(
            f"- {phase['name']}: {phase.get('requests', 0)} / {phase.get('cap', 0)} requests "
            f"(unused headroom {phase.get('unused_headroom', 0)}), exit={phase.get('returncode', 0)}"
        )
    if inventory:
        md += [
            "", "## Post-run statistics inventory", "",
            f"- rows: {inventory.get('rows', 0)}",
            f"- any stats: {inventory.get('any_stats_matches', 0)} ({inventory.get('any_stats_rate', 0):.2%})",
            f"- quality capable: {inventory.get('quality_capable_matches', 0)} ({inventory.get('quality_capable_rate', 0):.2%})",
            f"- ace/DF-only matches: {inventory.get('ace_df_only_matches', 0)}",
        ]
    md += [
        "", "## Doubles", "",
        "Doubles remain probe-only until pair/team/member identity and odds coverage are confirmed. They are not mixed into the singles model.",
    ]
    (report_dir / "mega_data_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
