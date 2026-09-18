"""Combine launch-critical BlinQ data reports into one conservative go/no-go report.

This does not invent missing odds markets. Projection modules can be published as
MODEL outputs when their historical sample gate passes; odds/value status remains
separate and is only marked observed when the provider probe actually saw it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: str) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def ratio(summary: dict[str, Any]) -> float:
    target = int(summary.get("target_players") or 0)
    ready = int(summary.get("players_ready") or 0)
    return (ready / target) if target else 0.0


def build(mega: dict[str, Any], preflight: dict[str, Any], *, sample_gate: float) -> dict[str, Any]:
    audit = mega.get("history_audit") if isinstance(mega.get("history_audit"), dict) else {}
    sg = mega.get("sg_summary") if isinstance(mega.get("sg_summary"), dict) else {}
    ace = mega.get("ace_summary") if isinstance(mega.get("ace_summary"), dict) else {}
    probe = mega.get("provider_live_probe") if isinstance(mega.get("provider_live_probe"), dict) else {}

    history_clean = bool(audit) and int(audit.get("invalid_rows") or 0) == 0 and int(audit.get("duplicate_match_id_groups") or 0) == 0 and int(audit.get("duplicate_provider_event_id_groups") or 0) == 0
    sg_rate = ratio(sg)
    ace_rate = ratio(ace)
    sg_projection_ready = bool(sg.get("target_players")) and sg_rate >= sample_gate
    ace_projection_ready = bool(ace.get("target_players")) and ace_rate >= sample_gate

    live_samples = probe.get("live_odds_samples") if isinstance(probe.get("live_odds_samples"), list) else []
    set2_rows = sum(len(row.get("second_set_rows") or []) for row in live_samples if isinstance(row, dict))
    set2_odds_observed = set2_rows > 0

    preflight_status = str(preflight.get("status") or "missing")
    production_data_ready = preflight_status in {"ready", "ready_with_warnings"}

    blockers = []
    if not history_clean:
        blockers.append("history_integrity_not_clean_or_missing")
    if not sg_projection_ready:
        blockers.append("sets_games_sample_gate_not_met")
    if not ace_projection_ready:
        blockers.append("esa_sample_gate_not_met")
    if preflight and not production_data_ready:
        blockers.append("production_preflight_blocked")

    warnings = []
    if not set2_odds_observed:
        warnings.append("set2_odds_not_observed_in_live_probe; LIVE projection remains valid but value/EV must stay hidden")
    if not preflight:
        warnings.append("production_preflight_report_missing")

    return {
        "schema": 1,
        "status": "blocked" if blockers else ("ready_with_warnings" if warnings else "ready"),
        "sample_gate": sample_gate,
        "blockers": blockers,
        "warnings": warnings,
        "history": {"clean": history_clean, "total_rows": audit.get("total_rows")},
        "sets_games": {
            "projection_ready": sg_projection_ready,
            "players_ready": sg.get("players_ready"),
            "target_players": sg.get("target_players"),
            "ready_rate": round(sg_rate, 4),
            "target_samples": sg.get("target_samples"),
            "odds_ready": False,
            "publication_mode": "model_projection" if sg_projection_ready else "hold",
        },
        "esa": {
            "projection_ready": ace_projection_ready,
            "players_ready": ace.get("players_ready"),
            "target_players": ace.get("target_players"),
            "ready_rate": round(ace_rate, 4),
            "target_samples": ace.get("target_samples"),
            "odds_ready": False,
            "publication_mode": "model_projection" if ace_projection_ready else "hold",
        },
        "live_set2": {
            "live_events_sampled": int(probe.get("live_events") or 0),
            "odds_samples": len(live_samples),
            "set2_priced_rows_observed": set2_rows,
            "odds_observed": set2_odds_observed,
            "value_mode": "edge_ev" if set2_odds_observed else "projection_only",
        },
        "production_preflight": {"status": preflight_status, "ready": production_data_ready},
    }


def markdown(report: dict[str, Any]) -> str:
    sg, ace, live = report["sets_games"], report["esa"], report["live_set2"]
    lines = [
        "# BlinQ launch gate", "", f"**Status:** `{report['status']}`", "",
        f"- History clean: **{report['history']['clean']}**",
        f"- SETS/GAMES sample readiness: **{sg['ready_rate']:.1%}** → `{sg['publication_mode']}`",
        f"- ESA sample readiness: **{ace['ready_rate']:.1%}** → `{ace['publication_mode']}`",
        f"- LIVE Set-2 priced rows observed: **{live['set2_priced_rows_observed']}** → `{live['value_mode']}`",
        f"- Production preflight: **{report['production_preflight']['status']}**", "",
        "## Blockers", "",
    ]
    lines += [f"- {x}" for x in report.get("blockers") or []] or ["- none"]
    lines += ["", "## Warnings", ""]
    lines += [f"- {x}" for x in report.get("warnings") or []] or ["- none"]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mega", default=".cache/tbt/mega-data/mega_data_report.json")
    ap.add_argument("--preflight", default=".cache/tbt/production/readiness_report.json")
    ap.add_argument("--sample-gate", type=float, default=0.80)
    ap.add_argument("--out", default=".cache/tbt/launch/launch_gate.json")
    ap.add_argument("--markdown", default=".cache/tbt/launch/launch_gate.md")
    args = ap.parse_args()
    report = build(load(args.mega), load(args.preflight), sample_gate=max(0.0, min(1.0, args.sample_gate)))
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = Path(args.markdown); md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "blocked":
        raise SystemExit("Launch gate blocked: " + ", ".join(report["blockers"]))


if __name__ == "__main__":
    main()
