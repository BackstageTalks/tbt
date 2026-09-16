from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_provider_exposes_player_history_contract():
    text = read("api/tbt/providers/rapidapi.py")
    assert "def previous_player_matches" in text
    assert "/api/tennis/player/{player_id}/events/last/{page}" in text
    assert "def upcoming_player_matches" in text
    assert "def player_near_matches" in text


def test_match_intelligence_route_is_authenticated_and_presentation_only():
    text = read("api/function_app.py")
    assert '@app.route(route="v1/match-intelligence", methods=["GET"])' in text
    assert "_verified_user(req)" in text
    assert '"recent_form": _form_from_events' in text
    assert '"surface_form": _form_from_events' in text
    assert '"ranking_points"' in text
    assert '"h2h_wins"' in text
    assert "Predictive/model features never read from this cache" in text


def test_frontend_hydrates_detail_without_zero_missing_fallback():
    app = read("web/app.js")
    auth = read("web/auth.js")
    assert "matchIntelligence" in auth
    assert "/api/v1/match-intelligence" in auth
    assert "mergeLiveMatchIntelligence" in app
    assert "requestLiveMatchIntelligence" in app
    assert "Number(rankingPoints)>0" in app
    assert "Form L" in app or "`${label} L${Math.round(form.matches)}" in app
