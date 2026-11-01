"""Reuse the newest independently verified prior hourly evidence from Actions.

Does not contact Tennis API or CDB; does not require a paid provider key.
Only a successful completed main-branch run with a matching private report can
seed the next run. If absent, preserve the original deterministic queue.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import subprocess
import sys
import tempfile

from adaptive_verified_prior import validated_prior
from tbt.services.statistics_enrichment import STATISTICS_SCHEMA_VERSION


def _gh(*args):
    completed = subprocess.run(["gh", *args], check=False, text=True,
                               capture_output=True, timeout=25)
    if completed.returncode:
        raise RuntimeError("GitHub evidence is unavailable")
    return completed.stdout


def locate_prior(repo, *, now=None):
    now = now or datetime.now(timezone.utc)
    if not repo or "/" not in repo:
        return None
    try:
        rows = json.loads(_gh("run", "list", "--repo", repo,
                              "--workflow", "data.yml", "--branch", "main",
                              "--status", "success", "--limit", "16",
                              "--json", "databaseId,createdAt"))
    except (RuntimeError, ValueError, subprocess.TimeoutExpired):
        return None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("databaseId"), int):
            continue
        run_id = str(row["databaseId"])
        try:
            created = datetime.fromisoformat(row["createdAt"].replace("Z", "+00:00"))
            if created.tzinfo is None or not timedelta(0) <= now - created <= timedelta(days=7):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        with tempfile.TemporaryDirectory() as folder:
            try:
                _gh("run", "download", run_id, "--repo", repo, "--name",
                    f"blinq-statistics-{run_id}", "--dir", folder)
                evidence_path = Path(folder) / "adaptive_cdb_evidence.json"
                data = json.loads(evidence_path.read_text(encoding="utf-8"))
                validated_prior(data, parser_version=STATISTICS_SCHEMA_VERSION, now=now)
            except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
                continue
            return data
    return None


def main():
    repo = os.getenv("GITHUB_REPOSITORY", "")
    data = locate_prior(repo)
    if data is None:
        print("No compatible, independently verified prior: deterministic baseline retained.")
        return
    directory = Path(".cache/tbt/adaptive-prior")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "verified-prior.json"
    target.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    env_path = os.getenv("GITHUB_ENV", "")
    if env_path:
        with open(env_path, "a", encoding="utf-8") as out:
            out.write(f"BLINQ_ADAPTIVE_VERIFIED_PRIOR_FILE={target.resolve()}\n")
    print("Validated prior adaptive CDB evidence; no provider calls.")


if __name__ == "__main__":
    main()
