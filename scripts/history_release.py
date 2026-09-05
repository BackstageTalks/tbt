from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from tbt.data.history_snapshot import load_snapshot, minimize_provider_payload, write_snapshot
from tbt.repositories.supabase import SupabaseRepository

HOT_TIER_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
HOT_TIER_FILTER = HOT_TIER_START.isoformat()

MATCH_SELECT = ",".join(
    (
        "match_id", "tour", "scheduled_at", "player1_id", "player1_name",
        "player2_id", "player2_name", "surface", "tournament", "tournament_id",
        "tournament_level", "round_name", "player1_rank", "player2_rank",
        "winner_id", "status", "best_of", "indoor", "stats", "provider_payload", "updated_at",
    )
)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _latest_hot_updated_at(repo: SupabaseRepository) -> str | None:
    rows = repo.select_all(
        "matches",
        filters={
            "winner_id": "not.is.null",
            "scheduled_at": f"gte.{HOT_TIER_FILTER}",
        },
        select="updated_at",
        order="updated_at.desc",
        max_rows=1,
        page_size=1,
    )
    return str(rows[0].get("updated_at")) if rows and rows[0].get("updated_at") else None


def _provider_event_id(match) -> str | None:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    for key in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    return str(event.get("id")) if event.get("id") not in (None, "") else None


def _merge(existing, changed, repo: SupabaseRepository):
    by_match_id = {str(row.match_id): row for row in existing}
    for row in changed:
        row.provider_payload = minimize_provider_payload(row.provider_payload)
        by_match_id[str(row.match_id)] = row
    combined = list(by_match_id.values())

    dedupe = getattr(repo, "_dedupe_completed_matches", None)
    if callable(dedupe):
        return dedupe(combined)

    by_provider: dict[str, Any] = {}
    without: list[Any] = []
    for row in sorted(combined, key=lambda item: (item.scheduled_at, str(item.match_id))):
        provider_id = _provider_event_id(row)
        if provider_id:
            by_provider[provider_id] = row
        else:
            without.append(row)
    result = list(by_provider.values()) + without
    result.sort(key=lambda item: (item.scheduled_at, str(item.match_id)))
    return result


def _load_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (ValueError, json.JSONDecodeError):
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Update the normalized TBT GitHub Release snapshot from the Supabase hot tier only. "
            "Cold history (<2025) is GitHub/provider-managed in V20.4."
        )
    )
    parser.add_argument("--snapshot", default=str(ROOT / ".cache" / "tbt" / "training_snapshot.parquet"))
    parser.add_argument("--meta", default=str(ROOT / ".cache" / "tbt" / "training_snapshot.meta.json"))
    parser.add_argument(
        "--hot-full-refresh",
        action="store_true",
        help="Explicitly re-read all completed Supabase matches from 2025 onward only",
    )
    parser.add_argument("--overlap-minutes", type=int, default=10)
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot)
    meta_path = Path(args.meta)
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    if not snapshot_path.is_file():
        raise SystemExit(
            "V20.4 safety stop: the private GitHub snapshot is missing. "
            "Supabase no longer contains the authoritative cold tier, so this workflow "
            "will not attempt to reconstruct all history from Supabase. Restore/download "
            "the release snapshot or bootstrap cold history directly from the provider."
        )

    repo = SupabaseRepository()
    existing = load_snapshot(snapshot_path)
    previous_meta = _load_meta(meta_path)

    if args.hot_full_refresh:
        print("V20.4 history sync: explicit HOT-TIER full refresh (2025+ only)")
        raw_rows = repo.select_all(
            "matches",
            filters={
                "winner_id": "not.is.null",
                "scheduled_at": f"gte.{HOT_TIER_FILTER}",
            },
            select=MATCH_SELECT,
            order="updated_at.asc",
            page_size=1000,
        )
        changed = [repo._match_from_row(row) for row in raw_rows]
        matches = _merge(existing, changed, repo)
        source_updated_at_max = _latest_hot_updated_at(repo)
        changed_count = len(changed)
        mode = "hot-full-refresh"
    else:
        cursor = _parse_dt(previous_meta.get("source_updated_at_max"))
        if cursor is None:
            # A direct-provider snapshot may legitimately predate the Supabase cursor.
            # Seed the cursor with one small hot-tier read rather than falling back to a full table scan.
            source_updated_at_max = _latest_hot_updated_at(repo)
            if source_updated_at_max is None:
                matches = existing
                changed_count = 0
                mode = "hot-incremental-empty"
            else:
                cursor = HOT_TIER_START - timedelta(minutes=max(0, args.overlap_minutes))
                raw_rows = repo.select_all(
                    "matches",
                    filters={
                        "winner_id": "not.is.null",
                        "scheduled_at": f"gte.{HOT_TIER_FILTER}",
                        "updated_at": f"gt.{cursor.isoformat()}",
                    },
                    select=MATCH_SELECT,
                    order="updated_at.asc",
                    page_size=1000,
                )
                changed = [repo._match_from_row(row) for row in raw_rows]
                matches = _merge(existing, changed, repo)
                updated_values = [str(row.get("updated_at")) for row in raw_rows if row.get("updated_at")]
                source_updated_at_max = max(updated_values) if updated_values else source_updated_at_max
                changed_count = len(changed)
                mode = "hot-incremental-seed"
        else:
            cursor = max(
                HOT_TIER_START,
                cursor - timedelta(minutes=max(0, args.overlap_minutes)),
            )
            print(f"V20.4 history sync: hot-tier incremental mode from updated_at > {cursor.isoformat()}")
            raw_rows = repo.select_all(
                "matches",
                filters={
                    "winner_id": "not.is.null",
                    "scheduled_at": f"gte.{HOT_TIER_FILTER}",
                    "updated_at": f"gt.{cursor.isoformat()}",
                },
                select=MATCH_SELECT,
                order="updated_at.asc",
                page_size=1000,
            )
            changed = [repo._match_from_row(row) for row in raw_rows]
            matches = _merge(existing, changed, repo)
            updated_values = [str(row.get("updated_at")) for row in raw_rows if row.get("updated_at")]
            source_updated_at_max = (
                max(updated_values)
                if updated_values
                else previous_meta.get("source_updated_at_max")
            )
            changed_count = len(changed)
            mode = "hot-incremental"

    snapshot_meta = write_snapshot(matches, snapshot_path)
    snapshot_meta.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "changed_rows_read_from_supabase": changed_count,
            "source_updated_at_max": source_updated_at_max,
            "source": "Hybrid V20.4: GitHub cold tier + Supabase hot tier (2025+) -> private GitHub Release snapshot",
            "storage_policy": {
                "cold_history_before": HOT_TIER_START.date().isoformat(),
                "cold_history_store": "private GitHub Release",
                "hot_history_from": HOT_TIER_START.date().isoformat(),
                "hot_history_store": "Supabase operational DB + GitHub training snapshot",
            },
            "last_direct_provider_backfill": previous_meta.get("last_direct_provider_backfill"),
            "completed_direct_provider_months": previous_meta.get("completed_direct_provider_months", []),
            "last_environment_enrichment": previous_meta.get("last_environment_enrichment"),
        }
    )
    snapshot_meta = {key: value for key, value in snapshot_meta.items() if value is not None}
    meta_path.write_text(json.dumps(snapshot_meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(snapshot_meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
