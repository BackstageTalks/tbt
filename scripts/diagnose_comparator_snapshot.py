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
    # Prove byte-compatible model probabilities from the tiny indexed reader
    # before exposing it to an authenticated Azure request.
    from tbt.services.comparator_index import build_comparator_index, load_pair_artifact
    indexed_path = destination / "comparator-serving.sqlite3"
    start_index = time.perf_counter()
    info = build_comparator_index(artifact, indexed_path)
    directory = {
        "players": artifact["players"],
        "generated_at": artifact["generated_at"],
        "model_version": artifact["model"]["model_version"],
    }
    pair = load_pair_artifact(
        indexed_path, directory,
        player1=norrie[0]["player_id"], player2=svrcina[0]["player_id"], tour="atp",
    )
    # Compare the same fixed instant so time-sensitive rest/form stays identical.
    from datetime import datetime, timezone
    instant = datetime.now(timezone.utc)
    original = compare_from_artifact(
        artifact, player1=norrie[0]["player_id"], player2=svrcina[0]["player_id"],
        tour="atp", surface="hard", best_of=3, now=instant,
    )
    optimized = compare_from_artifact(
        pair, player1=norrie[0]["player_id"], player2=svrcina[0]["player_id"],
        tour="atp", surface="hard", best_of=3, now=instant,
    )
    json.dumps(optimized, allow_nan=False)
    p_source = original["player1"]["probability"]
    p_indexed = optimized["player1"]["probability"]
    if abs(p_source - p_indexed) > 1e-10 or optimized["winner"] != original["winner"]:
        raise RuntimeError("Indexed comparator probability or winner mismatch")
    print("INDEXED PARITY PASS", {
        "source_p": p_source, "indexed_p": p_indexed,
        "diff": abs(p_source-p_indexed),
        "bytes": info["bytes"], "h2h": info["h2h"], "player_states": info["players"],
        "index_build_s": round(time.perf_counter()-start_index, 2),
        "rss_mb": current_rss_mb(),
    }, flush=True)
    import subprocess
    directory_path = destination / "comparator-players.json"
    directory_path.write_text(json.dumps(directory, ensure_ascii=False), encoding="utf-8")
    child = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("smoke_comparator_index_worker.py")),
         str(indexed_path), str(directory_path)],
        capture_output=True, text=True, timeout=30,
    )
    print(child.stdout[-1500:], flush=True)
    if child.returncode:
        raise RuntimeError(f"Indexed cold-start failed: {child.stderr[-1600:]}")




if __name__ == "__main__":
    main()
