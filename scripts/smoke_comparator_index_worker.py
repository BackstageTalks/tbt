"""Separate-process memory/time proof of one request using the indexed artifact."""
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from tbt.services.comparator_index import load_pair_artifact
from tbt.services.comparator_runtime import compare_from_artifact, search_players


def main():
    index = Path(sys.argv[1])
    directory = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    start = time.perf_counter()
    norrie = next(row for row in search_players(directory, "Cameron Norrie", tour="atp") if row["name"] == "Cameron Norrie")
    svrcina = next(row for row in search_players(directory, "Dalibor Svrčina", tour="atp") if row["name"] == "Dalibor Svrčina")
    artifact = load_pair_artifact(index, directory, player1=norrie["player_id"], player2=svrcina["player_id"], tour="atp")
    result = compare_from_artifact(artifact, player1=norrie["player_id"], player2=svrcina["player_id"], tour="atp", surface="hard", best_of=3)
    json.dumps(result, allow_nan=False)
    elapsed = time.perf_counter() - start
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print("INDEXED REQUEST PASS", {
        "elapsed_s": round(elapsed, 2),
        "peak_rss_mb": round(rss, 1),
        "probability": result["player1"]["probability"],
        "model_version": result["model_version"],
    }, flush=True)
    if rss > 768 or elapsed > 18:
        raise RuntimeError("Indexed request exceeds safe runtime envelope")


if __name__ == "__main__":
    main()
