from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from tbt.data.history_snapshot import load_snapshot, write_snapshot
from tbt.services.environment import OpenMeteoClient, environment_payload, location_candidates

logger = logging.getLogger("tbt.enrich_environment_snapshot")

HOT_TIER_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def parse_utc(value: str) -> datetime:
    text = value.strip()
    if len(text) == 10:
        text += "T00:00:00+00:00"
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich pre-2025 historical matches inside the GitHub Release snapshot. "
            "Supabase is deliberately not used."
        )
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep-ms", type=int, default=50)
    parser.add_argument("--diagnostics-limit", type=int, default=100)
    parser.add_argument(
        "--snapshot",
        default=str(ROOT / ".cache" / "tbt" / "training_snapshot.parquet"),
    )
    parser.add_argument(
        "--meta",
        default=str(ROOT / ".cache" / "tbt" / "training_snapshot.meta.json"),
    )
    args = parser.parse_args()

    start = parse_utc(args.start)
    end = parse_utc(args.end)
    if end <= start:
        raise SystemExit("--end must be later than --start")
    if end > HOT_TIER_START:
        raise SystemExit(
            "V20.4 safety stop: GitHub historical environment enrichment is restricted "
            "to dates before 2025-01-01. Use the Supabase hot-tier path for 2025+."
        )

    snapshot_path = Path(args.snapshot)
    meta_path = Path(args.meta)
    previous_meta = _load_meta(meta_path)
    matches = load_snapshot(snapshot_path)
    candidates = [
        match
        for match in matches
        if start <= match.scheduled_at.astimezone(timezone.utc) < end
        and match.is_completed
    ]
    if args.limit > 0:
        candidates = candidates[: args.limit]

    weather = OpenMeteoClient()
    report: dict[str, Any] = {
        "target": "github-release-snapshot",
        "supabase_used": False,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "inspected": 0,
        "already_enriched": 0,
        "resolved": 0,
        "unresolved": 0,
        "updated": 0,
        "errors": 0,
        "dry_run": bool(args.dry_run),
        "unresolved_details": [],
        "resolved_details": [],
        "error_details": [],
    }

    try:
        for index, match in enumerate(candidates, start=1):
            report["inspected"] += 1
            payload = dict(match.provider_payload or {})
            existing = payload.get("_tbt_environment")
            if (
                not args.force
                and isinstance(existing, dict)
                and existing.get("venue_resolved") is True
            ):
                report["already_enriched"] += 1
                continue

            location_options = location_candidates(payload, match.tournament)
            try:
                env = environment_payload(
                    weather,
                    payload,
                    match.tournament,
                    match.scheduled_at,
                )
                payload["_tbt_environment"] = env

                detail = {
                    "match_id": match.match_id,
                    "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                    "tour": match.tour,
                    "tournament": match.tournament,
                    "location_candidates": location_options,
                }
                if env.get("venue_resolved"):
                    report["resolved"] += 1
                    detail["resolved_query"] = env.get("location_query")
                    detail["resolved_venue"] = env.get("venue")
                    if len(report["resolved_details"]) < args.diagnostics_limit:
                        report["resolved_details"].append(detail)
                else:
                    report["unresolved"] += 1
                    if len(report["unresolved_details"]) < args.diagnostics_limit:
                        report["unresolved_details"].append(detail)

                if not args.dry_run:
                    match.provider_payload = payload
                    report["updated"] += 1
            except Exception as exc:
                report["errors"] += 1
                logger.warning(
                    "Snapshot environment enrichment failed match=%s tournament=%r: %s",
                    match.match_id,
                    match.tournament,
                    exc,
                )
                if len(report["error_details"]) < args.diagnostics_limit:
                    report["error_details"].append(
                        {
                            "match_id": match.match_id,
                            "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
                            "tour": match.tour,
                            "tournament": match.tournament,
                            "location_candidates": location_options,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

            if index % 250 == 0:
                logger.info(
                    "Progress %s/%s resolved=%s unresolved=%s errors=%s",
                    index,
                    len(candidates),
                    report["resolved"],
                    report["unresolved"],
                    report["errors"],
                )
            if args.sleep_ms > 0:
                time.sleep(args.sleep_ms / 1000.0)
    finally:
        weather.close()

    if not args.dry_run and report["updated"] > 0:
        snapshot_meta = write_snapshot(matches, snapshot_path)
        snapshot_meta.update(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "mode": "github-history-environment-enrichment",
                "source": previous_meta.get(
                    "source",
                    "normalized private GitHub Release snapshot",
                ),
                "source_updated_at_max": previous_meta.get("source_updated_at_max"),
                "storage_policy": previous_meta.get("storage_policy"),
                "last_direct_provider_backfill": previous_meta.get(
                    "last_direct_provider_backfill"
                ),
                "completed_direct_provider_months": previous_meta.get(
                    "completed_direct_provider_months", []
                ),
                "last_environment_enrichment": {
                    "target": "github-release-snapshot",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "updated": report["updated"],
                    "resolved": report["resolved"],
                    "unresolved": report["unresolved"],
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            }
        )
        # Drop null compatibility keys instead of polluting metadata.
        snapshot_meta = {key: value for key, value in snapshot_meta.items() if value is not None}
        meta_path.write_text(
            json.dumps(snapshot_meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        report["snapshot_sha256"] = snapshot_meta["sha256"]
        report["snapshot_rows"] = snapshot_meta["rows"]

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
