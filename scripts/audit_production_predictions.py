from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT
from download_tennis_history import read_json, write_json
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.services.ace_selection import build_ace_market_calibration


def _rate(wins: int, n: int):
    return wins / n if n else None


def _confidence_band(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if value >= .85:
        return "85%+"
    if value >= .75:
        return "75-85%"
    if value >= .65:
        return "65-75%"
    if value >= .55:
        return "55-65%"
    return "<55%"


def _aggregate(entries, key_fn):
    groups = defaultdict(lambda: {"n": 0, "wins": 0, "losses": 0, "voids": 0})
    for row, pub in entries:
        result = pub.get("result") if isinstance(pub.get("result"), dict) else {}
        status = str(result.get("status") or "").lower()
        correct = result.get("correct")
        key = str(key_fn(row, pub) or "unknown")
        if status == "void" or correct is None:
            groups[key]["voids"] += 1
            continue
        groups[key]["n"] += 1
        if correct is True:
            groups[key]["wins"] += 1
        elif correct is False:
            groups[key]["losses"] += 1
    out = {}
    for key, value in sorted(groups.items()):
        out[key] = {**value, "hit_rate": _rate(value["wins"], value["n"])}
    return out


def _market_rows(feed, key, market=None):
    rows = feed.get(key) or []
    if not isinstance(rows, list):
        return []
    if market is None:
        return [r for r in rows if isinstance(r, dict)]
    return [r for r in rows if isinstance(r, dict) and str(r.get("market") or "").lower() == market]


def main():
    parser = argparse.ArgumentParser(description="Audit real issued BlinQ production predictions and projection supply")
    parser.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    parser.add_argument("--out", default=str(ROOT / ".cache/tbt/production-audit/production_prediction_audit.json"))
    parser.add_argument("--markdown", default=str(ROOT / ".cache/tbt/production-audit/production_prediction_audit.md"))
    args = parser.parse_args()

    cache = ROOT / ".cache/tbt"
    pred = ReleaseStore(args.data_repository, "tbt-predictions-v1", cache / "production-audit/predictions")
    pred.download(extra_names=("feed.json", "ledger.json"), required_names=("feed.json", "ledger.json"), require_bundle_manifest=True)
    feed = read_json(pred.directory / "feed.json", {})
    ledger = read_json(pred.directory / "ledger.json", [])
    if not isinstance(feed, dict) or not isinstance(ledger, list):
        raise ValueError("Invalid production feed/ledger")

    entries = []
    for row in ledger:
        if not isinstance(row, dict):
            continue
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict) or not pub.get("issued_at") or not isinstance(pub.get("result"), dict):
                continue
            if pub.get("excluded_reason"):
                continue
            entries.append((row, pub))

    sections = _aggregate(entries, lambda _r, p: p.get("section"))
    markets = _aggregate(entries, lambda _r, p: p.get("market"))
    surfaces = _aggregate(entries, lambda r, _p: r.get("surface"))
    tours = _aggregate(entries, lambda r, _p: r.get("tour"))
    confidence = _aggregate(entries, lambda _r, p: _confidence_band(p.get("projection_confidence") if p.get("price_status") == "projection_only" else p.get("model_probability")))

    market_selection = feed.get("market_selection") if isinstance(feed.get("market_selection"), dict) else {}
    ace_report = market_selection.get("ace_projection_report") or market_selection.get("ace_projection") or {}
    sg_report = market_selection.get("sg_projection_report") or market_selection.get("sg_projection") or {}
    selected = {
        "aces": int((ace_report or {}).get("aces_selected") or 0),
        "double_faults": int((ace_report or {}).get("double_faults_selected") or 0),
        "sets": int((sg_report or {}).get("sets_selected") or 0),
        "games": int((sg_report or {}).get("games_selected") or 0),
    }
    published = {
        "aces": len(_market_rows(feed, "ace_picks", "aces")),
        "double_faults": len(_market_rows(feed, "ace_picks", "double_faults")),
        "sets": len(_market_rows(feed, "sg_picks", "sets")),
        "games": len(_market_rows(feed, "sg_picks", "games")),
    }
    supply_mismatch = {k: {"selected": selected[k], "published": published[k]} for k in selected if selected[k] != published[k]}

    # No provider requests: calibration is recomputed only from the stored private
    # historical snapshot using point-in-time walk-forward predictions.
    history_store = ReleaseStore(args.data_repository, "tbt-data-v1", cache / "production-audit/history")
    history_store.download(require_bundle_manifest=True)
    history = load_partitions(history_store.directory)
    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    calibration = build_ace_market_calibration(history, cutoff)

    odds_report = market_selection.get("odds_report") or feed.get("odds_report") or {}
    report = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issued_settled_publications": len(entries),
        "results_meta": feed.get("results_meta") or {},
        "performance_window_summary": feed.get("performance_window_summary") or {},
        "sections": sections,
        "markets": markets,
        "failure_slices": {"tour": tours, "surface": surfaces, "confidence_band": confidence},
        "projection_supply": {"selected": selected, "published": published, "mismatches": supply_mismatch, "ok": not supply_mismatch},
        "ace_df_walk_forward_calibration": calibration,
        "odds_coverage": odds_report,
        "diagnostic_limits": [
            "Breakdowns are descriptive; small groups are not treated as causal evidence.",
            "Deleted historical issuance cannot be recreated without immutable publication evidence.",
        ],
    }
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True); write_json(out, report)

    lines = [
        "# BlinQ production prediction audit",
        "",
        f"Generated: {report['generated_at']}",
        f"Issued + settled market publications: **{len(entries)}**",
        f"Public settled rows: **{(feed.get('results_meta') or {}).get('settled_total', 0)}**",
        "",
        "## Projection supply",
    ]
    for market in ("aces", "double_faults", "sets", "games"):
        lines.append(f"- {market}: selected {selected[market]}, published {published[market]}")
    lines += ["", "## Issued performance by section"]
    for section, metric in sections.items():
        rate = metric.get("hit_rate")
        rate_text = "—" if rate is None else f"{rate*100:.1f}%"
        lines.append(f"- {section}: {rate_text} · n={metric['n']} · W {metric['wins']} / L {metric['losses']} / void {metric['voids']}")
    lines += ["", "## Aces / Double Faults walk-forward calibration"]
    for market in ("aces", "double_faults"):
        item = calibration.get(market) or {}
        lines.append(f"- {market}: examples={item.get('examples', 0)}, hit={item.get('hit_rate')}, calibration_applied={item.get('applied')}, validation raw Brier={item.get('validation_raw_brier')}, calibrated={item.get('validation_calibrated_brier')}")
    lines += ["", "> This audit never invents old bets or odds. Missing immutable issuance stays missing."]
    md = Path(args.markdown); md.parent.mkdir(parents=True, exist_ok=True); md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "markdown": str(md), "projection_supply_ok": not supply_mismatch, "issued_settled": len(entries)}))


if __name__ == "__main__":
    main()
