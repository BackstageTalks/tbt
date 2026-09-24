"""Read-only bulk Environment audit. Does not call geocoders or upload history."""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT
from enrich_environment_snapshot import _build_venue_knowledge
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.services.environment import location_candidates


def main() -> None:
    # Download the existing private release into the runner's temporary
    # directory. Keep raw names and the detailed history out of public logs.
    with tempfile.TemporaryDirectory(prefix="blinq-environment-audit-") as tmp:
        history_dir = Path(tmp)
        store = ReleaseStore(
            os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
            "tbt-data-v1",
            history_dir,
        )
        store.download()
        matches, safety = sanitize_history_identities(
            load_partitions(history_dir, years=range(2021, datetime.now(timezone.utc).year + 1))
        )
        knowledge = _build_venue_knowledge(matches)
        totals = Counter()
        tournament_groups = set()
        missing_groups = set()
        query_groups = set()
        cache_groups = set()
        unknown_groups = set()
        for match in matches:
            if not match.is_completed:
                continue
            totals["historical_matches"] += 1
            payload = dict(match.provider_payload or {})
            env = payload.get("_tbt_environment")
            env = env if isinstance(env, dict) else {}
            group = (
                str(match.tour or "").casefold(),
                str(match.tournament_id or "").strip()
                or str(match.tournament or "").casefold().strip(),
            )
            tournament_groups.add(group)
            if env.get("venue_resolved") is True:
                totals["already_resolved"] += 1
                continue
            totals["missing_venue"] += 1
            missing_groups.add(group)
            cached, _ = knowledge.lookup(match, payload)
            if cached:
                totals["cache_recoverable_matches"] += 1
                cache_groups.add(group)
                continue
            candidates = location_candidates(payload, str(match.tournament or ""))
            if candidates:
                totals["has_geocode_candidate_matches"] += 1
                query_groups.add(group)
                # First candidate is preferred; count *distinct* requests
                # separately from matches requiring one.
                key = " ".join(candidates[0].casefold().split())
                query_groups.add(("query", key))
            else:
                totals["no_candidate_matches"] += 1
                unknown_groups.add(group)

        output = {
            "audited_at_utc": datetime.now(timezone.utc).isoformat(),
            "counts": dict(totals),
            "unique_tournaments": len(tournament_groups),
            "unique_tournaments_missing_venue": len(missing_groups),
            "unique_tournaments_recoverable_from_cache": len(cache_groups),
            "unique_tournaments_without_candidate": len(unknown_groups),
            "unique_preferred_geocode_queries": sum(1 for k in query_groups if k[0] == "query"),
            "api_requests_used": 0,
            "note": "Unique preferred query count is a candidate upper bound, not confirmed geocoding success.",
        }
        report = Path("environment_bulk_audit.json")
        report.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
        # Only aggregate numbers are emitted; no player or tournament raw data.
        print(json.dumps({k: v for k, v in output.items() if k != "history_identity_safety"}, indent=2))
        summary = os.getenv("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("## BlinQ Environment bulk audit (read-only)\n\n")
                for key, value in output["counts"].items():
                    fh.write(f"- **{key}**: {value:,}\n")
                for key in (
                    "unique_tournaments", "unique_tournaments_missing_venue",
                    "unique_tournaments_recoverable_from_cache",
                    "unique_tournaments_without_candidate", "unique_preferred_geocode_queries",
                ):
                    fh.write(f"- **{key}**: {output[key]:,}\n")
                fh.write("\nNo geocoding requests, no writes to historical releases.\n")


if __name__ == "__main__":
    main()
