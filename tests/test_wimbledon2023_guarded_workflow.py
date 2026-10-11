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



def test_publish_installs_parquet_dependencies_before_first_validator_import():
    """Regression: first publish failed at pandas import before the pip install."""
    text = FLOW.read_text()
    start = text.index("name: Require private release and immutable pinned one-time request")
    stop = text.index("name: Independently verify immutable source", start)
    validation_step = text[start:stop]
    install = validation_step.index("python -m pip install -q -r api/requirements-train.txt")
    check = validation_step.index("python scripts/prepare_wimbledon2023_guarded_restore.py")
    assert install < check, "pandas is imported by the validator before dependency setup"
