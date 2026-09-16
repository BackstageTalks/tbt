from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "polish-684.css").read_text(encoding="utf-8")


def test_local_country_flags_are_packaged_and_used():
    assert "const flagAssetUrl" in APP
    assert "/assets/flags/${value.toLowerCase()}.png" in APP
    assert "flagcdn" not in APP.lower()
    flags = WEB / "assets" / "flags"
    for code in ("sk", "us", "gb", "cz", "fr", "de", "es", "it"):
        assert (flags / f"{code}.png").is_file()


def test_player_meta_and_rank_visual_contract():
    assert "playerMetaHtml" in APP
    assert "hubPlayerMeta" in APP
    assert ".hub-rank" in CSS
    assert "font-variant-numeric:tabular-nums" in CSS


def test_tournament_logo_resolver_and_fallback_assets():
    assert "function tournamentFallbackBadge" in APP
    assert "/api/v1/tournament-logo/${tournamentId}" in APP
    assert "team-cup.svg" in APP
    assert "team-event.svg" in APP
    assert "utr.svg" in APP
    assert "wta-125.svg" in APP
    fallback_dir = WEB / "assets" / "tournament-fallbacks"
    for name in ("team-cup.svg", "team-event.svg", "utr.svg", "wta-125.svg"):
        assert (fallback_dir / name).is_file()


def test_banner_admin_uses_clickable_homepage_map():
    assert "function adminBannerMapSlot" in APP
    assert "function renderAdminBannerMap" in APP
    assert "admin-site-map" in APP
    assert "Rozloženie stránky ostáva pevné" in APP
    assert "data-admin-element" in APP
    assert ".admin-site-map" in CSS
    assert ".admin-banner-map-workspace" in CSS


def test_account_admin_is_simple_and_supports_flexible_expiry():
    assert 'function renderAdminUserEditor' in APP
    assert 'Poslať link na obnovu hesla' in APP
    assert 'data-admin-action="apply-default-term"' in APP
    assert 'data-admin-action="extend-default-term"' in APP
    for days in ('30','90','180','365'):
        assert f'data-admin-expiry-days="{days}"' in APP
    assert 'adminUserEmail' in APP and 'adminUserTelegram' in APP
    assert '.admin-simple-plans' in (WEB / 'admin-polish-687.css').read_text(encoding='utf-8')


def test_684_visual_layer_is_loaded_with_current_cache():
    cfg = json.loads((WEB / 'ui-config.json').read_text(encoding='utf-8'))
    cache = cfg['asset_revision']
    assert f'/polish-684.css?v={cache}' in INDEX
    assert f'/app.js?v={cache}' in INDEX
