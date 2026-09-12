from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "premium-v2.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_prime_top_and_value_cards_keep_four_metrics():
    assert "[publicText('Odds')" in APP
    assert "lcopy('Form','Forma','Forma')" in APP
    assert "['EV'" in APP
    assert "repeat(4,minmax(0,1fr)) minmax(88px,auto)" in CSS


def test_ace_cards_require_real_api_line_and_use_prediction_copy():
    assert "function apiMarketLine(row)" in APP
    assert "sourceRows.filter(aceHasApiLine)" in APP
    assert "lcopy('Prediction','Predikcia','Predikce')" in APP
    assert "lcopy('Line','Hranica','Hranice')" in APP
    assert "lcopy('PREDICTION','PREDIKCIA','PREDIKCE')" in APP


def test_cache_bust_is_current():
    import json
    cfg = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    expected = "v=" + str(cfg["ui_revision"]).replace(".", "")
    assert expected in INDEX
    assert "v=6539" not in INDEX
