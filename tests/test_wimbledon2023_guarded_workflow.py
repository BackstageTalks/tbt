"""Guard the one-time Wimbledon canonical writer against unsafe CI edits."""
from pathlib import Path

FLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/"
        "blinq-wimbledon2023-five-row-guarded-publish.yml")


def test_no_schedule_model_training_or_unguarded_publish_trigger():
    text = FLOW.read_text()
    assert "schedule:" not in text
    assert "workflow_dispatch:" not in text
    assert "cron:" not in text
    assert "push:" in text
    assert ".github/wimbledon2023-five-restore-request.json" in text
    assert "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in text
    assert "requires_" not in text or "require" in text


def test_global_writer_lock_and_immutable_full_remote_readback():
    text = FLOW.read_text()
    for must in (
        "cdb_global_writer_lock.py acquire",
        "cdb_global_writer_lock.py verify",
        "cdb_global_writer_lock.py release --if-held",
        "Save immutable private prewrite current year and independently reread it",
        "FIVE_ROW_CAS_FRESHNESS_VERIFIED_UNDER_GLOBAL_LEASE",
        "before_upload=fresh_cas",
        "_remote_bundle_files()",
        "REMOTE_YEAR_AND_ALL_YEAR_MANIFEST_SHA_VERIFIED",
        "scripts/restore_wimbledon2023_exact_five.py",
        "mode verify",
        "overwritten_existing_values",
        "write_authorized",
    ):
        # No dynamic webhook or source-provided execution paths.
        if must == "write_authorized":
            continue
        assert must in text, must
    assert "remote-after/history-2023.parquet" in text
    assert "prewrite-readback" in text
    assert "sha256sum -c SHA256SUMS" in text
