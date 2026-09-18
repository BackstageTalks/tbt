import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "final-polish-724.css").read_text(encoding="utf-8")
cache = str(json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))["asset_revision"])


def test_final_polish_is_loaded_after_lean_layer():
    lean = INDEX.index(f'/blinq-lean-700.css?v={cache}')
    final = INDEX.index(f'/final-polish-724.css?v={cache}')
    assert final > lean


def test_daily_hub_uses_tournament_logo_and_professional_match_rows():
    assert 'hub-tournament hub-tournament-pro' in APP
    assert 'tournamentVisual(row)' in APP
    assert 'hub-match hub-match-pro' in APP
    assert 'hub-match-player-main' in APP
    assert 'flagIconHtml(country,true)' in APP


def test_daily_hub_headers_and_cells_have_semantic_layout_classes():
    assert "return ['#','ČAS','TURNAJ','ZÁPAS','PREDIKCIA','KURZ','BLINQ %','EDGE',''];" in APP
    assert 'dailyHubColumnKeys(tab)' in APP
    assert 'hub-tournament-cell' in APP
    assert 'hub-match-cell' in APP
    assert 'hub-confidence-cell' in APP
    assert 'hubConfidenceHtml' in APP


def test_footer_links_are_simple_configurable_cards():
    assert 'Spodné odkazy' in APP
    assert 'benefit_${n}_text' in APP
    assert 'benefit_${n}_link' in APP
    assert 'vip-link-arrow' in APP
    assert 'class="vip-link-card is-static"' in APP


def test_final_css_covers_header_board_flags_and_footer():
    for selector in (
        '.site-header.reference-topbar',
        '.hub-tournament-pro',
        '.hub-match-pro',
        '.hub-confidence',
        '#vipRail .vip-link-card',
        '.admin-footer-link-grid',
    ):
        assert selector in CSS
