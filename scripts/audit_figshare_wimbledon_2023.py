"""Audit the CC BY 4.0 Figshare Wimbledon 2023 dataset in isolation.

The auditor is deliberately schema-tolerant because Figshare packages can
contain CSV/XLSX/JSON/TXT files. It emits only a research audit and never
mutates canonical BlinQ history or model features.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

SOURCE = "Figshare Tennis Data / Wimbledon 2023"
DOI = "10.6084/m9.figshare.25511917"
LICENSE = "CC BY 4.0"

POINT_HINTS = {
    "point",
    "server",
    "serve",
    "score",
    "winner",
    "rally",
    "break",
    "ace",
    "fault",
    "set",
    "game",
    "elapsed",
}
IDENTITY_HINTS = {
    "player1",
    "player2",
    "p1",
    "p2",
    "match_id",
    "matchid",
    "player",
    "server",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _safe_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def _frame_summary(frame: pd.DataFrame, *, name: str) -> dict[str, Any]:
    columns = [str(c) for c in frame.columns]
    normalized = [norm(c) for c in columns]
    rows = int(len(frame))

    non_null_rate = {}
    for column in columns[:200]:
        series = frame[column]
        rate = float(series.notna().mean()) if rows else 0.0
        non_null_rate[column] = rate

    relevant_columns = [
        column
        for column, key in zip(columns, normalized)
        if any(token in key for token in POINT_HINTS | IDENTITY_HINTS)
    ]
    identity_score = sum(
        1 for key in normalized if any(token == key or token in key for token in IDENTITY_HINTS)
    )
    point_score = sum(
        1 for key in normalized if any(token == key or token in key for token in POINT_HINTS)
    )

    sample = []
    for _, raw in frame.head(3).iterrows():
        sample.append({str(k): _safe_scalar(v) for k, v in raw.to_dict().items()})

    numeric = {}
    for column in columns:
        series = frame[column]
        if not pd.api.types.is_numeric_dtype(series):
            continue
        clean = pd.to_numeric(series, errors="coerce").dropna()
        if clean.empty:
            continue
        numeric[column] = {
            "count": int(clean.size),
            "min": float(clean.min()),
            "max": float(clean.max()),
            "mean": float(clean.mean()),
        }

    return {
        "name": name,
        "rows": rows,
        "columns": columns,
        "column_count": len(columns),
        "relevant_columns": relevant_columns,
        "point_schema_score": point_score,
        "identity_schema_score": identity_score,
        "non_null_rate": non_null_rate,
        "numeric_summary": numeric,
        "sample": sample,
    }


def _read_csv(path: Path) -> pd.DataFrame:
    attempts = [
        {"sep": None, "engine": "python"},
        {"sep": ","},
        {"sep": ";"},
        {"sep": "\t"},
    ]
    last: Exception | None = None
    for kwargs in attempts:
        try:
            return pd.read_csv(path, encoding="utf-8-sig", low_memory=False, **kwargs)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"Unable to parse CSV {path}: {last}")


def inspect_file(path: Path, root: Path) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    result: dict[str, Any] = {
        "path": rel,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "suffix": path.suffix.lower(),
    }

    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            result["tables"] = [_frame_summary(_read_csv(path), name=rel)]
        elif suffix in {".xlsx", ".xls"}:
            sheets = pd.read_excel(path, sheet_name=None)
            result["tables"] = [
                _frame_summary(frame, name=f"{rel}::{sheet}")
                for sheet, frame in sheets.items()
            ]
        elif suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                result["tables"] = [_frame_summary(pd.DataFrame(payload), name=rel)]
            elif isinstance(payload, dict):
                for key, value in payload.items():
                    if isinstance(value, list) and value and isinstance(value[0], dict):
                        result.setdefault("tables", []).append(
                            _frame_summary(pd.DataFrame(value), name=f"{rel}::{key}")
                        )
        elif suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            result["text_preview"] = text[:4000]
    except Exception as exc:
        result["parse_error"] = f"{type(exc).__name__}: {exc}"

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(args.source_dir)
    if not root.is_dir():
        raise SystemExit("Source directory missing")

    files = [
        path for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.startswith(".")
    ]
    if not files:
        raise SystemExit("No Figshare files found")

    inspected = [inspect_file(path, root) for path in files]
    tables = [
        table
        for item in inspected
        for table in item.get("tables", [])
        if isinstance(table, dict)
    ]

    rows_total = sum(int(table.get("rows") or 0) for table in tables)
    point_candidates = sorted(
        [
            {
                "name": table["name"],
                "rows": table["rows"],
                "point_schema_score": table["point_schema_score"],
                "identity_schema_score": table["identity_schema_score"],
                "relevant_columns": table["relevant_columns"],
            }
            for table in tables
            if int(table.get("point_schema_score") or 0) >= 3
        ],
        key=lambda row: (
            int(row["point_schema_score"]),
            int(row["identity_schema_score"]),
            int(row["rows"]),
        ),
        reverse=True,
    )

    report = {
        "schema": 1,
        "status": "verified" if tables else "no_tabular_data",
        "source": SOURCE,
        "doi": DOI,
        "license": LICENSE,
        "production_mutated": False,
        "canonical_history_mutated": False,
        "model_promoted": False,
        "file_count": len(files),
        "table_count": len(tables),
        "tabular_rows_total": rows_total,
        "files": inspected,
        "point_table_candidates": point_candidates,
        "policy": (
            "research-only isolated audit; no canonical write; no fuzzy identity; "
            "no target-match point or post-match data may become a pre-match feature"
        ),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "file_count": report["file_count"],
        "table_count": report["table_count"],
        "tabular_rows_total": report["tabular_rows_total"],
        "point_candidates": len(point_candidates),
    }, indent=2))


if __name__ == "__main__":
    main()
