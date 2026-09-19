from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
INDEX = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
CSS = (ROOT / 'web' / 'final-polish-736.css').read_text(encoding='utf-8')


def test_loader_uses_animated_rally_asset_without_hiding_card():
    assert '/assets/blinq_loading_animated_v6.svg?v=7360' in INDEX
    assert 'clip-path:none!important' in CSS
    assert 'opacity:1!important' in CSS
    assert "url('/assets/blinq_background.webp')" in CSS


def test_image_fallbacks_are_csp_safe_and_global():
    assert 'document.addEventListener(\'error\',handleAssetImageError,true)' in APP
    assert 'data-player-photo' in APP
    assert 'data-tournament-logo' in APP
    assert 'data-flag-image' in APP
    assert 'onerror=' not in APP


def test_results_have_separate_tournament_column_and_location_copy():
    assert '<th>Turnaj</th><th>Zápas</th>' in APP
    assert 'tournamentIdentityHtml(r)' in APP
    assert 'tournament-location' in APP
    assert '.tournament-identity' in CSS


def test_footer_is_neutral_but_keeps_live_diagnostic_signal():
    assert "footer.live_ok" in APP
    assert "wrap.dataset.liveService" in APP
    assert "Dáta synchronizované" in APP
    assert "if(liveFresh)status.textContent" not in APP


def test_changed_assets_have_patch_cache_bust_without_breaking_release_contract():
    assert '/app.js?v=7360&p=3' in INDEX
    assert '/final-polish-736.css?v=7360&p=3' in INDEX
    assert 'data-web-release="7.3.6"' in INDEX
