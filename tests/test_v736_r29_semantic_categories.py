from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
UI = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
RELEASE = json.loads((ROOT / "web" / "release.json").read_text(encoding="utf-8"))


def test_r29_release_identity_and_exact_public_labels():
    assert UI["ui_patch"] == "736-r30"
    assert RELEASE["patch"] == "736-r30"
    assert "ESÁ / DVOJCHYBY" in APP
    assert "ŠTVORHRA" in APP
    assert UI["dashboard"]["daily_hub"]["tabs"]["ace"]["label"] == "Esá / dvojchyby"
    assert UI["dashboard"]["daily_hub"]["tabs"]["doubles"]["label"] == "Štvorhra"
    assert UI["dashboard"]["sections"]["ace"]["label"] == "Aces / Double Faults"


def test_r29_has_one_fail_closed_market_family_guard_for_all_views():
    assert "function predictionFamily(row)" in APP
    assert "function marketRowMatches(key,row)" in APP
    assert "if(key==='ace')return family==='ace';" in APP
    assert "if(key==='doubles')return family==='doubles';" in APP
    assert "if(key==='sg')return family==='games'||family==='sets';" in APP
    assert "if(['prime','top_daily','value'].includes(key))return family==='singles';" in APP
    assert "const clean=rows.filter(row=>marketRowMatches(key,row));" in APP
    assert "marketRowMatches('top_daily',row)" in APP


def test_r29_ace_detail_uses_exact_market_name_not_generic_esa():
    assert "${escapeHtml(d.market.toUpperCase())} · ${escapeHtml(match.tour)}" in APP
    assert '<div class="dialog-eyebrow">ESA ·' not in APP


def test_r29_results_do_not_label_double_faults_as_esa():
    assert "settled Double Faults projection sample" in APP
    assert "vyhodnotená vzorka projekcií dvojchýb" in APP
    assert "settled ESA projection sample" not in APP
