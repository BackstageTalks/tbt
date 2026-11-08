import pytest
from scripts.verify_audit_only_diff import assert_audit_only


def test_documentation_can_skip_deployment():
    assert_audit_only(['docs/runbook.md', 'README.md'])


@pytest.mark.parametrize('path', ['api/tbt/services/market_selection.py', 'web/ui-config.json', '.github/workflows/data.yml'])
def test_runtime_change_cannot_hide_behind_audit_marker(path):
    with pytest.raises(ValueError, match='cannot suppress'):
        assert_audit_only(['docs/runbook.md', path])
