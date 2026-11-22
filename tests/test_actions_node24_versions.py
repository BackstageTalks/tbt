"""Require Node 24-ready action majors in priority workflows.

Commit SHA pins were verified against official actions/{checkout,setup-python}
v5/v6 Git refs on 2026-11-22. This does not imply every repository workflow
was migrated.
"""
from pathlib import Path

CHECKOUT_V5 = "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"
PYTHON_V6 = "ece7cb06caefa5fff74198d8649806c4678c61a1"
WORKFLOWS = (
    "ci.yml", "data.yml", "admin-training-worker.yml",
    "match-status.yml", "propline-evening-odds.yml",
    "telegram-web-historical-parity.yml", "cdb-drive-inbox.yml",
)


def test_priority_workflow_actions_use_pinned_new_majors():
    for name in WORKFLOWS:
        text = (Path(".github/workflows") / name).read_text(encoding="utf-8")
        assert "actions/checkout@" + CHECKOUT_V5 in text, name
        assert "actions/checkout@v4" not in text, name
        assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" not in text, name
        assert "actions/setup-python@v5" not in text, name
        assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" not in text, name
        if "setup-python@" in text:
            assert "actions/setup-python@" + PYTHON_V6 in text, name
