from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

NULLS = {"", "na", "n/a", "nan", "none", "null", "-", "--"}
LEAK_PATTERNS = ("winner","loser","result","outcome","label","target","is_win","won_match","match_winner","winner_name","completed")
MARKET_PATTERNS = ("odds","odd","book","bet365","betfair","ladbrokes","unibet","pinnacle","open","close","closing","handicap","total","line","over","under","price","margin","vig")
PBP_PATTERNS = ("point","pbp","rally","serve_speed","speed","timestamp","server","returner","score_state","ace","double_fault")
RANK_PATTERNS = ("rank","ranking","points","playerid","player_id")
IDENTITY_PATTERNS = ("player","competitor","name","date","time","tournament","event","round","surface","match_id","player_id")

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def classify_columns(cols: list[str]) -> dict[str, list[str]]:
    out = {"leakage": [], "market": [], "pbp": [], "ranking": [], "identity": []}
    for c in cols:
        low = c.lower().strip()
        if any(p in low for p in LEAK_PATTERNS): out["leakage"].append(c)
        if any(p in low for p in MARKET_PATTERNS): out["market"].append(c)
        if any(p in low for p in PBP_PATTERNS): out["pbp"].append(c)
        if any(p in low for p in RANK_PATTERNS): out["ranking"].append(c)
        if any(p in low for p in IDENTITY_PATTERNS): out["identity"].append(c)
    return out

def open_text(path: Path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", errors="replace", newline="")
    return path.open("r", encoding="utf-8-sig", errors="replace", newline="")

def sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:
        counts = {d: sample.count(d) for d in [",", ";", "\t", "|"]}
        return max(counts, key=counts.get)

def audit_csv(path: Path) -> dict:
    with open_text(path) as h:
        probe = h.read(65536)
    delim = sniff_delimiter(probe)
    rows = 0
    fields: list[str] = []
    nulls = Counter()
    examples: dict[str, list[str]] = {}
    with open_text(path) as h:
        reader = csv.DictReader(h, delimiter=delim)
        fields = list(reader.fieldnames or [])
        examples = {f: [] for f in fields}
        for row in reader:
            rows += 1
            for f in fields:
                val = "" if row.get(f) is None else str(row.get(f)).strip()
                if val.lower() in NULLS:
                    nulls[f] += 1
                elif len(examples[f]) < 3 and val not in examples[f]:
                    examples[f].append(val[:120])
    return {
        "kind": "csv",
        "rows": rows,
        "columns": fields,
        "column_count": len(fields),
        "delimiter": delim,
        "null_ratio": {f: (round(nulls[f] / rows, 6) if rows else None) for f in fields},
        "sample_values": examples,
        "column_classes": classify_columns(fields),
    }

def audit_text_like(path: Path) -> dict:
    return {"kind": path.suffix.lower().lstrip(".") or "other"}

def audit_file(path: Path, root: Path) -> dict:
    base = {
        "path": str(path.relative_to(root)),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }
    low = path.name.lower()
    try:
        if low.endswith(".csv") or low.endswith(".csv.gz"):
            detail = audit_csv(path)
        else:
            detail = audit_text_like(path)
    except Exception as exc:
        detail = {"kind": "unknown", "audit_error": str(exc)}
    return {**base, **detail}

def download(url: str, out: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "BlinQ-data-audit/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, out.open("wb") as f:
        shutil.copyfileobj(r, f, length=1024 * 1024)

def split_file(path: Path, out_dir: Path, chunk_bytes: int) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    with path.open("rb") as src:
        idx = 0
        while True:
            data = src.read(chunk_bytes)
            if not data:
                break
            part = out_dir / f"{path.name}.part-{idx:04d}"
            part.write_bytes(data)
            parts.append({
                "file": part.name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
            idx += 1
    return parts

def safe_name(slug: str) -> str:
    return slug.replace("/", "__").replace(":", "_")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out-audit", required=True)
    ap.add_argument("--out-backup", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.request).read_text())
    work = Path(args.workdir)
    backup = Path(args.out_backup)
    work.mkdir(parents=True, exist_ok=True)
    backup.mkdir(parents=True, exist_ok=True)

    chunk_bytes = int(cfg["backup"]["raw_chunk_bytes"])
    reports = []

    for src in cfg["sources"]:
        slug = src["slug"]
        safe = safe_name(slug)
        source_work = work / safe
        source_backup = backup / safe
        source_work.mkdir(parents=True, exist_ok=True)
        source_backup.mkdir(parents=True, exist_ok=True)
        archive = source_work / "source.zip"
        url = f"https://www.kaggle.com/api/v1/datasets/download/{slug}"

        rec = {
            "slug": slug,
            "grade": src.get("grade"),
            "license_status": src.get("license_status"),
            "intended_use": src.get("intended_use"),
            "download_url": url,
            "download_ok": False,
            "canonical_mutated": False,
            "provider_api_requests": 0,
            "files": [],
        }

        try:
            download(url, archive)
            rec["download_ok"] = True
            rec["archive_bytes"] = archive.stat().st_size
            rec["archive_sha256"] = sha256(archive)

            unpacked = source_work / "unpacked"
            unpacked.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as zf:
                bad = zf.testzip()
                if bad:
                    raise RuntimeError(f"zip CRC failure: {bad}")
                zf.extractall(unpacked)

            for p in sorted(unpacked.rglob("*")):
                if p.is_file():
                    rec["files"].append(audit_file(p, unpacked))

            if cfg["backup"].get("persist_raw_archives"):
                parts_dir = source_backup / "raw"
                parts = split_file(archive, parts_dir, chunk_bytes)
            else:
                parts = []

            source_manifest = {
                "schema": 1,
                "source": {
                    "platform": "Kaggle",
                    "slug": slug,
                    "download_url": url,
                    "license_status": src.get("license_status"),
                    "grade": src.get("grade"),
                    "intended_use": src.get("intended_use"),
                },
                "archive": {
                    "bytes": rec.get("archive_bytes"),
                    "sha256": rec.get("archive_sha256"),
                    "parts": parts,
                    "reassembly": "cat raw/source.zip.part-* > source.zip",
                },
                "files": rec["files"],
                "canonical_mutated": False,
                "provider_api_requests": 0,
                "model_promoted": False,
            }
            (source_backup / "manifest.json").write_text(
                json.dumps(source_manifest, indent=2, ensure_ascii=False)
            )
        except Exception as exc:
            rec["download_error"] = str(exc)
            (source_backup / "ERROR.txt").write_text(str(exc))

        reports.append(rec)

    summary = {
        "requested": len(reports),
        "downloaded": sum(1 for r in reports if r["download_ok"]),
        "failed": sum(1 for r in reports if not r["download_ok"]),
        "audited_files": sum(len(r["files"]) for r in reports),
    }
    audit = {
        "schema": 1,
        "mode": cfg["mode"],
        "canonical_mutated": False,
        "provider_api_requests": 0,
        "model_promoted": False,
        "summary": summary,
        "sources": reports,
    }
    Path(args.out_audit).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_audit).write_text(json.dumps(audit, indent=2, ensure_ascii=False))
    (backup / "backup-index.json").write_text(json.dumps({
        "schema": 1,
        "backup_root": cfg["backup"]["root"],
        "created_from_request": Path(args.request).name,
        "summary": summary,
        "sources": [
            {
                "slug": r["slug"],
                "download_ok": r["download_ok"],
                "archive_bytes": r.get("archive_bytes"),
                "archive_sha256": r.get("archive_sha256"),
            }
            for r in reports
        ],
        "canonical_mutated": False,
    }, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
