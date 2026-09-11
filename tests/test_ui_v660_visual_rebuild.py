from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_final_visual_layer_is_loaded_last():
    html = (ROOT / 'web/index.html').read_text(encoding='utf-8')
    assert '/final-ui.css?v=v660' in html
    assert html.index('/premium-theme.css?v=v660') < html.index('/final-ui.css?v=v660')


def test_homepage_composition_hides_legacy_content_rows():
    app = (ROOT / 'web/app.js').read_text(encoding='utf-8')
    assert "[top,mid,bottom].forEach" in app
    assert "row.hidden=true" in app
    assert "top navigation → three managed CTA blocks → hero → adaptive pick grid" in app


def test_six_panel_grid_and_mobile_breakpoints_exist():
    css = (ROOT / 'web/final-ui.css').read_text(encoding='utf-8')
    assert 'grid-template-columns:repeat(6,minmax(0,1fr))' in css
    assert '[data-active-count="5"]' in css
    assert '[data-grid-slot="5"]' in css
    assert '@media(max-width:900px)' in css
    assert '@media(max-width:620px)' in css
    assert '.dashboard-six-grid{grid-template-columns:1fr!important' in css


def test_search_is_not_a_global_header_control():
    html = (ROOT / 'web/index.html').read_text(encoding='utf-8')
    header = html.split('</header>', 1)[0]
    assert 'type="search"' not in header
    assert 'overview' in (ROOT / 'web/app.js').read_text(encoding='utf-8').lower()


def test_hero_uses_trust_proof_without_unverified_success_claim():
    app = (ROOT / 'web/app.js').read_text(encoding='utf-8')
    assert 'hero-proof-row' in app
    assert 'Modelové predikcie' in app
    assert 'Reálne štatistiky' in app
    assert 'Transparentné výsledky' in app
    assert 'Väčšia úspešnosť' not in app


def test_ace_cards_are_future_ready_for_api_over_under_lines():
    app = (ROOT / 'web/app.js').read_text(encoding='utf-8')
    for field in ['market_line', 'over_under_line', 'total_line', 'threshold']:
        assert field in app
    assert "pickLabel=lcopy('Aces / double-faults O/U'" in app
    assert "scoreLabel=key==='ace'?lcopy('Player projection'" in app
    assert "badge=key==='ace'&&Number.isFinite(marketLine)?'O/U'" in app


def test_cards_have_explicit_score_label_and_clean_empty_states():
    html = (ROOT / 'web/index.html').read_text(encoding='utf-8')
    app = (ROOT / 'web/app.js').read_text(encoding='utf-8')
    assert 'class="score-label">Model</small>' in html
    assert 'premium-empty' in app
    assert 'Zatiaľ žiadne tipy na štvorhru' in app
    assert 'Zatiaľ žiadne tipy na sety / hry' in app
