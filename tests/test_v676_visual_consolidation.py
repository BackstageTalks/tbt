from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'web' / 'blinq.css').read_text(encoding='utf-8')
INDEX = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
UI = (ROOT / 'web' / 'ui-config.json').read_text(encoding='utf-8')


def test_cache_and_ui_revision_are_current():
    cfg = json.loads(UI)
    assert cfg['ui_revision'] == cfg['revision'] == '6.8.6'
    assert cfg['asset_revision'] == '6860'
    assert '?v=6860' in INDEX


def test_account_modal_has_inline_telegram_profile():
    assert 'account-modal-main-card' in APP
    assert 'account-inline-telegram' in APP
    assert 'account-modal-security' not in APP
    assert '<details class="account-modal-profile"' not in APP


def test_admin_unavailable_state_does_not_show_fake_zero_accounts():
    assert 'Účty sa nenačítali — nejde o nulový počet účtov.' in APP
    assert 'admin-accounts-unavailable' in APP


def test_public_config_avoids_betting_terminology():
    assert 'Top Bets' not in UI
    assert 'Premium Picks' not in UI
    assert 'Value Picks' not in UI
    assert 'Prime Picks' not in UI


def test_v676_visual_layer_present():
    assert 'BlinQ 6.7.6 — consolidated visual system' in CSS
    assert '.account-modal-main-card' in CSS
    assert '.admin-banner-workspace' in CSS
    assert '.admin-tabs-v675' in CSS
