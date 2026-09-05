from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from _bootstrap import ROOT
from tbt.data.history_snapshot import load_partitions
from tbt.repositories.supabase import SupabaseRepository


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore only the rolling recent match buffer from GH history into Supabase."
    )
    parser.add_argument("--history-dir", default=str(ROOT / ".cache" / "tbt" / "history"))
    parser.add_argument("--retention-days", type=int, default=60)
    args = parser.parse_args()

    if args.retention_days < 14 or args.retention_days > 180:
        raise SystemExit("--retention-days must be between 14 and 180")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.retention_days)
    history = load_partitions(args.history_dir, before=now + timedelta(days=1))
    recent = [match for match in history if match.scheduled_at >= cutoff]

    repo = SupabaseRepository()
    written = repo.upsert_matches(recent)
    print(
        json.dumps(
            {
                "retention_days": args.retention_days,
                "cutoff": cutoff.isoformat(),
                "history_rows_scanned": len(history),
                "recent_rows_selected": len(recent),
                "rows_upserted": written,
                "year_independent": True,
                "raw_provider_payload_restored": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
