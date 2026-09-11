from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_professional_polish_layer_is_loaded_last():
    html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
    assert '/professional-polish.css?v=20260911-6527' in html
    assert html.index('/premium-theme.css') < html.index('/professional-polish.css')


def test_professional_polish_has_responsive_accessibility_and_six_grid_rules():
    css = (ROOT / 'web' / 'professional-polish.css').read_text(encoding='utf-8') + (ROOT / 'web' / 'premium-theme.css').read_text(encoding='utf-8')
    for token in (
        '.dashboard-six-grid',
        'data-active-count="5"',
        ':focus-visible',
        '@media(max-width:760px)',
        '@media(prefers-reduced-motion:reduce)',
        '.dashboard-locked-card',
        '.market-empty',
        '.probability-label',
    ):
        assert token in css


def test_navigation_order_matches_current_product_spec():
    cfg = json.loads((ROOT / 'web' / 'ui-config.json').read_text(encoding='utf-8'))
    nav = sorted(
        (
            (row['order'], row['content']['route'])
            for row in cfg['elements'].values()
            if row.get('kind') == 'navigation' and row.get('content', {}).get('route') not in {'admin'}
        )
    )
    assert [route for _, route in nav] == [
        'predictions', 'prime', 'top_daily', 'ace', 'value', 'doubles', 'sg', 'results', 'overview', 'btts'
    ]


def test_ui_semantics_distinguish_model_probability_and_projection_only_outputs():
    app = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
    assert 'probability-label' in app
    assert "'Projection only · no odds'" in app
    assert "lcopy('Confidence','Istota','Jistota')" in app
    assert 'function emptyStateCard' in app
    assert 'function uiIconSvg' in app
