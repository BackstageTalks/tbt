"""Guard training before any release/provider access until full immutable backup exists."""
import subprocess
import sys
from pathlib import Path


def test_candidate_training_fails_before_network_without_full_backup():
    script = Path(__file__).resolve().parents[1] / "scripts" / "pipeline.py"
    run = subprocess.run(
        [sys.executable, str(script), "train", "--max-requests", "1"],
        capture_output=True, text=True, timeout=45,
    )
    assert run.returncode == 2
    assert "Candidate training blocked: missing per-run immutable" in run.stderr
    assert "full-input backup" in run.stderr
