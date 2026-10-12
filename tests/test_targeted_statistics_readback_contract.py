"""Contract: all targeted sports-API CDB writes require remote read-back.

No provider calls or canonical writes in these tests.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_operator_and_hourly_statistics_both_verify_remote_persisted_values():
    workflow = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")
    marker = "Independently verify every targeted CDB statistics publication"
    assert workflow.count(marker) == 1
    verify = workflow.split(marker, 1)[1].split("\n      - name:", 1)[0]
    condition = next(line.strip() for line in verify.splitlines()
                     if line.lstrip().startswith("if:"))
    assert "success()" in condition
    assert "env.MODE == 'statistics'" in condition
    assert "inputs.hourly_autofill" in condition
    assert "env.BLINQ_TARGETED_STATISTICS == 'true'" in condition
    assert re.search(r"run: python scripts/verify_targeted_statistics\.py\s+--data-repository", verify)


def test_targeted_statistics_request_sets_trigger_and_proof_inputs():
    workflow = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")
    downloader = (ROOT / "scripts/download_tennis_history.py").read_text(encoding="utf-8")
    assert 'echo "BLINQ_TARGETED_STATISTICS=$targeted" >> "$GITHUB_ENV"' in workflow
    assert 'targeted_statistics' in workflow
    assert 'statistics_expected.json' in downloader
    assert 'added_fields' in downloader


def test_independent_verifier_checks_all_requested_fields_and_remote_hashes():
    verifier = (ROOT / "scripts/verify_targeted_statistics.py").read_text(encoding="utf-8")
    assert 'gh' in verifier and 'release' in verifier and 'download' in verifier
    assert "if seen != set(expected):" in verifier
    assert "count != collection.get('statistics_data_value', {}).get('new_statistic_values', 0)" in verifier
    assert "digest != manifest[name]['sha256']" in verifier
