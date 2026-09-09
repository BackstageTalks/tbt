from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v657_featured_banner_rotation_and_single_slot():
    js=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    css=(ROOT/'web'/'styles.css').read_text(encoding='utf-8')
    assert 'function renderFeaturedBanner()' in js
    assert 'function scheduleFeaturedBannerRotation()' in js
    assert "featured_rotation_ms" in js
    assert "bannerHtml(entry.item,false,index,4)" in js
    assert '#bannerTop .promo-card' in css
    assert 'width:100%!important' in css


def test_v657_mobile_two_micro_plus_one_featured_layout():
    css=(ROOT/'web'/'styles.css').read_text(encoding='utf-8')
    assert '2 micro + 1 featured' in css
    assert 'calc((100% - 5px)/2)' in css
    assert '#bannerTop .promo-card.span-4' in css
    assert 'height:72px!important' in css
    assert '#predictionsView .prediction-card:nth-child(n+2){display:none!important}' in css


def test_v657_compacts_desktop_and_bumps_pwa_cache():
    css=(ROOT/'web'/'styles.css').read_text(encoding='utf-8')
    sw=(ROOT/'web'/'sw.js').read_text(encoding='utf-8')
    assert '--content-max:1320px' in css
    assert 'grid-template-columns:repeat(3,minmax(0,1fr))' in css
    assert 'blinq-shell-v657' in sw
