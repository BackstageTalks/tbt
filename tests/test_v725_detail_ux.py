from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "final-polish-725.css").read_text(encoding="utf-8")


def test_footer_exposes_freshness_and_live_state():
    assert "liveAgeMin<=3" in APP
    assert "feedAgeMin>90" in APP
    assert "footer.live_ok" in APP
    assert "hubDataDepthLabel" in APP
    assert ".site-footer .system-status" in CSS


def test_market_specific_details_do_not_mix_projection_types():
    assert "sgProjectionDetailHtml" in APP
    assert "aceProjectionDetailHtml" in APP
    assert "winnerWhyBlinqHtml" in APP
    assert "MODEL 2. SETU · samostatný podporný signál" in APP


def test_match_detail_is_presented_as_side_drawer_and_table_header_stays_sticky():
    assert "blinqDrawerIn" in CSS
    assert ".match-dialog" in CSS and "inset:0 0 0 auto" in CSS
    assert ".daily-hub-table thead" in CSS and "position:sticky" in CSS
