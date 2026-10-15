"""Guard the production refresh budget against regression to the 30-minute outage window."""

import ast
from pathlib import Path


def test_production_refresh_budget_covers_heavy_recent_history_before_upcoming():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "pipeline.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    budgets = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "LocalRequestBudget"
    ]
    assert len(budgets) == 1
    durations = [
        node.value.value for node in budgets[0].keywords
        if node.arg == "duration_seconds"
        and isinstance(node.value, ast.Constant)
    ]
    # On 2026-10-15 the old 1800-second budget expired after canonical history
    # processing, before the first upcoming discovery request. Keep at least
    # two hours, but always below the 210-minute GitHub Actions job timeout.
    assert durations == [7200]
    assert durations[0] < 210 * 60


def test_provider_request_caps_remain_independent_of_elapsed_time():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "pipeline.py").read_text(encoding="utf-8")
    assert "provider.request_limit = allowance" in source
    assert 'purpose="refresh"' in source
    assert "combined_reservation" in (
        Path(__file__).resolve().parents[1] / "api" / "tbt" / "providers" / "rapidapi.py"
    ).read_text(encoding="utf-8")
