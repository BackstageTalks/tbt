from pathlib import Path
import json
import re

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
CSS=(ROOT/'web'/'blinq-app.css').read_text(encoding='utf-8')
RELEASE=json.loads((ROOT/'web'/'release.json').read_text(encoding='utf-8'))

def test_membership_admin_exists_and_edits_runtime_plans():
    assert "['levels','Členstvá','Levely · odkazy']" in APP
    assert 'function renderAdminLevels()' in APP
    for field in ('enabled','label','card_title','short_description','description','cta_label','url','invite_url','duration_days','features'):
        assert f'data-admin-level-field="{field}"' in APP
    assert 'runtimeConfigSnapshot?.plans' in APP
    assert 'state.ui?.plans?.[id]?.features' in APP
    assert 'data-admin-level-field="lifetime"' not in APP
    assert 'data-admin-level-field="order"' not in APP
    assert 'admin-membership-static-mark' in APP

def test_legacy_expanded_layout_editor_is_not_rendered():
    assert 'Rozšírené sekcie dashboardu' not in APP
    assert 'Ďalšie stránky' not in APP
    assert 'data-section-preset=' not in APP

def test_accounts_grid_no_longer_overflows_into_editor():
    assert 'admin-accounts-split-v22' in APP
    assert 'grid-template-columns:minmax(0,1.18fr) minmax(360px,.82fr)' in CSS
    assert 'grid-template-columns:minmax(0,1.7fr) minmax(70px,.55fr)' in CSS
    assert 'admin-accounts-split-v22.no-selection' in CSS
    assert 'admin-layout-advanced' not in APP

def test_membership_admin_survives_newer_release_patches():
    match=re.fullmatch(r'736-r(\d+)', RELEASE['patch'])
    assert match and int(match.group(1)) >= 22
    assert f"runtime patch 7.3.6-r{match.group(1)}" in CSS
