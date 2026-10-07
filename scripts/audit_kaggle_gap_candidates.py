from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Iterable

NULLS = {"", "na", "n/a", "nan", "none", "null", "-", "--"}
LEAK_PATTERNS = (
    "winner", "loser", "result", "outcome", "label", "target", "is_win",
    "won_match", "match_winner", "winner_name", "completed",
)
MARKET_PATTERNS = (
    "odds", "odd", "book", "bet365", "betfair", "ladbrokes", "unibet",
    "pinnacle", "open", "close", "closing", "handicap", "total", "line",
    "over", "under", "price", "margin", "vig",
)
PBP_PATTERNS = (
    "point", "pbp", "rally", "serve_speed", "speed", "timestamp",
    "server", "returner", "score_state", "ace", "double_fault",
)
IDENTITY_PATTERNS = (
    "player", "competitor", "name", "date", "time", "tournament",
    "event", "round", "surface", "match_id", "player_id",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_columns(columns: Iterable[str]) -> dict[str, list[str]]:
    out = {"leakage": [], "market": [], "pbp": [], "identity": []}
    for column in columns:
        low = column.lower().strip()
        if any(pattern in low for pattern in LEAK_PATTERNS):
            out["leakage"].append(column)
        if any(pattern in low for pattern in MARKET_PATTERNS):
            out["market"].append(column)
        if any(pattern in low for pattern in PBP_PATTERNS):
            out["pbp"].append(column)
        if any(pattern in low for pattern in IDENTITY_PATTERNS):
            out["identity"].append(column)
    return out


def open_text(path: Path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", errors="replace", newline="")
    return path.open("r", encoding="utf-8-sig", errors="replace", newline="")


def sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:
        counts = {delimiter: sample.count(delimiter) for delimiter in [",", ";", "\t", "|"]}
        return max(counts, key=counts.get)


def audit_csv(path: Path) -> dict:
    with open_text(path) as handle:
        probe = handle.read(65536)
    delimiter = sniff_delimiter(probe)
    nulls = Counter()
    rows = 0
    fields: list[str] = []

    with open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        fields = list(reader.fieldnames or [])
        for row in reader:
            rows += 1
            for field in fields:
                raw = row.get(field)
                value = "" if raw is None else str(raw).strip()
                if value.lower() in NULLS:
                    nulls[field] += 1

    return {
        "kind": "csv",
        "delimiter": delimiter,
        "rows": rows,
        "columns": fields,
        "column_count": len(fields),
        "null_ratio": {
            field: (round(nulls[field] / rows, 8) if rows else None)
            for field in fields
        },
        "column_classes": classify_columns(fields),
    }


def audit_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"kind": "json", "parse_error": str(exc)}

    if isinstance(data, list):
        keys = sorted({
            str(key)
            for row in data[:1000]
            if isinstance(row, dict)
            for key in row
        })
        return {
            "kind": "json",
            "top_level": "array",
            "rows": len(data),
            "columns": keys,
            "column_classes": classify_columns(keys),
        }

    if isinstance(data, dict):
        keys = sorted(map(str, data.keys()))
        return {
            "kind": "json",
            "top_level": "object",
            "keys": keys[:500],
            "column_classes": classify_columns(keys),
        }

    return {"kind": "json", "top_level": type(data).__name__}


def audit_sqlite(path: Path) -> dict:
    out = {"kind": "sqlite", "tables": []}
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        names = [
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type='table' order by name"
            )
        ]
        for name in names:
            safe = name.replace('"', '""')
            columns = [
                row[1]
                for row in connection.execute(f'pragma table_info("{safe}")')
            ]
            count = connection.execute(
                f'select count(*) from "{safe}"'
            ).fetchone()[0]
            out["tables"].append({
                "name": name,
                "rows": int(count),
                "columns": columns,
                "column_classes": classify_columns(columns),
            })
        connection.close()
    except Exception as exc:
        out["parse_error"] = str(exc)
    return out


def audit_file(path: Path, root: Path) -> dict:
    base = {
        "path": str(path.relative_to(root)),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }
    name = path.name.lower()

    try:
        if name.endswith(".csv") or name.endswith(".csv.gz"):
            detail = audit_csv(path)
        elif name.endswith(".json"):
            detail = audit_json(path)
        elif name.endswith(".sqlite") or name.endswith(".db"):
            detail = audit_sqlite(path)
        else:
            detail = {"kind": path.suffix.lower().lstrip(".") or "other"}
    except Exception as exc:
        detail = {"kind": "unknown", "audit_error": str(exc)}

    return {**base, **detail}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--download-status", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    root = Path(args.root)
    status = json.loads(Path(args.download_status).read_text(encoding="utf-8"))
    source_by_slug = {item["slug"]: item for item in request["sources"]}

    results = []
    for item in status.get("sources", []):
        slug = item["slug"]
        source = source_by_slug.get(slug, {})
        source_dir = root / item["safe_name"]
        record = {
            "slug": slug,
            "grade": source.get("grade"),
            "license_status": source.get("license_status"),
            "intended_use": source.get("intended_use"),
            "download_ok": bool(item.get("download_ok")),
            "archive_bytes": item.get("archive_bytes"),
            "archive_sha256": item.get("archive_sha256"),
            "download_error": item.get("download_error"),
            "files": [],
        }

        if record["download_ok"] and source_dir.exists():
            for path in sorted(source_dir.rglob("*")):
                if path.is_file():
                    record["files"].append(audit_file(path, source_dir))

        results.append(record)

    failed = [item["slug"] for item in results if not item["download_ok"]]
    report = {
        "schema": 1,
        "mode": "audit-only",
        "canonical_mutated": False,
        "provider_api_requests": 0,
        "model_promoted": False,
        "sources": results,
        "download_failures": failed,
        "summary": {
            "requested_sources": len(request.get("sources", [])),
            "downloaded_sources": len(results) - len(failed),
            "failed_sources": len(failed),
            "audited_files": sum(len(item.get("files", [])) for item in results),
        },
    }

    Path(args.out).write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
