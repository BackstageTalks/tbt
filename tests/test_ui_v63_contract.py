import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    return json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))


def test_v63_banner_rows_are_restored_and_manageable():
    cfg = _cfg()
    assert cfg["ui_revision"] == "6.3.0"
    assert cfg["content_rows"]["content_top"]["enabled"] is True
    assert cfg["content_rows"]["content_mid"]["enabled"] is True
    assert cfg["content_rows"]["content_bottom"]["enabled"] is True
    assert cfg["content_rows"]["content_top"]["preset"] in {"1+1+1+1", "2+2", "2+1+1", "1+1+2", "4"}
    assert [cfg["elements"][f"CONTENT_TOP_{i}"]["content"]["route"] for i in range(1, 5)] == [
        "prime", "top_daily", "value", "results"
    ]
    assert all(cfg["elements"][f"CONTENT_TOP_{i}"]["content"]["type"] == "promo" for i in range(1, 5))


def test_membership_catalogue_is_link_driven_and_legend_is_switchable():
    cfg = _cfg()
    plans = cfg["plans"]
    for plan_id in ("rookie", "pro", "elite", "goat", "legend"):
        plan = plans[plan_id]
        assert "url" in plan
        assert "description" in plan
        assert "cta_label" in plan
        assert "avatar" in plan
        assert "order" in plan
        assert "price" not in plan
        assert "currency" not in plan
        assert "billing" not in plan
    assert plans["legend"]["enabled"] is False
    assert cfg["assets"]["admin_avatar_plan"] == "goat"


def test_dashboard_has_clock_results_and_see_all_cards():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="headerDate"' in html
    assert 'id="headerTime"' in html
    assert 'id="resultsPreviewPanel"' in html
    for token in (
        'id="primeSeeAllCard"',
        'id="topDailySeeAllCardCount"',
        'id="valueSeeAllCardCount"',
        'id="aceSeeAllCardCount"',
        'id="sgSeeAllCardCount"',
        'id="doublesSeeAllCardCount"',
        'id="resultsSeeAllCardCount"',
    ):
        assert token in html
