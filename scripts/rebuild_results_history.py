from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from _bootstrap import ROOT
from download_tennis_history import read_json, write_json
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.services.engine import reconcile_ledger, serving_feed
from tbt.services.publication import validate_publication_candidate, validate_market_publication_candidate


def main():
    parser = argparse.ArgumentParser(description="Re-settle all recoverable issued BlinQ history without fabricating publications")
    parser.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cache = ROOT / ".cache/tbt/results-rebuild"
    history_store = ReleaseStore(args.data_repository, "tbt-data-v1", cache / "history")
    history_store.download(require_bundle_manifest=True)
    history = load_partitions(history_store.directory)

    pred_store = ReleaseStore(args.data_repository, "tbt-predictions-v1", cache / "predictions")
    pred_store.download(extra_names=("feed.json", "ledger.json"), required_names=("feed.json", "ledger.json"), require_bundle_manifest=True)
    feed = read_json(pred_store.directory / "feed.json", {})
    ledger = read_json(pred_store.directory / "ledger.json", [])
    if not isinstance(feed, dict) or not isinstance(ledger, list):
        raise ValueError("Invalid production prediction bundle")

    before_rows = int((feed.get("results_meta") or {}).get("settled_total") or len(feed.get("results") or []))
    now = datetime.now(timezone.utc)
    rebuilt_ledger = reconcile_ledger(ledger, [], history, now)
    model_meta = feed.get("model") if isinstance(feed.get("model"), dict) else {}
    model = SimpleNamespace(version=str(model_meta.get("version") or "production"))
    derived = serving_feed(rebuilt_ledger, model, history, model_meta.get("report") or {}, [], now)

    # Keep the live/current offer surface exactly as it was. Only settled history
    # and metrics are rebuilt from immutable issued ledger evidence.
    for key in (
        "results", "performance", "betting_performance", "performance_windows",
        "performance_window_summary", "results_meta", "performance_subgroups", "history",
    ):
        feed[key] = derived[key]
    feed["results_rebuild"] = {
        "schema": 1,
        "generated_at": now.isoformat(),
        "before_settled_rows": before_rows,
        "after_settled_rows": int(feed["results_meta"]["settled_total"]),
        "ledger_rows": len(rebuilt_ledger),
        "policy": "immutable_issued_evidence_only",
        "fabricated_rows": 0,
    }

    validate_publication_candidate(feed, rebuilt_ledger)
    if (feed.get("market_selection") or {}).get("publication_schema") == 1:
        validate_market_publication_candidate(feed, rebuilt_ledger)

    report_path = cache / "results_rebuild_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(report_path, feed["results_rebuild"])
    if not args.dry_run:
        write_json(pred_store.directory / "ledger.json", rebuilt_ledger)
        write_json(pred_store.directory / "feed.json", feed)
        pred_store.upload_bundle([pred_store.directory / "ledger.json", pred_store.directory / "feed.json"])
    print(json.dumps({**feed["results_rebuild"], "dry_run": bool(args.dry_run)}))


if __name__ == "__main__":
    main()
