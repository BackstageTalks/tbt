#!/usr/bin/env python3
"""Classify BlinQ Drive source files via non-destructive, idempotent shortcuts.

No source moves, downloads, CDB imports, source mutations or model operations.
Default is plan-only. In apply mode a distinct writable service account is
required. Full source IDs remain in a PRIVATE report, never Actions stdout.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import time

ROOT = "17UChTTWLpC-7tZIbvTXKA4_2eqooV44A"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
DESTINATIONS = {
    "01_ZAPASY_A_VYSLEDKY": "1_N38EaOQ06-a32JyCniRZDQCVMKAs0V3",
    "02_KURZY_A_ODDS": "1L2hXjcTyuYXGfSPbUBfvR_cQ-WCJPdPN",
    "03_POINT_BY_POINT": "1VyDJyI1FLVu3PVkYwLM08fEsxEX0Lxv9",
    "04_SERVIS_RETURN_STATISTIKY": "1t8YRWoatOHYTGa7e1ifHZ5dUgrIkaIse",
    "05_REBRICKY_A_ELO": "1HV18SWO51kHIWLwE3sNsmGbeaSQgCNBt",
    "06_HRACI_A_H2H": "1_JFB7dnn7iStNWEse-_kK5FZb9FMqtj7",
    "07_TURNAJE": "1aSc4M9wsd1Datn4L17gZl5pZHU95E7jl",
    "08_MATCH_CHARTING_FEATURES": "1BWdw3v11glB3AUCAjoL2v6QK0_B4DSss",
    "09_KOD_A_DOKUMENTACIA": "1CWzDk-vYCX3ET_F09bGpDNOi6nNP7KiS",
    "10_POVODNE_ZDROJE_ARCHIVY": "1nI_2fa3Jz5v90BrdpTmB9dJf_bqb_Y19",
    "11_ZALOHY": "1QroFvfmldbnbqjWi9usUOzXTewWDj-wj",
    "12_NA_KONTROLU": "1o2fVDt0lMgYXDL2vZzqrfFVbaB31Z_7f",
}

def tokens(name: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip() + " "

def has(text: str, *terms: str) -> bool:
    return any(" " + term + " " in text for term in terms)

def classify(name: str, ancestors: tuple[str, ...]) -> str:
    """Conservative metadata-only selection, never infer CDB importability."""
    n = tokens(name)
    parent = tokens(" ".join(ancestors))
    if has(n, "backup", "backups", "snapshot") or has(parent, "backup", "backups"):
        return "11_ZALOHY"
    if name.lower().endswith((".py", ".ipynb", ".md", ".rst", ".yml", ".yaml", ".js", ".ts", ".pdf")) or has(n, "readme", "documentation", "license"):
        return "09_KOD_A_DOKUMENTACIA"
    if has(n, "charting", "tennisvisuals", "shot", "rally") or has(parent, "charting"):
        return "08_MATCH_CHARTING_FEATURES"
    if has(n, "pbp", "point by point", "pointbypoint", "points") or has(parent, "point by point", "pbp"):
        return "03_POINT_BY_POINT"
    if has(n, "odds", "odd", "betting", "market", "closing", "bookmaker", "betfair", "clv"):
        return "02_KURZY_A_ODDS"
    if has(n, "elo", "rank", "ranking", "rankings", "ratings", "rating"):
        return "05_REBRICKY_A_ELO"
    if has(n, "serve", "serving", "return", "returning", "ace", "aces", "double faults", "double fault", "df", "statistics", "stats"):
        return "04_SERVIS_RETURN_STATISTIKY"
    if has(n, "h2h", "players", "player", "profiles", "profile", "biography"):
        return "06_HRACI_A_H2H"
    if has(n, "tournament", "tournaments", "venue", "venues", "court speed"):
        return "07_TURNAJE"
    if has(n, "match", "matches", "results", "result", "score", "scores", "singles", "doubles"):
        return "01_ZAPASY_A_VYSLEDKY"
    if name.lower().endswith((".zip", ".7z", ".rar", ".tar", ".gz", ".sqlite", ".db")) or has(parent, "archive", "archives"):
        return "10_POVODNE_ZDROJE_ARCHIVY"
    if re.fullmatch(r"\d{4}\.xlsx?", name.casefold()) and (
        "atp mens tour" in parent or "wta womens tour" in parent
    ):
        return "01_ZAPASY_A_VYSLEDKY"
    return "12_NA_KONTROLU"

class DriveAPI:
    def __init__(self, session):
        self.session = session

    def request(self, method, endpoint, **kwargs):
        url = "https://www.googleapis.com/drive/v3/" + endpoint
        for attempt in range(4):
            r = self.session.request(method, url, timeout=45, **kwargs)
            if r.status_code not in (429, 500, 502, 503, 504):
                r.raise_for_status()
                return r.json()
            r.close()
            time.sleep(min(2 ** attempt, 8))
        raise RuntimeError("Drive service temporarily unavailable")

    def metadata(self, file_id):
        return self.request("GET", "files/" + file_id, params={
            "fields": "id,name,mimeType,parents,trashed,shortcutDetails(targetId)",
            "supportsAllDrives": "true",
        })

    def children(self, folder_id):
        token = None
        while True:
            params = {
                "q": "'" + folder_id + "' in parents and trashed = false",
                "fields": "nextPageToken,incompleteSearch,files(id,name,mimeType,parents,shortcutDetails(targetId))",
                "pageSize": 1000,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if token:
                params["pageToken"] = token
            page = self.request("GET", "files", params=params)
            if page.get("incompleteSearch"):
                raise ValueError("Incomplete Drive listing: refusing to classify")
            yield from page.get("files", [])
            token = page.get("nextPageToken")
            if not token:
                break

    def create_shortcut(self, source, destination):
        created = self.request("POST", "files", params={
            "fields": "id,name,mimeType,parents,shortcutDetails(targetId)",
            "supportsAllDrives": "true",
        }, json={
            "name": source["name"], "mimeType": SHORTCUT_MIME,
            "parents": [destination],
            "shortcutDetails": {"targetId": source["id"]},
        })
        checked = self.metadata(created["id"])
        if (checked.get("mimeType") != SHORTCUT_MIME
                or checked.get("shortcutDetails", {}).get("targetId") != source["id"]
                or checked.get("parents") != [destination]):
            raise ValueError("Shortcut read-back mismatch")
        return checked["id"]

def inventory(api, max_files: int, max_folders: int):
    excluded = set(DESTINATIONS.values())
    queue = [(ROOT, ())]; seen = set(); found = []
    while queue:
        folder, ancestry = queue.pop(0)
        if folder in seen:
            continue
        if len(seen) >= max_folders:
            raise ValueError("Folder traversal cap hit: refusing partial plan")
        seen.add(folder)
        children = sorted(api.children(folder), key=lambda f: f["id"])
        for f in children:
            if f["mimeType"] == FOLDER_MIME:
                if f["id"] not in excluded:
                    queue.append((f["id"], ancestry + (f["name"],)))
            elif f["mimeType"] != SHORTCUT_MIME:
                found.append((f, ancestry))
                if len(found) > max_files:
                    raise ValueError("Source inventory cap hit: refusing partial plan")
    return sorted(found, key=lambda record: record[0]["id"])

def run(api, *, apply: bool, max_files: int, max_folders: int, max_new: int):
    root = api.metadata(ROOT)
    if root.get("mimeType") != FOLDER_MIME or root.get("trashed"):
        raise ValueError("Drive source root mismatch")
    for title, fid in DESTINATIONS.items():
        meta = api.metadata(fid)
        if (meta.get("name") != title or meta.get("mimeType") != FOLDER_MIME
                or meta.get("trashed") or ROOT not in meta.get("parents", [])):
            raise ValueError("Predefined category identity mismatch")
    original = inventory(api, max_files, max_folders)
    existing = {}
    for title, folder in DESTINATIONS.items():
        for item in api.children(folder):
            if item.get("mimeType") == SHORTCUT_MIME:
                target = item.get("shortcutDetails", {}).get("targetId")
                if target:
                    existing.setdefault(target, title)
    plan = []
    counts = Counter()
    for item, ancestors in original:
        target = classify(item["name"], ancestors)
        status = "already_linked" if item["id"] in existing else "candidate"
        counts[target] += 1
        plan.append({"source_id": item["id"], "source_name": item["name"],
                     "source_folders": list(ancestors), "category": target, "status": status})
    pending = [record for record in plan if record["status"] == "candidate"]
    # Validate entire plan before any mutation. Cap NEW shortcuts per batch.
    selected = pending[:max_new]
    if apply:
        for record in selected:
            fid = api.create_shortcut({"id": record["source_id"], "name": record["source_name"]},
                                      DESTINATIONS[record["category"]])
            record["status"] = "created_verified"
            record["shortcut_id"] = fid
    report = {
        "schema": 1, "mode": "apply" if apply else "plan",
        "source_file_count": len(original), "category_counts": dict(sorted(counts.items())),
        "already_linked": sum(x["status"] == "already_linked" for x in plan),
        "new_shortcuts_verified": sum(x["status"] == "created_verified" for x in plan),
        "pending_unlinked": sum(x["status"] == "candidate" for x in plan),
        "source_originals_moved": 0, "cdb_writes": 0, "details": plan,
    }
    return report

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("plan", "apply"), default="plan")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--max-files", type=int, default=10000)
    p.add_argument("--max-folders", type=int, default=2000)
    p.add_argument("--max-new", type=int, default=300)
    args = p.parse_args()
    if not 1 <= args.max_files <= 50000 or not 1 <= args.max_folders <= 10000 or not 1 <= args.max_new <= 1000:
        raise SystemExit("Invalid bounded inventory/write limits")
    from google.oauth2.service_account import Credentials
    from google.auth.transport.requests import AuthorizedSession
    raw = os.environ["BLINQ_DRIVE_SORT_CREDENTIALS"]
    scope = "https://www.googleapis.com/auth/drive" if args.mode == "apply" else "https://www.googleapis.com/auth/drive.readonly"
    credentials = Credentials.from_service_account_info(json.loads(raw), scopes=[scope])
    api = DriveAPI(AuthorizedSession(credentials))
    report = run(api, apply=args.mode == "apply", max_files=args.max_files,
                 max_folders=args.max_folders, max_new=args.max_new)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
    # Never print Drive IDs, source names or raw paths into the PUBLIC Actions log.
    print(json.dumps({key: val for key, val in report.items() if key != "details"}, sort_keys=True))

if __name__ == "__main__":
    main()
