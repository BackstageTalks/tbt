"""Read-only production comparator reproducer (no model promotion or provider calls).

Runs only in PR CI against the checksum-verified private prediction release.
The test intentionally uses the exact player names/surface/format reported by users.
"""
from __future__ import annotations

import gzip
import json
import resource
import sys
import time
import traceback
from pathlib import Path

from release_store import ReleaseStore


def current_rss_mb():
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def main():
    destination = Path("/tmp/blinq-comparator-readonly-audit")
    release = ReleaseStore("BackstageTalks/tbt-data", "tbt-predictions-v1", destination)
    release.download(
        extra_names=("comparator.json.gz",),
        required_names=("comparator.json.gz",),
        require_bundle_manifest=True,
    )
    import os
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
    from tbt.services.comparator_runtime import compare_from_artifact, search_players
    start = time.perf_counter()
    with gzip.open(destination / "comparator.json.gz", "rt", encoding="utf-8") as src:
        artifact = json.load(src)
    print("SNAPSHOT loaded", {
        "schema": artifact.get("schema"),
        "generated_at": artifact.get("generated_at"),
        "model_version": (artifact.get("model") or {}).get("model_version"),
        "players": len(artifact.get("players") or []),
        "features": len((artifact.get("model") or {}).get("feature_names") or []),
        "state_players": len((artifact.get("feature_state") or {}).get("players") or {}),
        "read_s": round(time.perf_counter() - start, 2),
        "rss_mb": current_rss_mb(),
    }, flush=True)
    norrie = search_players(artifact, "Cameron Norrie", tour="atp")
    svrcina = search_players(artifact, "Dalibor Svrčina", tour="atp")
    print("SEARCH", {
        "norrie": len(norrie),
        "svrcina": len(svrcina),
        "norrie_exact": any(row["name"].casefold() == "cameron norrie" for row in norrie),
        "svrcina_candidates": [row["name"] for row in svrcina[:3]],
    }, flush=True)
    if not norrie or not svrcina:
        raise RuntimeError("User-selected players not present in serving snapshot")
    started = time.perf_counter()
    try:
        result = compare_from_artifact(
            artifact,
            player1=norrie[0]["player_id"], player2=svrcina[0]["player_id"],
            tour="atp", surface="hard", best_of=3,
        )
    except Exception as exc:
        print("SNAPSHOT COMPARE FAILED", {
            "error_type": type(exc).__name__,
            "error": str(exc)[:450],
            "elapsed_s": round(time.perf_counter() - started, 2),
            "rss_mb": current_rss_mb(),
        }, flush=True)
        traceback.print_exc()
        raise
    else:
        print("SNAPSHOT COMPARE PASS", {
            "model_version": result.get("model_version"),
            "probability": (result.get("player1") or {}).get("probability"),
            "duration_s": round(time.perf_counter() - started, 2),
            "rss_mb": current_rss_mb(),
            "api_requests": result.get("api_requests"),
        }, flush=True)
    assert result.get("api_requests") == 0


if __name__ == "__main__":
    main()
