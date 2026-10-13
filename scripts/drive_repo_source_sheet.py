#!/usr/bin/env python3
"""Private, read-only Drive and GitHub source inventory for BlinQ.

Creates a spreadsheet-compatible CSV and a separately verified baseline.
No provider scraping, source relocation, CDB writes or import authorization.
Names, paths and IDs are PRIVATE and must never be printed into Actions logs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

from drive_sort_prefolders import classify

REPOS = ("BackstageTalks/tbt-data", "BackstageTalks/tbt")
FIELDS = (
    "umiestnenie", "stav", "kategoria", "nazov_alebo_cesta", "format",
    "velkost_bajty", "vhodnost", "audit_CDB", "kontrolny_otlacok", "odkaz",
)
SOURCE_EXT = (".csv", ".tsv", ".json", ".jsonl", ".parquet", ".xlsx", ".xls", ".zip",
              ".gz", ".7z", ".sqlite", ".db", ".feather", ".arrow", ".xml")
SKIP_CATEGORIES = {"09_KOD_A_DOKUMENTACIA", "11_ZALOHY"}


def git_json(endpoint: str) -> dict:
    # No shell, no remote code execution; GH_TOKEN is supplied by the workflow.
    p = subprocess.run(["gh", "api", endpoint], check=True, capture_output=True, text=True)
    return json.loads(p.stdout)


def repo_inventory(repo: str, fetch=git_json) -> tuple[list[dict], str]:
    if repo not in REPOS:
        raise ValueError("Unapproved repository")
    head = fetch("repos/" + repo + "/branches/main")
    commit = head["commit"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid repository revision")
    result = fetch("repos/" + repo + "/git/trees/" + commit + "?recursive=1")
    if result.get("truncated") is not False or not isinstance(result.get("tree"), list):
        raise ValueError("Incomplete GitHub tree; refusing partial source audit")
    output = []
    for entry in result["tree"]:
        if entry.get("type") != "blob":
            continue
        path = entry["path"]
        digest = entry["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", digest):
            raise ValueError("Invalid Git blob identity")
        output.append({
            "id": "git:" + repo + ":" + path,
            "source": repo,
            "name": path,
            "size": entry.get("size"),
            "fingerprint": digest,
            "link": "https://github.com/" + repo + "/blob/" + commit + "/" + quote(path, safe="/"),
            "mime": Path(path).suffix.lower(),
            "status": "REPO_NOT_FIELD_MATCHED",
        })
    if not output:
        raise ValueError("Empty Git tree")
    return output, commit


def release_inventory(repo: str, fetch=git_json, max_pages: int = 25) -> tuple[list[dict], bool]:
    """Inventory GitHub Release assets as METADATA ONLY, never download raw data."""
    if repo != "BackstageTalks/tbt-data":
        raise ValueError("Unexpected release repository")
    output = []
    seen = set()
    complete = False
    for page_no in range(1, max_pages + 1):
        page = fetch(f"repos/{repo}/releases?per_page=100&page={page_no}")
        if not isinstance(page, list):
            raise ValueError("Invalid release inventory response")
        for release in page:
            tag = release.get("tag_name", "")
            # Exclude our own changing reports/checkpoints to avoid recursive deltas.
            if tag.startswith(("blinq-drive-cdb-audit-", "blinq-drive-cdb-checkpoint-",
                               "blinq-drive-source-inventory-")) or tag == "blinq-drive-cdb-audit-cache-v1":
                continue
            for asset in release.get("assets", []):
                aid = asset.get("id")
                if not isinstance(aid, int) or aid <= 0 or aid in seen:
                    raise ValueError("Invalid or duplicate Release asset ID")
                seen.add(aid)
                if len(seen) > 25000:
                    raise ValueError("Release asset inventory safety limit reached")
                name = str(asset.get("name") or "")
                if not name:
                    raise ValueError("Unnamed Release asset")
                value = "|".join(str(asset.get(k) or "") for k in
                                 ("digest", "size", "updated_at"))
                output.append({
                    "id": f"release:{repo}:{aid}", "source": repo + " Releases",
                    "name": tag + "/" + name, "size": asset.get("size"),
                    "fingerprint": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                    "link": "https://github.com/" + repo + "/releases/tag/" + quote(tag, safe=""),
                    "mime": Path(name).suffix.lower(),
                    "status": "RELEASE_METADATA_ONLY_NOT_BYTES_VERIFIED",
                })
        if len(page) < 100:
            complete = True
            break
    return output, complete

def drive_inventory(data: list, files: list) -> list[dict]:
    if not isinstance(data, list) or not isinstance(files, list):
        raise ValueError("Invalid Drive report")
    statuses = {record["id"]: record.get("status", "UNKNOWN") for record in files}
    if len(statuses) != len(files) or {r["id"] for r in data} != set(statuses):
        raise ValueError("Drive report and source audit are inconsistent")
    result = []
    for row in data:
        if row.get("mimeType") == "application/vnd.google-apps.shortcut":
            # Categorization shortcuts are pointers, not independent data.
            continue
        version = (row.get("sha256Checksum") or row.get("md5Checksum") or
                   "|".join(str(row.get(x, "")) for x in ("version", "size", "modifiedTime")))
        result.append({
            "id": "drive:" + row["id"],
            "source": "Google Drive",
            "name": row["name"],
            "size": row.get("size"),
            "fingerprint": hashlib.sha256(version.encode("utf-8")).hexdigest(),
            "link": "https://drive.google.com/open?id=" + quote(row["id"], safe=""),
            "mime": row.get("mimeType", ""),
            "status": statuses[row["id"]],
        })
    return result


def suitability(item: dict, category: str) -> str:
    name = item["name"].lower()
    if category in SKIP_CATEGORIES:
        return "POMOCNY_SUBOR_NIE_PRIAMY_DATOVY_IMPORT"
    if category == "12_NA_KONTROLU":
        return "NEJASNY_ZDROJ_MANUALNA_KONTROLA"
    if category == "10_POVODNE_ZDROJE_ARCHIVY":
        return "ARCHIV_VYZADUJE_OVERENIE_OBSAHU"
    if name.endswith(SOURCE_EXT):
        return "POTENCIALNY_ZDROJ_OVERIT_IDENTITU_A_POVOD"
    return "METADATA_ONLY_VYZADUJE_ANALYZU"


def safe_cell(value) -> str:
    value = "" if value is None else str(value)
    # Quote untrusted Drive filenames so Excel/Sheets cannot execute CSV formulas.
    trimmed = value.lstrip(" \t\r\n\ufeff")
    return "'" + value if trimmed.startswith(("=", "+", "-", "@")) else value


def generate(drive: list[dict], repositories: dict[str, list[dict]], commits: dict[str, str],
             comparison: dict, previous: dict | None, out: Path,
             releases: list[dict] | None = None, releases_complete: bool = True) -> dict:
    if not isinstance(comparison, dict) or comparison.get("cdb_writes") != 0:
        raise ValueError("Unverified read-only CDB report")
    before = {}
    if previous is not None:
        if previous.get("schema") != 1 or not isinstance(previous.get("entries"), dict):
            raise ValueError("Invalid previous source baseline")
        before = previous["entries"]
    sources = drive + [item for repo in REPOS for item in repositories[repo]] + (releases or [])
    ids = [record["id"] for record in sources]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate source identities")
    rows = []
    current = {}
    counts = Counter()
    for item in sorted(sources, key=lambda x: x["id"]):
        category = classify(Path(item["name"]).name, tuple(Path(item["name"]).parts[:-1]))
        key = item["id"]
        fingerprint = item["fingerprint"]
        old = before.get(key)
        state = ("BASELINE" if previous is None else
                 "NOVY" if old is None else
                 "ZMENENY" if old["fingerprint"] != fingerprint else "BEZ_ZMENY")
        relevance = suitability(item, category)
        counts[state] += 1
        current[key] = {"fingerprint": fingerprint, "name": item["name"],
                        "source": item["source"], "category": category}
        rows.append(dict(zip(FIELDS, (
            item["source"], state, category, item["name"], item["mime"],
            item["size"], relevance, item["status"], fingerprint, item["link"],
        ))))
    if previous is not None:
        for key in sorted(set(before) - set(current)):
            old = before[key]
            counts["UZ_NEDOSTUPNY"] += 1
            rows.append(dict(zip(FIELDS, (
                old["source"], "UZ_NEDOSTUPNY", old["category"], old["name"], "",
                "", "OVERIT_ODSTRANENIE_ALEBO_PRESUN", "NEOVERENE", "", "",
            ))))
    out.mkdir(parents=True, exist_ok=True)
    for name, subset in (
        ("audit-zdrojov.csv", rows),
        ("nove-a-zmenene-zdroje.csv", [x for x in rows if x["stav"] in
                                      ("NOVY", "ZMENENY", "UZ_NEDOSTUPNY")]),
    ):
        with (out / name).open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            for record in subset:
                writer.writerow({key: safe_cell(value) for key, value in record.items()})
    baseline = {"schema": 1, "entries": current, "repository_commits": commits}
    (out / "source-baseline.json").write_text(
        json.dumps(baseline, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "schema": 1, "status": "READ_ONLY_INVENTORY",
        "scope": {"drive_root": "configured private Drive audit folder",
                  "repositories": list(REPOS), "git_branches": "main",
                  "github_release_assets_in_scope": bool(releases is not None),
                  "github_release_inventory_complete": releases_complete},
        "baseline_previously_available": previous is not None,
        "source_counts": dict(sorted(counts.items())),
        "drive_originals": len(drive), "github_release_assets": len(releases or []),
        "git_files": {repo: len(repositories[repo]) for repo in REPOS},
        "canonical_rows": comparison.get("canonical_rows"),
        "cdb_candidate_missing_fields_all_drive": (
            comparison.get("comparison") or {}).get("candidate_missing_fields"),
        "note": ("File-level suitability is a conservative classification, NOT evidence "
                 "of unique rows, licensed use, identity matching, missing CDB cells, "
                 "or readiness to import. All candidate values remain read-only."),
        "cdb_writes": 0, "originals_moved": 0,
    }
    (out / "audit-zhrnutie.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256((out / "source-baseline.json").read_bytes()).hexdigest()
    (out / "source-baseline.sha256").write_text(
        digest + "  source-baseline.json\n", encoding="ascii")
    # stdout only counts: no private paths, names, IDs or player/match data.
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--drive-inventory", type=Path, required=True)
    p.add_argument("--drive-files", type=Path, required=True)
    p.add_argument("--cdb-report", type=Path, required=True)
    p.add_argument("--previous", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    previous = json.loads(args.previous.read_text()) if args.previous else None
    repositories, commits = {}, {}
    for repo in REPOS:
        repositories[repo], commits[repo] = repo_inventory(repo)
    releases, releases_complete = release_inventory("BackstageTalks/tbt-data")
    summary = generate(
        drive_inventory(json.loads(args.drive_inventory.read_text()),
                        json.loads(args.drive_files.read_text())),
        repositories, commits, json.loads(args.cdb_report.read_text()),
        previous, args.out, releases=releases, releases_complete=releases_complete)
    print(json.dumps({k: summary[k] for k in (
        "status", "baseline_previously_available", "source_counts",
        "drive_originals", "git_files", "github_release_assets", "cdb_writes")}, sort_keys=True))


if __name__ == "__main__":
    main()
