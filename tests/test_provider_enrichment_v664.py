from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_provider_has_full_presentation_endpoints():
    text = read("api/tbt/providers/rapidapi.py")
    assert "def player_details" in text
    assert 'f"/api/tennis/player/{player_id}"' in text
    assert "def head_to_head_history" in text
    assert 'f"/api/tennis/match/{token}/h2h"' in text
    assert 'f"/api/tennis/player/{player_id}/events/near"' in text
    assert 'f"/api/tennis/player/{player_id}/events/previous/{page}"' in text
    assert 'f"/api/tennis/player/{player_id}/events/next/{page}"' in text


def test_refresh_automatically_builds_presentation_assets_before_feed():
    text = read(".github/workflows/data.yml")
    enrich = text.index("Refresh presentation metadata for current feed")
    prepare = text.index("Prepare refreshed serving feed and cached player assets")
    assert enrich < prepare
    assert "scripts/enrich_player_cards.py" in text
    assert "--max-player-detail-requests" in text


def test_player_profile_details_are_merged_into_serving_feed():
    enrich = read("scripts/enrich_player_cards.py")
    prepare = read("scripts/prepare_feed.py")
    for key in ("birth_date", "height_cm", "hand", "birthplace", "residence"):
        assert key in enrich
        assert key in prepare


def test_match_intelligence_has_feed_fallback_and_direct_h2h():
    text = read("api/function_app.py")
    assert "def _feed_match_intelligence" in text
    assert "client.head_to_head_history(custom_id)" in text
    assert "client.player_details(pid)" in text
    assert '"live_provider": False' in text


def test_frontend_passes_custom_id_to_h2h_enrichment():
    auth = read("web/auth.js")
    app = read("web/app.js")
    assert "custom_id: String(customId || '')" in auth
    assert "row?.custom_id||row?.customId||''" in app


def test_previous_player_history_uses_live_verified_route_without_legacy_fallback():
    from tbt.providers.rapidapi import RapidTennisClient

    client = object.__new__(RapidTennisClient)
    calls = []

    def fake_get(path, params=None, *, enrichment=False):
        calls.append((path, enrichment))
        return {"events": [{"id": 14494928}], "hasNextPage": True}

    client._get = fake_get
    response = client.previous_player_matches(206570, page=0)
    assert response["events"][0]["id"] == 14494928
    assert calls == [(
        "/api/tennis/player/206570/events/previous/0", True)]
