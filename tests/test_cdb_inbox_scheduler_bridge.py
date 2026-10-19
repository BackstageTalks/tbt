"""Guard reused external Drive scheduler and prevent a second GitHub cron."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / ".github/workflows/blinq-private-drive-cdb-audit-bridge.yml").read_text()
IMPORT = (ROOT / ".github/workflows/cdb-drive-inbox.yml").read_text()


def test_external_scheduler_not_github_schedule():
    assert "\n  schedule:" not in BRIDGE
    assert "\n  schedule:" not in IMPORT
    assert "cdb-inbox-cron-dispatch:" in BRIDGE
    assert "GH_TOKEN: ${{ github.token }}" in BRIDGE
    assert 'gh workflow run cdb-drive-inbox.yml -R "$GITHUB_REPOSITORY" --ref main' in BRIDGE


def test_duplicate_window_and_utc_slot_guard():
    assert 'hour" != "02" && "$hour" != "14"' in BRIDGE
    assert 'any(.created_at | startswith($slot))' in BRIDGE
    assert "INBOX_CRON_SLOT_ALREADY_DISPATCHED" in BRIDGE


def test_secrets_never_present_on_pr_and_writer_is_reused():
    assert "github.event_name == 'workflow_dispatch'" in BRIDGE
    assert "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'" in IMPORT
    assert 'python scripts/cdb_global_writer_lock.py acquire' in IMPORT
    assert 'python scripts/import_offline_linked_serve_return.py' in IMPORT
    assert 'store.upload_bundle(' in IMPORT
    assert 'verify_persisted(' in IMPORT
    assert 'if: always()' in IMPORT

def test_active_half_hour_match_status_scheduler_is_primary_trigger():
    workflow = (ROOT / ".github/workflows/match-status.yml").read_text()
    assert "Dispatch CDB Drive Inbox at UTC 02 and 14 from active external clock" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "10#$minute >= 30" in workflow
    assert "CDB_INBOX_ALREADY_DISPATCHED_IN_SLOT" in workflow
    assert 'gh workflow run cdb-drive-inbox.yml --repo "$GITHUB_REPOSITORY" --ref main' in workflow
    assert "\\n  schedule:" not in workflow
