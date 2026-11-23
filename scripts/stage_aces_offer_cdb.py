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
import subprocess
import tempfile

from propline_evening_quotes import load_evening_report, validated_events, _valid_report

REPOSITORY = "BackstageTalks/tbt-data"
RELEASE = "tbt-data-v1"


def stage(report, *, day, now):
    date.fromisoformat(day)
    if not _valid_report(report, betting_day=day, now=now):
        raise ValueError("Missing, stale or incomplete source archive; do not refetch provider")
    # Keep immutable pre-start observations even after kickoff; the consumer
    # filters them against its actual clock. A rerun cannot shrink the file.
    captured = datetime.fromisoformat(report["captured_at"])
    events = validated_events(report, betting_day=day, now=captured)
    if len(events) != len(report["events_in_target_window"]):
        raise ValueError("Invalid native event evidence in source archive")
    ids = [str(e["event_id"]) for e in events]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate provider fixture in archive")
    # Retain source evidence so any downstream reader can revalidate identity,
    # timestamp, native payload hash and parsed lines without a provider call.
    return {"schema": 1, "scope": "prematch_aces_offers", "target_day": day,
            "source": "propline", "source_captured_at": report["captured_at"],
            "archive_header": {key: report[key] for key in (
                "schema", "source", "target_betting_day", "status", "captured_at",
                "provider_requests", "provider_event_requests", "provider_paid_calls",
                "cdb_writes", "published_picks_changed", "coverage_truncated")},
            "source_sha256": sha256(json.dumps(report, sort_keys=True,
                ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
            "events": events, "incremental_provider_requests": 0,
            "status": "offers_available" if any(e.get("aces_markets") for e in events) else "bez ponuky"}


def load_cdb_report(*, day, now, runner=None):
    """Read committed sidecar bytes and verify the CDB bundle checksum, no writes."""
    try:
        date.fromisoformat(day)
        name = f"aces-offers-{day}.json"
        runner = runner or (lambda args: subprocess.run(args, check=True, capture_output=True, timeout=45))
        with tempfile.TemporaryDirectory(prefix="aces-cdb-read-") as folder:
            runner(["gh", "release", "download", RELEASE, "--repo", REPOSITORY,
                    "--pattern", name, "--pattern", "_tbt_bundle_manifest.json", "--dir", folder])
            raw = (Path(folder) / name).read_bytes()
            manifest = json.loads((Path(folder) / "_tbt_bundle_manifest.json").read_text(encoding="utf-8"))
            expected = manifest["files"][name]
            if expected["sha256"] != sha256(raw).hexdigest() or expected["bytes"] != len(raw):
                return None, "cdb_checksum_mismatch"
            payload = json.loads(raw)
            if (payload.get("schema") != 1 or payload.get("scope") != "prematch_aces_offers"
                    or payload.get("target_day") != day or payload.get("source") != "propline"):
                return None, "invalid_cdb_sidecar"
            report = {**payload["archive_header"], "events_in_target_window": payload["events"]}
            if not _valid_report(report, betting_day=day, now=now):
                return None, "stale_or_invalid_cdb_sidecar"
            return report, "cdb_verified"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        return None, "cdb_unavailable:" + type(exc).__name__


def persist(path, *, work):
    from cdb_global_writer_lock import acquire, release
    from release_store import ReleaseStore

    state = Path(".cdb-global-writer-lock.json")
    acquire(REPOSITORY, state, wait_seconds=900)
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
    parser.add_argument("--report", type=Path, help="Already captured source report; no provider call")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    report, status = ((json.loads(args.report.read_text(encoding="utf-8")), "local_capture")
                      if args.report else load_evening_report(betting_day=args.day, now=now))
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
