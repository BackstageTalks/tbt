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
    # Production secrets are usable only on main: manual dispatch or pinned
    # one-shot push. Pull requests must never reach guarded-import.
    assert "github.ref == 'refs/heads/main' &&" in IMPORT
    assert "(github.event_name == 'workflow_dispatch' ||" in IMPORT
    assert "(github.event_name == 'push' &&" in IMPORT
    assert "startsWith(github.event.head_commit.message, 'chore(cdb): authorized one-shot Drive import 2026-10-20')" in IMPORT
    assert "Enforce explicit one-shot source authorization (push only)" in IMPORT
    assert 'data.get("wta_current_match_statistics_import_allowed") is not False' in IMPORT
    assert "api_budget_requests_for_this_import" in IMPORT
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


def test_entire_blinq_data_root_is_recursive_and_progress_is_private():
    assert "INBOX_FOLDER_ID: 1jzdzztz8cXquO8VDswqE19PHupQau-xM" in IMPORT
    assert "scripts/cdb_inbox_drive.py --folder-id" in IMPORT
    assert "--state-file work/private-state/current.json" in IMPORT
    assert "--next-state work/private-state/next.json" in IMPORT
    assert "audit/cdb-inbox-progress.json.gz" in IMPORT
    assert "CDB_INBOX_PROGRESS_PRIVATE_READBACK_VERIFIED" in IMPORT
    assert "tests/test_cdb_inbox_drive.py" in IMPORT

def test_cdb_writer_busy_is_checked_after_preparing_sources_and_deferred():
    gate = "Observe CDB writer only AFTER normalized data preparation"
    assert gate in IMPORT
    assert "await-cdb-writer-idle:" not in IMPORT
    assert IMPORT.index("Restore private Drive-wide import progress") < IMPORT.index(gate)
    assert IMPORT.index("scripts/cdb_inbox_drive.py --folder-id") < IMPORT.index(gate)
    assert IMPORT.index(gate) < IMPORT.index("scripts/cdb_global_writer_lock.py acquire")
    assert "python scripts/cdb_inbox_pending_batch.py persist" in IMPORT
    assert "python scripts/cdb_inbox_pending_batch.py restore" in IMPORT
    assert "steps.writer_gate.outputs.ready == 'false'" in IMPORT
    assert "steps.writer.outputs.locked == 'true'" in IMPORT

def test_protected_training_completion_triggers_safe_import_retry():
    hook = (ROOT / ".github/workflows/cdb-drive-inbox-after-training.yml").read_text()
    assert "workflow_run:" in hook
    assert "BlinQ protected frozen-CDB candidate training" in hook
    assert "completed" in hook
    assert "head_branch == 'main'" in hook
    assert "head_repository.full_name == 'BackstageTalks/tbt'" in hook
    assert "actions: write" in hook
    assert "gh workflow run cdb-drive-inbox.yml" in hook
    assert "git/refs/tags" not in hook
    assert "release delete" not in hook
    assert "\\n  schedule:" not in hook
    assert "Tennis data and predictions" in hook
    assert "blinq-cdb-inbox-pending-v1" in hook
    assert "PRIVATE_CDB_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}" in hook
    assert "CDB_INBOX_NO_PREPARED_BATCH_AFTER_MAIN_WRITER" in hook
    assert "CDB_INBOX_ALREADY_RUNNING_NO_DUPLICATE_RETRY" in hook
    assert 'gh api -X GET' in hook
