"""Scope and renderer guards for approved compact BlinQ mobile cards."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/"web"
APP=(WEB/"app.js").read_text(encoding="utf-8")
INDEX=(WEB/"index.html").read_text(encoding="utf-8")
CSS=(WEB/"blinq-mobile-unified-cards.css").read_text(encoding="utf-8")

def test_mobile_card_styles_loaded_last_and_versioned():
    assert '/blinq-mobile-unified-cards.css?v=7360&p=61&cards=20261105-units-1' in INDEX
    assert INDEX.index('blinq-mobile-density.css?') < INDEX.index('blinq-mobile-unified-cards.css?')
    assert '@media (max-width:600px)' in CSS
    assert ':not(.blinq-admin)' in CSS
    assert '#dailyHub:not([data-tab="see_all"])' in CSS

def test_verified_started_status_only_and_no_fake_live_markers():
    renderer=APP.split('function dailyHubRow(',1)[1].split('function dailyHubLockedRow(',1)[0]
    assert 'const started=row?.runtime_match_started===true;' in renderer
    assert 'const mobileStatus=started' in renderer
    assert 'const mobileTournament=mobileStatus?tournament.replace' in renderer
    assert 'const mobileStatus=uncertain' not in renderer
    assert 'class="hub-mobile-started is-started"' in renderer
    assert '.hub-time .hub-offer-status {display:none!important;}' in CSS

def test_native_details_and_projection_evidence():
    renderer=APP.split('function dailyHubRow(',1)[1].split('function dailyHubLockedRow(',1)[0]
    assert renderer.count('hub-mobile-only') == 2
    assert 'data-sg-projection' in renderer
    assert 'aceProjectionDetailAvailable(row)?' in renderer
    assert 'data-ace-projection' in renderer
    assert 'hubMatchDetailButtonHtml()' in renderer
    assert 'hub-number-cell' in renderer
    assert '.hub-mobile-only {display:none!important;}' in CSS
    assert 'hub-seeall-model' in APP
    assert ':is(.hub-data-depth,.hub-seeall-confidence small) {display:none!important;}' in CSS


def test_results_and_predictions_premium_surface_is_shared():
    assert 'mobile premium feed v2' in CSS
    assert '.results-table tbody tr.results-card-row' in CSS
    assert '.hub-pick-stack small::before' in CSS
    assert '.results-card-row .result-prediction strong' in CSS
    assert 'result-loss' in CSS and 'result-void' in CSS
    assert 'grid-template-areas:"date status"' in CSS


def test_mobile_result_units_respect_win_loss_void_and_unpriced_states():
    # Signed units are already classified by the Results renderer; the mobile
    # CSS must not apply unconditional green to both positive and negative.
    assert "units>=0?'correct':'wrong'" in APP
    assert "displayUnits<0?'wrong'" in APP
    block=CSS.split("/* Signed Results values must keep their settlement color on mobile.",1)[1]
    block=block.split("/* Compact pick body",1)[0]
    assert "color:#79d6ae!important;font-size:12px!important" not in block
    for state,color in (("correct","#79d6ae"),("wrong","#e98787"),("void","#c99aff")):
        start=block.index(f".results-card-row .result-units.{state},")
        child=block.index(f".results-card-row .result-units .results-units-depth b.{state} {{",start)
        declaration=block[child:].split("}",1)[0]
        assert f"color:{color}!important;" in declaration, state
    assert ".results-card-row .result-units.unit-excluded" in block
    assert "color:#849b94!important;" in block
