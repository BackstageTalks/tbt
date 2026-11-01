"""Footer health must follow the authenticated match-status updater, not LIVE radar."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_footer_has_two_distinct_clock_fields():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert 'id="footerFeedUpdate"' in html
    assert 'id="footerLastUpdate"' in html
    assert "Aktualizácia —" in html
    assert "Scan —" in html


def test_match_updater_is_only_footer_health_clock():
    script = (ROOT / "web/app.js").read_text(encoding="utf-8")
    footer = script.split("function renderSystemFooterStatus(){", 1)[1].split("function insightTypeLabel(", 1)[0]
    assert "state.feed?.generated_at" in footer
    assert "state.feed?.match_status_updated_at" in footer
    assert "ageMs<=30*60*1000" in footer
    assert "ageMs>=0" in footer
    assert "Number.isFinite(matchScanMs)" in footer
    assert "state.liveRadarHeartbeat" not in footer
    assert "state.userLiveRadarStatus" not in footer
    assert "Match updater mešká" in footer
