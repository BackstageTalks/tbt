"""Offline expected failures from the November 2026 repository audit."""

import pytest

from test_market_selection import row
from tbt.services.market_selection import (
    _exclusive_section_assignment,
)



def test_section_assignment_rejects_rows_without_event_identity():
    selected, _, _ = _exclusive_section_assignment({
        "top_daily": [{"market": "match_winner", "selection_id": "p1", "betting_day": "2026-09-07"}],
    })
    assert selected["top_daily"] == []



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


def test_telegram_matches_equivalent_numeric_ace_lines():
    from telegram_daily_results import match_result

    sent = {
        "event_id": "e1", "selection_id": "a", "section": "ace",
        "market": "aces", "market_line": 8, "projection_direction": "over",
    }
    archived = {
        **sent, "market_line": 8.0,
        "result": {"runtime_source": "match_status_snapshot", "correct": True},
    }
    assert match_result(sent, [archived]) == archived


def test_mobile_hero_image_exists():
    import json
    from pathlib import Path

    web = Path(__file__).resolve().parents[1] / "web"
    config = json.loads((web / "config" / "banners.json").read_text(encoding="utf-8"))
    banners = config["main_banner"]["slides"]
    local_images = [banner["mobile_image_url"] for banner in banners
                    if banner.get("mobile_image_url", "").startswith("/assets/")]
    assert all((web / url.lstrip("/")).is_file() for url in local_images)


def test_shadow_rejects_extra_rows_outside_the_prepared_slate():
    from datetime import datetime, timezone
    from tbt.services.offer_shadow import build_offer_shadow

    day = "2026-11-24"
    prediction = row("prepared", .80, 1.90, 2.00)
    prediction["scheduled_at"] = day + "T10:00:00Z"
    prediction["betting"]["betting_day"] = day
    capture = build_offer_shadow(
        [prediction], observed_at=datetime(2026, 11, 24, 5, tzinfo=timezone.utc),
        public_offer_day=day, extra_variants={
            "aces_all_levels": [{"event_id": "outside-slate", "section": "most_aces"}],
        },
    )
    assert capture["variants"]["aces_all_levels"] == []
