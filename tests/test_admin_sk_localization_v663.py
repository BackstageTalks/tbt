from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_admin_primary_ui_is_slovak():
    app = read("web/app.js")
    for text in [
        "Admin centrum",
        "Bannery a odkazy",
        "Kategórie · predikcie · prístupy",
        "Uložiť koncept",
        "Publikovať zmeny",
        "Prime",
        "TOP",
        "Esá",
        "Štvorhra",
        "Sety / hry",
        "Účty",
        "Kvalita modelu",
    ]:
        assert text in app

def test_live_match_intelligence_remains_wired():
    app = read("web/app.js")
    auth = read("web/auth.js")
    api = read("api/function_app.py")
    assert "requestLiveMatchIntelligence" in app
    assert "/api/v1/match-intelligence" in auth
    assert 'route="v1/match-intelligence"' in api
