from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_footer_is_minimal_with_live_worker_heartbeat_status():
    assert "hubDataDepthLabel" in APP
    assert "renderFooterConfig" not in APP
    assert "footer.live_ok" not in APP
    assert ".site-footer-minimal" in CSS
    assert 'id="footerSystemStatus"' in INDEX
    assert "Všetky systémy funkčné" in INDEX
    assert "Aktualizácia modelu: —" in INDEX
    assert "renderSystemFooterStatus" in APP


def test_market_specific_details_do_not_mix_projection_types():
    assert "sgProjectionDetailHtml" in APP
    assert "aceProjectionDetailHtml" in APP
    assert "winnerWhyBlinqHtml" in APP
    assert "MODEL 2. SETU · samostatný podporný signál" in APP


def test_match_detail_is_presented_as_side_drawer_and_table_header_stays_sticky():
    assert "blinqDrawerIn" in CSS
    assert ".match-dialog" in CSS and "inset:0 0 0 auto" in CSS
    assert ".daily-hub-table thead" in CSS and "position:sticky" in CSS
