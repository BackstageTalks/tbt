"""Export precise historical BlinQ selections that lack a bookmaker price.

No writes to prediction releases. Used to match archived real odds, rather than
guessing from wins/losses or confusing model projections with betting lines.
"""
from __future__ import annotations
import csv
import json
from collections import Counter
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from release_store import ReleaseStore

REPO = "BackstageTalks/tbt-data"
OUT = ROOT / "reports" / "missing_market_odds"

def label(value):
    if isinstance(value, dict):
        return str(value.get("name") or value.get("display_name") or value.get("full_name") or "")
    return str(value or "")

def first(record, keys):
    for key in keys:
        if record.get(key) is not None:
            return record[key]
    return None

def export(ledger):
    found = []
    seen = set()
    for row in ledger:
        if not isinstance(row, dict):
            continue
        eid = str(first(row, ("event_id", "id", "match_id")) or "")
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict):
                continue
            market = str(pub.get("market") or "").lower().strip()
            if market not in {"aces", "double_faults", "sets", "games"}:
                continue
            if not pub.get("issued_at"):
                continue
            try:
                priced = float(pub.get("odds") or 0) > 1
            except (ValueError, TypeError):
                priced = False
            if priced:
                continue
            selection = first(pub, ("selection", "selection_name", "selection_label",
                                    "selection_id", "side"))
            semantic = (eid, market, str(pub.get("projection_scope") or ""),
                        str(pub.get("projection_metric") or ""), str(selection))
            if semantic in seen:
                continue
            seen.add(semantic)
            found.append({
                "event_id": eid,
                "scheduled_at": first(row, ("scheduled_at", "date", "commence_time")),
                "player1": label(first(row, ("player1", "home_team", "player_1"))),
                "player2": label(first(row, ("player2", "away_team", "player_2"))),
                "tournament": label(first(row, ("tournament", "tournament_name", "league"))),
                "market": market,
                "section": pub.get("section"),
                "selection": selection,
                "selection_id": pub.get("selection_id"),
                "scope": pub.get("projection_scope"),
                "metric": pub.get("projection_metric"),
                "projection_kind": pub.get("projection_kind"),
                "line": first(pub, ("line", "point", "threshold", "bet_line")),
                "issued_at": pub.get("issued_at"),
                "price_status": pub.get("price_status"),
                "publication_key": pub.get("publication_key") or pub.get("selection_key"),
            })
    return found

def main():
    store = ReleaseStore(REPO, "tbt-predictions-v1",
                         ROOT / ".cache/tbt/odds-recovery")
    store.download(extra_names=("ledger.json",), required_names=("ledger.json",),
                   require_bundle_manifest=True)
    ledger = json.loads((store.directory / "ledger.json").read_text(encoding="utf-8"))
    if not isinstance(ledger, list):
        raise ValueError("Unexpected ledger format")
    rows = export(ledger)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "missing_odds.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if rows:
        with (OUT / "missing_odds.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    counts = dict(Counter(row["market"] for row in rows))
    print(f"Missing-odds selections: {len(rows)} by market: {counts}")
    print(f"Export directory: {OUT}")
    if not rows:
        print("No missing issued market publications found; investigate public projection feed separately.")

if __name__ == "__main__":
    main()
