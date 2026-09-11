import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v6513_upgrade_dialog_uses_membership_facts_and_closes_on_navigation():
    cfg = json.loads((ROOT / 'web' / 'ui-config.json').read_text(encoding='utf-8'))
    assert tuple(map(int, cfg['ui_revision'].split('.'))) >= (6, 5, 13)
    app = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
    assert 'function upgradePlanFacts' in app
    assert "publicText('Validity')" in app
    assert 'upgrade-dialog-account-facts' in app
    assert "target.closest('#upgradeDialog')" in app
    assert 'upgradeDialog.close()' in app


def test_v6513_avatar_labels_are_not_rendered_over_membership_artwork():
    app = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
    css = (ROOT / 'web' / 'responsive.css').read_text(encoding='utf-8')
    assert 'avatarAssetSrc' in app
    assert '?v=v65' in app
    plan_fn = app.split('function planAvatarHtml', 1)[1].split('function renderPlanCardsForAccount', 1)[0]
    assert '<em>' not in plan_fn
    assert '.plan-card-avatar em{display:none!important}' in css


def test_v6513_desktop_header_controls_match_cta_height():
    css = (ROOT / 'web' / 'responsive.css').read_text(encoding='utf-8')
    assert '--blinq-header-control-h:62px' in css
    assert '.top-upgrade,.profile-shell{height:var(--blinq-header-control-h)!important' in css
    assert '.header-feature-strip .header-slot{height:var(--blinq-header-control-h)!important' in css
