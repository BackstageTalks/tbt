"""Prepare a dated CDB offer sidecar from the existing Prop-Line archive.

Zero provider calls. Default is local staging only. Explicit --apply uses the
existing global CDB writer lock and ReleaseStore, with independent read-back.
History partitions, models and published predictions are never rewritten.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from propline_evening_quotes import load_evening_report, validated_events, _valid_report

REPOSITORY = "BackstageTalks/tbt-data"
RELEASE = "tbt-data-v1"


def stage(report, *, day, now):
    date.fromisoformat(day)
    if not _valid_report(report, betting_day=day, now=now):
        raise ValueError("Missing, stale or incomplete source archive; do not refetch provider")
    events = validated_events(report, betting_day=day, now=now)
    ids = [str(e["event_id"]) for e in events]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate provider fixture in archive")
    # Retain source evidence so any downstream reader can revalidate identity,
    # timestamp, native payload hash and parsed lines without a provider call.
    return {"schema": 1, "scope": "prematch_aces_offers", "target_day": day,
            "source": "propline", "source_captured_at": report["captured_at"],
            "source_sha256": sha256(json.dumps(report, sort_keys=True,
                ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
            "events": events, "incremental_provider_requests": 0,
            "status": "offers_available" if any(e.get("aces_markets") for e in events) else "bez ponuky"}


def persist(path, *, work):
    from cdb_global_writer_lock import acquire, release
    from release_store import ReleaseStore

    state = Path(".cdb-global-writer-lock.json")
    acquire(REPOSITORY, state, wait_seconds=0)
    try:
        # Dated immutable name: reruns never replace an observed snapshot.
        store = ReleaseStore(REPOSITORY, RELEASE, work / "store")
        assets = store._asset_names()
        if path.name in assets:
            store._download_asset(path.name)
            if (store.directory / path.name).read_bytes() != path.read_bytes():
                raise RuntimeError("Existing dated offer snapshot differs; refusing overwrite")
        else:
            store.upload_bundle([path])
        readback = ReleaseStore(REPOSITORY, RELEASE, work / "readback")
        readback._download_asset(path.name)
        if (readback.directory / path.name).read_bytes() != path.read_bytes():
            raise RuntimeError("CDB offer read-back mismatch")
        return sha256(path.read_bytes()).hexdigest()
    finally:
        release(REPOSITORY, state, if_held=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    report, status = load_evening_report(betting_day=args.day, now=now)
    payload = stage(report, day=args.day, now=now)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"aces-offers-{args.day}.json"
    path.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = persist(path, work=args.out) if args.apply else None
    print(json.dumps({"state": "VERIFIED" if digest else "PREPARED", "source_status": status,
                      "offer_status": payload["status"], "events": len(payload["events"]),
                      "incremental_provider_requests": 0, "cdb_written": bool(digest), "sha256": digest}))


if __name__ == "__main__":
    main()
