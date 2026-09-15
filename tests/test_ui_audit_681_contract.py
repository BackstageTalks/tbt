from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'web/index.html').read_text(encoding='utf-8')
APP = (ROOT / 'web/app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'web/polish-681.css').read_text(encoding='utf-8')


def test_final_polish_layer_and_new_loader_asset_are_active():
    assert '/polish-681.css?v=6808' in INDEX
    assert '/assets/blinq_loading_tennis_v2.webp?v=6808' in INDEX
    assert (ROOT / 'web/assets/blinq_loading_tennis_v2.webp').is_file()
    assert '@keyframes bq-loader-rally' in CSS
    assert 'animation:bq-loader-rally 1.85s' in CSS


def test_results_filter_order_matches_public_prediction_order():
    token = "['all','top_daily','prime','value','ace','double_faults','sg','doubles']"
    assert token in APP
    for label in ('TOP predikcie', 'Short Odds', 'Esá', 'Dvojchyby', 'Sety a gamy', 'Štvorhra'):
        assert label in APP


def test_account_modal_keeps_verification_with_email_and_compact_editor():
    block = APP.split('function renderAccountModal()', 1)[1].split('function openAccountDialog()', 1)[0]
    assert 'account-email-fact' in block
    assert 'account-verified' in block
    assert 'account-profile-editor' in block
    assert 'Vyber si svoju úroveň' in block
    assert 'account-profile-editor>.account-inline-field' in CSS


def test_match_detail_has_full_modal_tabs_and_popout():
    block = APP.split('function matchDetailHtml', 1)[1].split('function openMatchPopout', 1)[0]
    for tab in ('Prehľad', 'Štatistiky', 'Radar', 'História'):
        assert tab in block
    assert 'data-match-popout' in block
    assert 'renderMotivationPanel(row)' in block
    assert 'data-rail-open-modal' in APP


def test_mobile_dashboard_uses_card_rows_and_scrollable_category_tabs():
    assert '@media(max-width:620px)' in CSS
    assert 'scroll-snap-type:x proximity' in CSS
    assert 'grid-template-areas:"time tournament detail" "match match match" "pick odds probability"' in CSS
    assert 'host.dataset.tab=tab' in APP
