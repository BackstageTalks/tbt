"""Remove only explicitly audited impossible self-matches from a history partition."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT
from release_store import ReleaseStore


TARGET_MATCH_ID = "7f395aed57cd10dfcf4e2779"
TARGET_YEAR = 2026


def clean_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    args = parser.parse_args()

    directory = ROOT / ".cache/tbt/history-repair"
    store = ReleaseStore(args.data_repository, "tbt-data-v1", directory)
    store.download()

    path = directory / f"history-{TARGET_YEAR}.parquet"
    if not path.is_file():
        raise SystemExit(f"Missing {path.name}")

    frame = pd.read_parquet(path, engine="pyarrow")
    before = len(frame)

    mask = frame["match_id"].astype(str) == TARGET_MATCH_ID
    matches = frame.loc[mask]

    if len(matches) != 1:
        raise SystemExit(
            f"Expected exactly one target row, found {len(matches)}"
        )

    row = matches.iloc[0]
    p1 = clean_text(row.get("player1_id"))
    p2 = clean_text(row.get("player2_id"))

    if not p1 or p1 != p2:
        raise SystemExit(
            "Target row no longer matches the audited identical-player condition; refusing repair."
        )

    repaired = frame.loc[~mask].copy()
    temporary = path.with_name(path.name + ".tmp")

    repaired.to_parquet(
        temporary,
        engine="pyarrow",
        compression="zstd",
        index=False,
    )
    temporary.replace(path)

    report = {
        "file": path.name,
        "removed_rows": 1,
        "match_id": TARGET_MATCH_ID,
        "rows_before": int(before),
        "rows_after": int(len(repaired)),
        "reason": "impossible self-match: player1_id == player2_id",
    }

    report_path = directory / "history_repair_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    store.upload_bundle([path, report_path])

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
