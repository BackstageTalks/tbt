from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from tbt.data.history_snapshot import load_snapshot, minimize_provider_payload, write_snapshot
from tbt.repositories.supabase import SupabaseRepository

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


def _latest_updated_at(repo: SupabaseRepository) -> str | None:
    rows = repo.select_all(
        "matches",
        filters={"winner_id": "not.is.null"},
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build/update the normalized TBT GitHub Release history snapshot")
    parser.add_argument("--snapshot", default=str(ROOT / ".cache" / "tbt" / "training_snapshot.parquet"))
    parser.add_argument("--meta", default=str(ROOT / ".cache" / "tbt" / "training_snapshot.meta.json"))
    parser.add_argument("--full", action="store_true", help="Explicitly allow a full canonical Supabase bootstrap")
    parser.add_argument("--overlap-minutes", type=int, default=10)
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot)
    meta_path = Path(args.meta)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    repo = SupabaseRepository()

    existing = []
    previous_meta: dict[str, Any] = {}
    if snapshot_path.is_file() and not args.full:
        existing = load_snapshot(snapshot_path)
        if meta_path.is_file():
            try:
                previous_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (ValueError, json.JSONDecodeError):
                previous_meta = {}

    if args.full:
        print("V20.1 history sync: EXPLICIT bootstrap/full mode — one canonical Supabase history read")
        matches = repo.get_completed_matches()
        for row in matches:
            row.provider_payload = minimize_provider_payload(row.provider_payload)
        source_updated_at_max = _latest_updated_at(repo)
        changed_count = len(matches)
        mode = "full"
    else:
        if not existing:
            raise SystemExit(
                "V20.1 safety stop: no existing GitHub snapshot was downloaded. "
                "Refusing an implicit full Supabase history read. Re-run the workflow manually with full=true "
                "only for the one-time bootstrap or an intentional disaster recovery rebuild."
            )

        cursor = _parse_dt(previous_meta.get("source_updated_at_max"))
        if cursor is None:
            raise SystemExit(
                "V20.1 safety stop: previous snapshot metadata has no valid source_updated_at_max. "
                "Refusing to guess a cursor and refusing a hidden full read."
            )
        cursor = cursor - timedelta(minutes=max(0, args.overlap_minutes))
        print(f"V20.1 history sync: incremental mode from updated_at > {cursor.isoformat()}")
        raw_rows = repo.select_all(
            "matches",
            filters={"winner_id": "not.is.null", "updated_at": f"gt.{cursor.isoformat()}"},
            select=MATCH_SELECT,
            order="updated_at.asc",
            page_size=1000,
        )
        changed = [repo._match_from_row(row) for row in raw_rows]
        matches = _merge(existing, changed, repo)
        updated_values = [str(row.get("updated_at")) for row in raw_rows if row.get("updated_at")]
        source_updated_at_max = max(updated_values) if updated_values else previous_meta.get("source_updated_at_max")
        changed_count = len(changed)
        mode = "incremental"

    snapshot_meta = write_snapshot(matches, snapshot_path)
    snapshot_meta.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "changed_rows_read_from_supabase": changed_count,
            "source_updated_at_max": source_updated_at_max,
            "source": "Supabase operational DB -> normalized private GitHub Release snapshot",
        }
    )
    meta_path.write_text(json.dumps(snapshot_meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(snapshot_meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
