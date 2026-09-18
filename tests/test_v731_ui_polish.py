import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'web/app.js').read_text(encoding='utf-8')
INDEX=(ROOT/'web/index.html').read_text(encoding='utf-8')
CSS=(ROOT/'web/final-polish-731.css').read_text(encoding='utf-8')
cache = str(json.loads((ROOT/'web/ui-config.json').read_text(encoding='utf-8'))['asset_revision'])


def test_v731_layer_is_loaded_last():
    assert f'/final-polish-731.css?v={cache}' in INDEX
    assert INDEX.index('/final-polish-725.css') < INDEX.index('/final-polish-731.css')


def test_player_photos_are_in_daily_board_and_results():
    assert "smallAvatar(photoFor(player,side),name,row?.tour" in APP
    assert 'results-match-player' in APP and 'results-opponent' in APP
    assert "smallAvatar(p1Photo,p1Name,r?.tour" in APP
    assert '/assets/missing_foto_m.webp' in APP
    assert '/assets/missing_foto_w.webp' in APP


def test_tournament_logo_has_deterministic_fallback():
    assert "classList.add(\\'logo-failed\\');this.remove()" in APP
    assert '.hub-tournament-logo.logo-failed>img' in CSS
    assert '.hub-tournament-logo.logo-failed .hub-logo-fallback' in CSS
    assert '/assets/tournament-fallbacks/tennis.svg' in APP


def test_header_and_loader_polish_contract():
    assert 'grid-template-columns:108px auto minmax(36px,1fr) auto' in CSS
    assert 'Načítavam model · live dáta · dnešné predikcie' in CSS
    assert 'width:min(520px,82vw)' in CSS


def test_tournament_metadata_is_not_forced_to_single_line():
    assert '.hub-tournament-copy>small{white-space:normal' in CSS
    assert 'flex-wrap:wrap' in CSS
