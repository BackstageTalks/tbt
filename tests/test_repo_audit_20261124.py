"""Offline expected failures from the November 2026 repository audit."""

import pytest

from test_market_selection import row
from tbt.services.market_selection import (
    _exclusive_section_assignment,
    select_market_sections,
)


def test_value_cap_leaves_independently_eligible_pick_available_to_top():
    candidate = row("qualified-for-both", .80, 1.90, 2.00, depth=.95, surface1=20, surface2=20)
    positive = select_market_sections([candidate], value_limit=1)
    assert [item["event_id"] for item in positive["value_picks"]] == ["qualified-for-both"]
    assert positive["top_daily_picks"] == []
    capped = select_market_sections([candidate], value_limit=0)
    assert [item["event_id"] for item in capped["top_daily_picks"]] == ["qualified-for-both"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="AUD-02: incomplete identity produces a truthy key")
def test_section_assignment_rejects_rows_without_event_identity():
    selected, _, _ = _exclusive_section_assignment({
        "top_daily": [{"market": "match_winner", "selection_id": "p1", "betting_day": "2026-09-07"}],
    })
    assert selected["top_daily"] == []



@pytest.mark.xfail(strict=True, raises=AssertionError, reason="AUD-03: teaser uses elapsed hours across DST")
@pytest.mark.parametrize(
    ("instant", "expected_day"),
    [
        ("2026-03-29T04:30:00Z", "2026-03-29"),
        ("2026-10-25T04:30:00Z", "2026-10-24"),
    ],
)
def test_teaser_betting_day_uses_bratislava_wall_clock(instant, expected_day):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the frontend regression")
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    # Evaluate the production expression and its local helper with a frozen clock.
    helper_start = source.index("  function bratislavaBettingDayKey(")
    start = source.rfind("  const bratislavaBettingDayFormatter=", 0, helper_start)
    start = helper_start if start < 0 else start
    end = source.index("\n  }", source.index("  function bratislavaBettingDayKey(", start)) + len("\n  }")
    helper = source[start:end]
    teaser = source.split("  function previewStableRandomSlots(", 1)[1].split("\n  }", 1)[0]
    line = next(line.strip() for line in teaser.splitlines() if line.strip().startswith("const dateKey="))
    add_start = source.index("  function dateOnlyAddDays(")
    add_end = source.index("\n  }", add_start) + len("\n  }")
    code = f"Date.now = () => Date.parse(process.argv[1]);\n{source[add_start:add_end]}\n{helper}\n{line}\nconsole.log(dateKey);"
    actual = subprocess.run(
        [node, "-e", code, instant], check=True, capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    assert actual == expected_day
