"""Confirm prediction issuance only after a successful public deployment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from urllib.request import Request, urlopen
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.services.feed import empty_feed
from prepare_feed import _read_confirmed_telegram_state
from telegram_offer_publisher import verify_frozen_daily_offer
from tbt.services.issued_authority import build_confirmed_authority
from tbt.services.publication import (
    build_confirmed_daily_offer_snapshot,
    confirm_market_publications,
    confirm_publication,
    validate_market_publication_candidate,
    restore_published_market_snapshots,
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


def _publication_candidate_view(value, *, player_context: bool = False):
    """Return a comparison-safe view of a deployed/private feed.

    prepare_feed.py may attach presentation-only player/tournament metadata
    after the private prediction candidate has already been validated against the
    ledger. Those fields must not make post-deploy issuance confirmation fail,
    while all prediction/market/model content remains exact-match protected.

    Doubles/team rows can contain player members nested below player1/player2.
    Presentation enrichment is applied to those member dictionaries too, so
    player context must propagate recursively instead of stripping fields only
    from the top-level player object.
    """
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

        child_player_context = player_context or key in {"player1", "player2"}
        result[key] = _publication_candidate_view(
            item,
            player_context=child_player_context,
        )
    return result

def _matches_private_publication_candidate(deployed: dict, released: dict, restored: dict) -> bool:
    """After issuing, the immutable ledger can alter restored market snapshots.

    The exact released feed remains a valid candidate on an idempotent retry;
    never accept a feed that differs from both trusted release representations.
    """
    observed = _publication_candidate_view(deployed)
    return (
        observed == _publication_candidate_view(released)
        or observed == _publication_candidate_view(restored)
    )


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def _prediction_asset_state(store: ReleaseStore) -> str:
    assets = store._asset_names()
    present = PREDICTION_ASSETS & assets
    if not present:
        return "absent"
    if present != PREDICTION_ASSETS:
        missing = sorted(PREDICTION_ASSETS - present)
        raise FileNotFoundError(
            "Prediction release is incomplete; missing assets: " + ", ".join(missing)
        )
    return "complete"


def _is_honest_empty_feed(value) -> bool:
    expected = empty_feed()
    return isinstance(value, dict) and all(value.get(key) == expected[key] for key in expected)


def sync_confirmed_authority(deployed_path: Path, deployed_feed: dict, confirmed_ledger: list) -> dict:
    """Apply confirmation to serving only after durable private ledger upload.

    A failed remote sync is an unsuccessful release; the runtime fails closed
    for all as-yet-unconfirmed candidate rows in the meantime.
    """
    token = str(os.getenv("BLINQ_LIVE_WORKER_TOKEN") or "").strip()
    base = str(
        os.getenv("TBT_PRODUCTION_URL")
        or os.getenv("BLINQ_BASE_URL")
        or ""
    ).rstrip("/")
    if not token or not base.startswith("https://"):
        raise RuntimeError("Authenticated production issued-authority sync is not configured")
    manifest = build_confirmed_authority(deployed_feed, confirmed_ledger)
    digest = hashlib.sha256(deployed_path.read_bytes()).hexdigest()
    manifest["feed_sha256"] = digest
    endpoint = base + "/api/v1/internal/issued-offer-authority"
    headers = {
        "Content-Type": "application/json",
        "X-Blinq-Worker-Token": token,
        "Cache-Control": "no-cache",
    }
    request = Request(
        endpoint,
        data=json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
        headers=headers, method="POST",
    )
    with urlopen(request, timeout=25) as result:
        accepted = json.load(result)
    expected = set(manifest["keys"])
    if (
        accepted.get("ok") is not True
        or accepted.get("betting_day") != manifest["betting_day"]
        or accepted.get("feed_sha256") != digest
        or not expected.issubset(set(accepted.get("keys") or []))
    ):
        raise RuntimeError("Durable issued authority write was not acknowledged")
    readback = Request(endpoint, headers=headers, method="GET")
    with urlopen(readback, timeout=25) as result:
        observed = json.load(result)
    if (
        observed.get("ok") is not True
        or observed.get("confirmed_only") is not True
        or observed.get("betting_day") != manifest["betting_day"]
        or not expected.issubset(set(observed.get("keys") or []))
    ):
        raise RuntimeError("Independent issued authority readback failed")
    return {
        "betting_day": manifest["betting_day"],
        "confirmed_keys": len(expected),
        "durable_keys": observed.get("count"),
        "feed_sha256": digest,
    }



def summarize_confirmed_offer_snapshot(snapshot):
    """Validate and count *issued* markets without merging ESÁ and Viac Es."""
    if not isinstance(snapshot, dict) or snapshot.get("schema") != 1 or snapshot.get("confirmed_only") is not True:
        raise ValueError("Daily snapshot is not confirmed-only")
    sections = ("top_daily_picks", "prime_picks", "value_picks", "ace_picks",
                "sg_picks", "doubles_picks")
    totals = snapshot.get("totals")
    if not isinstance(totals, dict):
        raise ValueError("Daily snapshot has no category totals")
    for key in sections:
        rows = snapshot.get(key)
        if not isinstance(rows, list) or type(totals.get(key)) is not int or totals[key] != len(rows):
            raise ValueError(f"Daily snapshot category mismatch: {key}")
        identities = []
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("event_id") or "").strip():
                raise ValueError(f"Invalid issued daily snapshot row: {key}")
            identities.append((
                str(row["event_id"]),
                str(row.get("market") or "match_winner"),
                str(row.get("selection_id") or (row.get("betting") or {}).get("selection_id") or ""),
            ))
        if len(identities) != len(set(identities)):
            raise ValueError(f"Duplicate issued daily snapshot selection: {key}")
    ace_markets = {
        "aces": 0,
        "most_aces": 0,
        "double_faults": 0,
    }
    for row in snapshot["ace_picks"]:
        market = str(row.get("market") or "").strip().lower()
        if market not in ace_markets:
            raise ValueError(f"Unknown issued ace market: {market}")
        ace_markets[market] += 1
    return {
        "betting_day": snapshot.get("betting_day"),
        "confirmed_only": True,
        "top": len(snapshot["top_daily_picks"]),
        "value": len(snapshot["value_picks"]),
        "esa": ace_markets["aces"],
        "viac_es": ace_markets["most_aces"],
        "double_faults": ace_markets["double_faults"],
        "prime": len(snapshot["prime_picks"]),
    }


def verify_uploaded_offer_snapshot(repository, expected):
    """Read back the immutable confirmed snapshot from private GitHub release."""
    with TemporaryDirectory(prefix="blinq-confirmed-offer-readback-") as directory:
        read_store = ReleaseStore(repository, "tbt-predictions-v1", Path(directory))
        read_store.download(
            extra_names=("daily_offer_snapshot.json",),
            required_names=("daily_offer_snapshot.json",),
            require_bundle_manifest=True,
        )
        remote = json.loads(
            (Path(directory) / "daily_offer_snapshot.json").read_text(encoding="utf-8")
        )
        if remote != expected:
            raise RuntimeError("Private release confirmed daily snapshot read-back mismatch")
        counts = summarize_confirmed_offer_snapshot(remote)
        counts["status"] = "verified"
        return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument(
        "--deployed-feed",
        default=None,
        help="Local feed file that was just deployed; must match the private candidate exactly.",
    )
    parser.add_argument(
        "--ui-config-file",
        default=None,
        help="Effective public UI config captured at issuance; only entitlement rules are persisted.",
    )
    parser.add_argument(
        "--sync-serving-authority", action="store_true",
        help="Require authenticated issued-only member-serving readback after confirmation.",
    )
    parser.add_argument(
        "--require-prepared-evidence",
        action="store_true",
        help="Fail closed unless this exact candidate was frozen before deployment.",
    )
    args = parser.parse_args(argv)

    effective_ui_config = None
    if args.ui_config_file:
        effective_ui_config = read_json(Path(args.ui_config_file), None)
        if not isinstance(effective_ui_config, dict):
            raise ValueError("Invalid effective UI config")

    deployed_feed = None
    if args.deployed_feed:
        deployed_feed = read_json(Path(args.deployed_feed), None)
        if not isinstance(deployed_feed, dict):
            raise ValueError("Invalid deployed feed")

    directory = ROOT / ".cache/tbt/predictions-confirm"
    store = ReleaseStore(args.data_repository, "tbt-predictions-v1", directory)
    state = _prediction_asset_state(store)

    if state == "absent":
        # A manual/bootstrap deployment can legitimately have no prediction
        # candidate yet. It must have deployed the honest empty feed; there is
        # then nothing to issue and confirmation is a successful no-op.
        if deployed_feed is not None and not _is_honest_empty_feed(deployed_feed):
            raise RuntimeError(
                "No private prediction candidate exists, but the deployed feed is not empty; "
                "refusing to confirm an unverifiable deployment"
            )
        print(json.dumps({"status": "no_candidate", "newly_confirmed": 0, "published_ids": 0}))
        return

    store.download(
        extra_names=("ledger.json", "feed.json"),
        required_names=("ledger.json", "feed.json"),
    )
    ledger = read_json(directory / "ledger.json", [])
    feed = read_json(directory / "feed.json", {})
    if not isinstance(ledger, list) or not isinstance(feed, dict):
        raise ValueError("Invalid prediction publication artifacts")

    released_feed = feed
    if (feed.get("market_selection") or {}).get("publication_schema") == 1:
        feed = restore_published_market_snapshots(feed, ledger)

    if deployed_feed is None:
        deployed_feed = feed
    elif not _matches_private_publication_candidate(deployed_feed, released_feed, feed):
        raise RuntimeError(
            "Deployed feed does not match the current private publication candidate; "
            "refusing to confirm issuance"
        )

    upcoming = deployed_feed.get("upcoming")
    if not isinstance(upcoming, list):
        raise ValueError("Invalid deployed feed")
    validate_publication_candidate(deployed_feed, ledger)
    market_schema = (deployed_feed.get("market_selection") or {}).get("publication_schema")
    if market_schema == 1:
        validate_market_publication_candidate(deployed_feed, ledger)
    published_rows = upcoming
    before = sum(1 for row in ledger if isinstance(row, dict) and row.get("issued_at"))
    now = datetime.now(timezone.utc)
    confirmed = confirm_publication(
        ledger,
        published_rows,
        now,
        require_prepared=args.require_prepared_evidence,
    )
    market_new = 0
    if market_schema == 1:
        confirmed, market_new = confirm_market_publications(
            confirmed,
            deployed_feed,
            now,
            require_prepared=args.require_prepared_evidence,
        )
    after = sum(1 for row in confirmed if isinstance(row, dict) and row.get("issued_at"))
    print("Telegram exact offer confirmation gate:", json.dumps(
        verify_frozen_daily_offer(
            build_confirmed_daily_offer_snapshot(deployed_feed, confirmed, now=now),
            _read_confirmed_telegram_state(args.data_repository), now,
        ), sort_keys=True,
    ))
    write_json(directory / "ledger.json", confirmed)
    daily_snapshot = build_confirmed_daily_offer_snapshot(
        feed,
        confirmed,
        now=now,
        ui_config=effective_ui_config,
    )
    # Bind the final certificate to the workflow which actually confirmed it.
    # A concurrent deployment finishing after this confirmation must not be
    # mistaken for the same final generation by Telegram.
    run_id = str(os.getenv("GITHUB_RUN_ID") or "")
    if run_id.isdecimal() and int(run_id) > 0:
        daily_snapshot["final_offer"]["issuer_run_id"] = int(run_id)
    write_json(directory / "daily_offer_snapshot.json", daily_snapshot)
    store.upload_bundle([
        directory / "ledger.json",
        directory / "daily_offer_snapshot.json",
    ])
    snapshot_readback = verify_uploaded_offer_snapshot(args.data_repository, daily_snapshot)
    authority_readback = (
        sync_confirmed_authority(Path(args.deployed_feed), deployed_feed, confirmed)
        if args.sync_serving_authority and args.deployed_feed else None
    )
    if args.sync_serving_authority and authority_readback is None:
        raise RuntimeError("Exact deployed feed required for issued authority sync")
    print(json.dumps({
        "status": "confirmed",
        "newly_confirmed": after - before,
        "market_newly_confirmed": market_new,
        "published_ids": len(published_rows),
        "issued_authority_readback": authority_readback,
        "daily_snapshot_readback": snapshot_readback,
    }))


if __name__ == "__main__":
    main()
