from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_daily_offer_copy_and_lock_are_consolidated():
    html = read("web/index.html")
    app = read("web/app.js")
    assert "Prehľad" in read("web/ui-config.json")
    assert "Zobraziť celú ponuku" in app
    assert "Dnešné bety" not in html
    assert "daily-hub-results" in app
    assert "data-route=\"results\"" in app
    assert "Táto položka je dostupná od úrovne" in app
    assert "'PREDIKCIA'" in app


def test_membership_is_json_driven_and_dual_avatar_cards_exist():
    links = json.loads(read("web/membership-links.json"))
    app = read("web/app.js")
    assert links["schema"] == 3
    assert set(links["plans"]) >= {"rookie", "pro", "elite", "legend", "goat"}
    assert "planAvatarPairHtml" in app
    assert "payment_url" in read("web/membership-links.json")
    assert "cta_label" in read("web/membership-links.json")


def test_all_banner_slots_have_image_plus_copy_editor():
    app = read("web/app.js")
    assert "Podklad bannera" in app
    assert "Odporúčaný formát pre tento slot" in app
    assert 'data-simple-banner-field="image_url"' in app
    assert 'data-simple-banner-field="headline"' in app
    assert 'data-simple-banner-field="text"' in app
    assert 'data-simple-banner-field="button_text"' in app


def test_admin_diagnostics_are_wired_end_to_end():
    app = read("web/app.js")
    auth = read("web/auth.js")
    api = read("api/function_app.py")
    assert "adminDiagnostics" in app
    assert "/api/v1/admin/diagnostics" in auth
    assert 'route="v1/admin/diagnostics"' in api
    assert "firebase_server_configured" in api
    assert "problems" in api


def test_static_environment_is_active_but_archive_weather_remains_masked():
    ensemble = read("api/tbt/models/ensemble.py")
    table = read("scripts/build_production_training_table.py")
    assert 'self.excluded_features = {"weather_serve_interaction", "weather_known"}' in ensemble
    assert '"environment_known", "indoor"' in table
    assert 'WEATHER_RESEARCH_FEATURES = ["weather_serve_interaction", "weather_known"]' in table
