"""Run the high-value tennis data backfills under one global RapidAPI budget.

Operational goal: one GitHub Action run, one Tennis RapidAPI cap and sequential
writers. The phase order is intentionally driven by the current production
preflight: event statistics are the largest gap, Sets/Games are next, Aces/DF
already have a useful corpus, and plain history is only a small catch-up step.

Current phases:
1. provider capability probe (tiny, read-only; doubles/markets/stat-key discovery)
2. generic event-statistics sweep (largest budget share)
3. targeted Sets/Games score enrichment for current-board players
4. targeted Aces/Double-Fault enrichment for current-board players
5. canonical history catch-up (small reserved cap; normally near-zero)
6. second statistics sweep with every request still left
7. zero-API post-run statistics inventory

Unused request headroom rolls forward automatically. Doubles remain probe-only
until pair/member identity and odds coverage are confirmed by real provider
payloads; doubles are never mixed into the singles history/model.
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
    """Reserve high-value caps; unused requests roll forward and end in stats-tail."""
    probe = min(120, max(60, int(total * 0.01)))
    remaining = max(0, total - probe)

    # Keep plain history small. The canonical corpus is already large/current;
    # this only catches a recent gap before unused budget returns to statistics.
    history = min(300, max(50, int(total * 0.03)))
    history = min(history, remaining)
    remaining -= history

    # Aces/DF already have materially better coverage than SG, so cap this phase.
    ace = min(1500, max(250, int(total * 0.10)))
    ace = min(ace, remaining)
    remaining -= ace

    # Structured score history is still shallow and directly unlocks SETS/GAMES.
    sg = min(3200, max(500, int(total * 0.25)))
    sg = min(sg, remaining)
    remaining -= sg

    # Everything else is the primary event-statistics sweep.
    statistics_primary = max(0, remaining)
    return {
        "provider_probe": probe,
        "statistics_primary": statistics_primary,
        "sg": sg,
        "ace": ace,
        "history": history,
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
                "--days-back", "3", "--days-ahead", "2",
                "--odds-samples", "12", "--stats-samples", "8",
            ],
            optional=True,
        )
        finish_phase(phase, probe_cap, "provider_probe")

    # 2) Largest current gap: event statistics / serve-return quality.
    _run("statistics-repair", [sys.executable, "scripts/repair_history_data.py", "--data-repository", args.data_repository])
    stats_cap = min(planned["statistics_primary"] + carry, remaining())
    carry = 0
    if stats_cap:
        phase = _run("statistics-primary", stats_cmd(stats_cap))
        finish_phase(phase, stats_cap, "statistics")

    # 3) Structured set/game samples for current-board players.
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

    # 4) ESA topping-up. This is intentionally smaller than SG/statistics now.
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

    # 5) Tiny history catch-up near the end. If already complete it spends almost
    # nothing and its unused headroom immediately returns to statistics-tail.
    _run("history-repair", [sys.executable, "scripts/repair_history_data.py", "--data-repository", args.data_repository])
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

    # 6) Consume every remaining request on the highest-value generic stats sweep.
    # A second pass naturally skips rows marked available/cached by the first pass
    # and continues farther back through the requested window.
    stats_tail_cap = remaining()
    carry = 0
    if stats_tail_cap:
        phase = _run("statistics-tail", stats_cmd(stats_tail_cap))
        finish_phase(phase, stats_tail_cap, "statistics")

    # 7) Zero-Tennis-API inventory from the latest local canonical release.
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
    probe = _read_json(ROOT / ".cache/tbt/provider-probe/provider_probe_report.json")

    payload = {
        "schema": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request_cap": args.max_requests,
        "requests_used": used_total,
        "requests_unused": max(0, args.max_requests - used_total),
        "planned_caps": planned,
        "phases": phases,
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
