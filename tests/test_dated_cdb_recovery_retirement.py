"""Only date-locked one-shot CDB workflow entrypoints are retired."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED = (
    "cdb-urgent-recover-20261104.yml",
    "cdb-urgent-recover-20261106.yml",
    "cdb-2026-four-native-id-repair.yml",
    "cdb-2026-four-identity-triage.yml",
)


def test_expired_cdb_mutating_workflows_are_no_longer_triggers():
    for name in RETIRED:
        assert not (ROOT / ".github/workflows" / name).exists(), name


def test_general_recovery_and_authoritative_writer_are_preserved():
    for name in (
        "scripts/cdb_global_writer_lock.py",
        "scripts/recover_cdb_stalled_release_20261106.py",
        "scripts/restore_cdb_2026_four_native_id.py",
        ".github/workflows/cdb-drive-inbox.yml",
        ".github/workflows/prediction-release-recovery.yml",
    ):
        assert (ROOT / name).exists(), name
