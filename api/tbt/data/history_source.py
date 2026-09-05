from __future__ import annotations

import os
from pathlib import Path

from tbt.schemas import MatchRecord
from .history_snapshot import load_partitions


def default_history_dir(root: str | Path | None = None) -> Path:
    configured = str(os.getenv("TBT_HISTORY_DIR") or "").strip()
    if configured:
        return Path(configured)
    if root is not None:
        return Path(root) / ".cache" / "tbt" / "history"
    return Path(".cache/tbt/history")


def load_training_history(
    history_dir: str | Path | None = None,
    *,
    root: str | Path | None = None,
) -> list[MatchRecord]:
    directory = Path(history_dir) if history_dir else default_history_dir(root)
    matches = load_partitions(directory)
    completed = [match for match in matches if match.is_completed and match.winner_id]
    completed.sort(key=lambda match: (match.scheduled_at, str(match.match_id)))
    if not completed:
        raise RuntimeError(f"No completed matches found in GitHub history partitions: {directory}")
    return completed
