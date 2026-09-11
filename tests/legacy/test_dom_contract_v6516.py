import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_static_dom_ids_used_by_boot_are_not_translated():
    html=(ROOT/'web/index.html').read_text(encoding='utf-8')
    required={'authEmail','authPassword','authPasswordToggle','menuClose','dialogClose','upgradeDialogClose','tooltipAccountEmail'}
    ids=set(re.findall(r'id="([^"]+)"',html))
    assert required <= ids
    forbidden={'authE-mail','authHeslo','authHesloToggle','menuZavrieť','dialogZavrieť','upgradeDialogZavrieť','tooltipAccountE-mail'}
    assert not (forbidden & ids)

def test_direct_dom_id_references_resolve_or_are_dynamic_optional():
    html=(ROOT/'web/index.html').read_text(encoding='utf-8')
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    responsive=(ROOT/'web/responsive.js').read_text(encoding='utf-8')
    ids=set(re.findall(r'id="([^"]+)"',html))
    refs=set(re.findall(r"\$\('([^']+)'\)",app+'\n'+responsive))
    dynamic={x for x in refs if f'id="{x}"' in app or f"id='{x}'" in app}
    allowed_optional={'sidebarPromoZone'}
    assert refs-ids-dynamic-allowed_optional == set()

def test_public_copy_stays_slovak_but_identifiers_stay_stable():
    html=(ROOT/'web/index.html').read_text(encoding='utf-8')
    assert '<html lang="sk">' in html
    assert 'Vitaj späť.' in html
    assert 'Zadaj svoj e-mail' in html
    assert 'id="authEmail"' in html
    assert 'id="authPassword"' in html


def test_plan_hidden_banners_are_removed_before_layout_and_rotation():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    assert "filter(item=>item?.content?.enabled!==false&&elementAccess(item.id)!=='hidden')" in app
    assert "elementList('header_slot','header').filter(item=>item?.content?.enabled!==false&&elementAccess(item.id)!=='hidden')" in app
    assert "elementList('hero_banner','hero').filter(item=>item?.content?.enabled!==false&&elementAccess(item.id)!=='hidden')" in app


def test_release_migration_preserves_published_banner_and_access_settings():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    assert "state.ui.hero_banner=mergeConfig" in app
    assert "runtime.config.hero_banner||{}" in app
    assert "state.ui.elements[id].content=clone(state.uiSource.elements[id].content)" not in app
    assert "String(saved.ui_revision||'')===String(state.uiSource?.ui_revision||'')" in app
