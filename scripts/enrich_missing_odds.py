"""Enrich the missing-odds manifest with precise contract and model context.

Never infer bookmaker market lines from predictions or use settled outcomes
to estimate a price. The result is a research manifest, not a price backfill.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from export_missing_market_odds import OUT, export
from tbt.services.indicative_odds import indicative_price
from release_store import ReleaseStore

REPO = "BackstageTalks/tbt-data"
MARKETS = {"aces", "double_faults", "sets", "games"}


def contract(pub):
    market = str(pub.get("market") or "").strip().lower()
    selection = str(pub.get("selection_id") or "").strip().lower()
    if market == "aces":
        return "most_aces", "selected_player_more_than_opponent", None, "exact_market_type"
    if market == "double_faults":
        return "most_double_faults", "selected_player_more_than_opponent", None, "exact_market_type"
    if market == "sets":
        match = re.fullmatch(r"sets:(over|under):([0-9]+(?:\.[0-9]+)?)", selection)
        if match:
            return "total_sets", match.group(1), float(match.group(2)), "exact_market_and_line"
        return "total_sets", None, None, "incomplete_market"
    if market == "games":
        direction = str(pub.get("projection_direction") or "").lower()
        if not direction and selection.startswith("games:"):
            direction = selection.split(":", 1)[1]
        # The model reference is a baseline, NOT a published bookmaker O/U threshold.
        return "total_games", direction, None, "bookmaker_line_unknown"
    return market, None, None, "unknown"


def enrich(ledger):
    base = export(ledger)
    by_key = {}
    authentic = Counter()
    authentic_samples = []
    for row in ledger:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or row.get("id") or row.get("match_id") or "")
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict) or not pub.get("issued_at"):
                continue
            market = str(pub.get("market") or "").lower()
            if market not in MARKETS:
                continue
            try:
                price = float(pub.get("odds") or 0)
            except (TypeError, ValueError):
                price = 0.0
            if price > 1 and pub.get("price_status") == "priced_projection":
                authentic[market] += 1
                if len(authentic_samples) < 30:
                    name, side, line, precision = contract(pub)
                    authentic_samples.append({
                        "event_id": event_id, "market": name,
                        "side": side, "line": line, "odds": price,
                        "issued_at": pub.get("issued_at"),
                        "price_source": pub.get("price_source")
                    })
                continue
            key = pub.get("publication_key") or pub.get("selection_key")
            if key:
                by_key[str(key)] = pub

    output = []
    for item in base:
        pub = by_key.get(str(item.get("publication_key") or ""), {})
        market, side, line, precision = contract(pub if pub else item)
        enriched = dict(item)
        enriched.update({
            "contract": market,
            "contract_side": side,
            "line": line,
            "contract_precision": precision,
            "model_projection": pub.get("projection"),
            "opponent_model_projection": pub.get("opponent_projection"),
            "model_reference_not_bookmaker_line": pub.get("reference_projection"),
            "model_confidence": pub.get("projection_confidence"),
            "best_of": pub.get("best_of"),
            "projection_direction": pub.get("projection_direction"),
        })
        estimated = indicative_price({
            "market": enriched["market"],
            "projection_confidence": enriched.get("model_confidence"),
        })
        enriched.update(estimated or {
            "indicative_odds": None,
            "indicative_odds_method": "insufficient_frozen_pre_match_confidence",
        })
        output.append(enriched)
    counts = dict(Counter(row["contract_precision"] for row in output))
    audit = {
        "missing": len(output),
        "by_market": dict(Counter(row["market"] for row in output)),
        "contract_precision": counts,
        "authentic_priced_by_market": dict(authentic),
        "indicative_estimates": sum(item["indicative_odds"] is not None for item in output),
        "without_frozen_confidence": sum(item["indicative_odds"] is None for item in output),
        "indicative_estimates_by_market": dict(Counter(
            item["market"] for item in output if item["indicative_odds"] is not None
        )),
        "authentic_priced_examples": authentic_samples,
        "notes": [
            "Most Aces and Most Double Faults select the player with more "
            "of that statistic, not an individual player O/U.",
            "The games model reference is NOT a bookmaker O/U line.",
            "Never derive price from the match result.",
            "Indicative prices are display-only, model-confidence based, "
            "NOT historic bookmaker prices and NOT eligible for real ROI.",
        ],
    }
    return output, audit


def main():
    store = ReleaseStore(REPO, "tbt-predictions-v1",
                         ROOT / ".cache/tbt/odds-recovery")
    store.download(extra_names=("ledger.json",), required_names=("ledger.json",),
                   require_bundle_manifest=True)
    ledger = json.loads((store.directory / "ledger.json").read_text(encoding="utf-8"))
    if not isinstance(ledger, list):
        raise ValueError("Invalid published ledger")
    rows, audit = enrich(ledger)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "enriched_missing_odds.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT / "contract_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if rows:
        with (OUT / "enriched_missing_odds.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({k: v for k, v in audit.items()
                      if k != "authentic_priced_examples"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
