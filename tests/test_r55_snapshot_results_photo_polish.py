from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
PIPELINE = (ROOT / "scripts" / "pipeline.py").read_text(encoding="utf-8")


def test_results_use_top_short_label_and_no_actual_column():
    assert "top_daily:'TOP'" in APP
    assert "TOP predikcie" not in APP[APP.index("function resultCategoryLabel"):APP.index("function resultPickIdentity")]
    results = APP[APP.index("function renderResults(){"):APP.index("function wireResultsFilters()")]
    assert "<th>Skutočne</th>" not in results
    assert "<th>Výsledok</th>" in results
    assert 'class="results-outcome-stack"' in results
    assert 'class="results-actual"' in results


def test_results_typography_is_overridden_to_one_data_size():
    assert "R55 final polish — deterministic player fallbacks + calm Results typography" in CSS
    assert ".results-table td strong" in CSS
    assert ".results-opponent strong" in CSS
    assert "font-size:11px!important;line-height:1.25!important" in CSS


def test_player_avatar_fallback_is_layered_not_async_src_replacement():
    assert "function playerAvatarParts" in APP
    assert "function applyPlayerAvatarHost" in APP
    assert "data-player-fallback" in APP
    assert "data-player-photo" in APP
    assert ".layered-player-avatar .player-avatar-fallback" in CSS
    assert ".layered-player-avatar .player-avatar-initials" in CSS


def test_daily_offer_snapshot_is_a_dedicated_release_asset():
    assert 'daily_offer_snapshot.json' in PIPELINE
    assert 'snapshot_sources = []' in PIPELINE
    assert 'snapshot_sources.append(prior_snapshot)' in PIPELINE
    assert 'snapshot_sources.append(prior_feed)' in PIPELINE
    assert 'build_daily_offer_snapshot(' in PIPELINE
