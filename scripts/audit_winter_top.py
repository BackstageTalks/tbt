"""Read-only comparison on frozen daily slates. Prints aggregate counts only."""
import gzip
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

from audit_top_direction import ledger_outcome
from audit_top_721_funnel import quote_evidence
from replay_selection_reliability import anchors, dt, load_snapshots
from tbt.services.market_selection import select_market_sections
from tbt.services.top_policy import competition_group


def replay_row(row):
    bet = dict(row["betting"], market="match_winner",
               model_probability=row["raw_model_probability"],
               blinq_probability=row["blinq_probability"])
    samples = row.get("samples") or {}
    quality = {side: {key: samples.get(f"{side}_{key}") for key in ("matches", "surface_matches")}
               for side in ("player1", "player2")}
    quality["feature_evidence"] = row.get("feature_evidence")
    return dict(row, betting=bet, match_winner_market=row["two_way_market"], quality=quality)


def analyze(directory):
    paths = sorted(directory.glob("selection_candidates_*.json.gz"))
    if not paths:
        raise ValueError("Frozen candidate archives missing")
    ledger = json.loads((directory / "ledger.json").read_text(encoding="utf-8"))
    by_event = defaultdict(list)
    for row in ledger:
        by_event[str(row.get("event_id") or "")].append(row)
    result = Counter()
    for day, snapshot in anchors(load_snapshots(paths)).items():
        clock = dt(snapshot["generated_at"])
        rows = [replay_row(r) for r in snapshot["rows"]
                if r.get("priced") and quote_evidence(r, clock) == "verified_prestart_selected_price_ge_150"
                and r.get("created_at") and dt(r["created_at"]) <= clock]
        result["days"] += 1
        result["graded_itf_rows"] += sum(competition_group(r) == "ITF" for r in rows)
        prior = set()
        for mode in ("linear", "sqrt_v1"):
            with patch.dict(os.environ, {"TBT_ITF_TOP_DEPTH_MODE": mode, "TBT_TOP_EMERGENCY_FILL": "0"}):
                top = select_market_sections(rows, public_offer_day=day)["top_daily_picks"]
            result[mode + "_top"] += len(top)
            for pick in top:
                key = (str(pick["event_id"]), str(pick["winner_id"]))
                if mode == "linear":
                    prior.add(key)
                elif key not in prior:
                    result["new_selections"] += 1
                    history = by_event.get(key[0], [])
                    winner = ledger_outcome(pick, history[0]) if len(history) == 1 else None
                    if winner:
                        result["new_settled"] += 1
                        result["new_correct"] += int(winner == key[1])
    return dict(result)


def staging(directory):
    owners = defaultdict(set)
    result = Counter()
    for path in sorted(directory.glob("*.jsonl.gz")):
        result["files"] += 1
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                owners[str(row["provider_event_id"])].add(str(row["match_id"]))
                result["rows"] += 1
                result["empty_stats"] += int(not row.get("stats"))
    result["unique_events"] = len(owners)
    result["events_with_multiple_match_ids"] = sum(len(matches) > 1 for matches in owners.values())
    return dict(result)


if __name__ == "__main__":
    root = Path(sys.argv[1])
    print("WINTER_AUDIT " + json.dumps({"selection": analyze(root), "staging": staging(root)}))
