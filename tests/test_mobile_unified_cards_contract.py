"""Scope and renderer guards for approved compact BlinQ mobile cards."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/"web"
APP=(WEB/"app.js").read_text(encoding="utf-8")
INDEX=(WEB/"index.html").read_text(encoding="utf-8")
CSS=(WEB/"blinq-mobile-unified-cards.css").read_text(encoding="utf-8")

def test_mobile_card_styles_loaded_last_and_versioned():
    assert '/blinq-mobile-unified-cards.css?v=7360&p=61&cards=20261030-1' in INDEX
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
