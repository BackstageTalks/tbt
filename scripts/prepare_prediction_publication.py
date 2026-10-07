"""Freeze immutable prediction/market evidence before public deployment."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.services.feed import empty_feed
from tbt.services.publication import (
    prepare_market_publication_evidence,
    prepare_publication_evidence,
    restore_published_market_snapshots,
    validate_market_publication_candidate,
    validate_publication_candidate,
)


PREDICTION_ASSETS = {"feed.json", "ledger.json"}
_PLAYER_PRESENTATION_KEYS = {
    "rank",
    "previous_rank",
    "best_rank",
    "ranking_points",
    "country_code",
    "country_code3",
    "country_name",
    "photo_url",
    "date_of_birth",
    "birth_date",
    "birth_timestamp",
    "height",
    "height_cm",
    "hand",
    "birthplace",
    "residence",
}


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _publication_candidate_view(value, *, player_context: bool = False):
    if isinstance(value, list):
        return [
            _publication_candidate_view(item, player_context=player_context)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {"player_assets", "tournament_assets", "tournament_logo_url"}:
            continue
        if player_context and key in _PLAYER_PRESENTATION_KEYS:
            continue
        result[key] = _publication_candidate_view(
            item,
            player_context=player_context or key in {"player1", "player2"},
        )
    return result


def _asset_state(store: ReleaseStore) -> str:
    assets = store._asset_names()
    present = PREDICTION_ASSETS & assets
    if not present:
        return "absent"
    if present != PREDICTION_ASSETS:
        raise FileNotFoundError(
            "Prediction release incomplete; missing: "
            + ", ".join(sorted(PREDICTION_ASSETS - present))
        )
    return "complete"


def _honest_empty_feed(value) -> bool:
    expected = empty_feed()
    return isinstance(value, dict) and all(value.get(key) == expected[key] for key in expected)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument(
        "--prepared-feed",
        required=True,
        help="Exact local feed that will be deployed after evidence is persisted.",
    )
    args = parser.parse_args(argv)

    prepared_feed = read_json(Path(args.prepared_feed), None)
    if not isinstance(prepared_feed, dict):
        raise ValueError("Invalid prepared feed")

    directory = ROOT / ".cache/tbt/predictions-predeploy"
    store = ReleaseStore(args.data_repository, "tbt-predictions-v1", directory)
    state = _asset_state(store)
    if state == "absent":
        if not _honest_empty_feed(prepared_feed):
            raise RuntimeError(
                "No private prediction candidate exists but deploy feed is non-empty"
            )
        print(json.dumps({"status": "no_candidate", "prepared": 0, "market_prepared": 0}))
        return

    store.download(
        extra_names=("ledger.json", "feed.json"),
        required_names=("ledger.json", "feed.json"),
    )
    ledger = read_json(directory / "ledger.json", [])
    private_feed = read_json(directory / "feed.json", {})
    if not isinstance(ledger, list) or not isinstance(private_feed, dict):
        raise ValueError("Invalid private prediction publication artifacts")

    if (private_feed.get("market_selection") or {}).get("publication_schema") == 1:
        private_feed = restore_published_market_snapshots(private_feed, ledger)

    if _publication_candidate_view(prepared_feed) != _publication_candidate_view(private_feed):
        raise RuntimeError(
            "Prepared deploy feed differs from private candidate; refusing evidence write"
        )

    validate_publication_candidate(prepared_feed, ledger)
    market_schema = (prepared_feed.get("market_selection") or {}).get("publication_schema")
    if market_schema == 1:
        validate_market_publication_candidate(prepared_feed, ledger)

    now = datetime.now(timezone.utc)
    prepared_ledger = prepare_publication_evidence(
        ledger,
        prepared_feed.get("upcoming") or [],
        now,
        feed_generated_at=prepared_feed.get("generated_at"),
    )
    market_prepared = 0
    if market_schema == 1:
        prepared_ledger, market_prepared = prepare_market_publication_evidence(
            prepared_ledger,
            prepared_feed,
            now,
        )

    write_json(directory / "ledger.json", prepared_ledger)
    # Persist evidence before any public upload. feed.json stays byte-for-byte
    # unchanged; a failed Azure deployment therefore leaves only an unissued
    # prepared attempt in private storage.
    store.upload_bundle([directory / "ledger.json"])
    prepared_count = sum(
        1
        for row in prepared_ledger
        if isinstance(row, dict) and isinstance(row.get("prepared_publication"), dict)
        and not row.get("issued_at")
    )
    print(json.dumps({
        "status": "prepared",
        "prepared": prepared_count,
        "market_prepared": market_prepared,
        "issued": 0,
    }))


if __name__ == "__main__":
    main()
