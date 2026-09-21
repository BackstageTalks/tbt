"""Run the complete zero-Tennis-API production data preflight."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _bootstrap import ROOT


def run(args: list[str]) -> None:
    print("$ " + " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    py = sys.executable
    run([py, "scripts/download_production_preflight_inputs.py"])
    profiles = ROOT / ".cache/tbt/player-assets/player_profiles.json"
    cmd = [py, "scripts/build_player_master.py", "--history-dir", ".cache/tbt/history"]
    if profiles.is_file() and profiles.stat().st_size:
        cmd += ["--profiles", str(profiles.relative_to(ROOT))]
    cmd += [
        "--out", ".cache/tbt/production/player_master.json",
        "--csv", ".cache/tbt/production/player_master.csv",
        "--report", ".cache/tbt/production/player_master_report.json",
    ]
    run(cmd)
    run([py, "scripts/build_tournament_venue_master.py",
         "--history-dir", ".cache/tbt/history",
         "--tournaments-out", ".cache/tbt/production/tournament_master.json",
         "--tournaments-csv", ".cache/tbt/production/tournament_master.csv",
         "--venues-out", ".cache/tbt/production/venue_master.json",
         "--venues-csv", ".cache/tbt/production/venue_master.csv",
         "--report", ".cache/tbt/production/tournament_venue_report.json"])
    run([py, "scripts/build_production_training_table.py",
         "--history-dir", ".cache/tbt/history",
         "--out", ".cache/tbt/production/training_table.parquet",
         "--report", ".cache/tbt/production/training_table_report.json"])
    run([py, "scripts/audit_training_leakage.py",
         "--history-dir", ".cache/tbt/history",
         "--report", ".cache/tbt/production/leakage_audit_report.json"])
    run([py, "scripts/audit_statistics_inventory.py",
         "--history-dir", ".cache/tbt/history",
         "--out", ".cache/tbt/production/statistics_inventory_report.json"])
    run([py, "scripts/build_production_readiness_report.py",
         "--player-report", ".cache/tbt/production/player_master_report.json",
         "--tournament-report", ".cache/tbt/production/tournament_venue_report.json",
         "--training-report", ".cache/tbt/production/training_table_report.json",
         "--leakage-report", ".cache/tbt/production/leakage_audit_report.json",
         "--statistics-report", ".cache/tbt/production/statistics_inventory_report.json",
         "--out", ".cache/tbt/production/readiness_report.json",
         "--markdown", ".cache/tbt/production/readiness_report.md"])


if __name__ == "__main__":
    main()
