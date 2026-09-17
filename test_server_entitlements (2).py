from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def test_locked_access_uses_hint_and_explicit_upgrade_uses_dialog():
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    html=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
    assert 'id="accessHint"' in html
    assert 'data-upgrade-explicit="1"' in html
    assert "showAccessHint(upgradeTarget,plan,section,true)" in app
    assert "if(upgradeTarget.dataset.upgradeExplicit==='1')showUpgradePrompt(plan,section)" in app
    assert 'Dostupné od úrovne' in app


def test_live_is_visible_but_locked_below_elite():
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    assert "shortcut.hidden=!eligible" in app
    assert "shortcut.classList.toggle('is-access-locked',eligible&&!liveEligible)" in app
    assert "shortcut.dataset.upgradePlan='elite'" in app


def test_mobile_hint_and_compact_profile_styles_exist():
    css=(ROOT/'web'/'blinq-lean-700.css').read_text(encoding='utf-8')
    assert '.access-hint' in css
    assert '@media(max-width:560px)' in css
    assert '.reference-topbar .profile-shell' in css
    assert '.insight-info-button' in css
