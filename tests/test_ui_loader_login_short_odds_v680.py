from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
RELEASE = json.loads((ROOT/'web'/'release.json').read_text(encoding='utf-8'))
PATCH = str(RELEASE['patch'])
PATCH_NUM = PATCH.rsplit('r',1)[-1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
ASSETS = ROOT / "web" / "assets"
LOADER = (ASSETS / "blinq-loader.webp").read_bytes()
STATIC = (ASSETS / "blinq-loader-static.webp").read_bytes()
GIF = (ASSETS / "blinq-loader.gif").read_bytes()


def test_loader_is_dark_animated_webp_with_fallbacks_and_no_progress_track():
    assert '/assets/blinq-loader.webp' in INDEX
    assert '/assets/blinq-loader-static.webp' in INDEX
    assert '/assets/blinq-loader.gif' in INDEX
    assert 'prefers-reduced-motion: reduce' in INDEX
    assert 'boot-tennis-track' not in INDEX
    assert LOADER[:4] == b'RIFF' and LOADER[8:12] == b'WEBP'
    assert b'ANIM' in LOADER[:4096]
    assert STATIC[:4] == b'RIFF' and STATIC[8:12] == b'WEBP'
    assert GIF.startswith((b'GIF87a', b'GIF89a'))

def test_auth_login_hides_signup_only_telegram_field():
    assert 'id="nameLabel" hidden' in INDEX
    assert ".auth-card label[hidden]{display:none!important}" in CSS
    assert "background:linear-gradient(100deg,#35e69c,#47efbd)!important" in CSS


def test_short_odds_public_labels_replace_prime_in_results_and_cards():
    assert "prime:'Short Odds'" in APP
    assert "key==='prime'?'Short Odds Prediction'" in APP
    assert "publicText('Short Odds rule')" in APP
    assert "No Short Odds predictions available yet" in APP
    assert "Načítavam Prime predikcie" not in APP
    assert "Pravidlo Prime" not in APP
    assert "Prime predikcia" not in APP


def test_frontend_cache_bust_for_final_ui_pass():
    cfg = json.loads((ROOT / 'web' / 'ui-config.json').read_text(encoding='utf-8'))
    cache = str(cfg['asset_revision'])
    for asset in ('blinq-app.css','app.js'):
        assert f'/{asset}?v={cache}' in INDEX
    for asset in ('blinq-loader.webp', 'blinq-loader-static.webp', 'blinq-loader.gif'):
        assert f'/assets/{asset}?v={cache}&p={PATCH_NUM}' in INDEX


def test_loader_current_is_compact_centered_and_without_duplicate_logo():
    assert 'width:min(352px,calc(100vw - 40px))!important' in CSS
    assert 'aspect-ratio:704/410!important' in CSS
    assert 'background:#031314!important' in CSS
    assert 'class="blinq-loader-media"' in INDEX
    assert 'src="/assets/blinq-loader.gif' in INDEX
    assert 'srcset="/assets/blinq-loader.webp' in INDEX
    assert 'srcset="/assets/blinq-loader-static.webp' in INDEX
    assert 'filter:none!important' in CSS
    assert LOADER[:4] == b'RIFF' and b'ANIM' in LOADER[:4096]
