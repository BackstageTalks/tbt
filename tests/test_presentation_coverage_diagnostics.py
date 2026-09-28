"""Read-only diagnostics must report real deployed photos and real provider odds."""
from function_app import _feed_asset_health


def card(event, *, odds=None, betting=None, market="match_winner"):
    row = {
        "event_id": event,
        "market": market,
        "player1": {"id": str(int(event) * 2 + 1), "name": "A"},
        "player2": {"id": str(int(event) * 2 + 2), "name": "B"},
        "tournament": "Test",
        "tournament_id": str(1000 + int(event)),
    }
    if odds is not None:
        row["odds"] = odds
    if betting is not None:
        row["betting"] = betting
    return row


def test_numeric_player_id_is_not_counted_as_a_deployed_photo():
    feed = {
        "player_assets": {
            "available": True,
            "player_ids_requested": 4,
            "photos_deployed": 3,
            "photos_missing": 1,
        },
        "tournament_assets": {
            "available": True,
            "tournament_ids_requested": 2,
            "logos_deployed": 1,
            "logos_missing": 1,
        },
        "top_daily_picks": [
            card("1", odds=1.70),
            card("2", odds=1.80),
        ],
    }
    health = _feed_asset_health(feed)
    players = health["player_images"]
    assert players["total"] == 4
    assert players["deployed_assets"] == 3
    assert players["fallback_needed"] == 1
    assert players["provider_or_proxy_refs"] == 4
    assert players["ok"] is False

    logos = health["tournament_logos"]
    assert logos["total"] == 2
    assert logos["deployed_assets"] == 1
    assert logos["fallback_needed"] == 1
    assert logos["ok"] is False


def test_real_betting_price_coverage_is_separate_from_projection_price_coverage():
    synthetic = card("4", odds=1.65)
    synthetic["historical_display_placeholder_source"] = "synthetic_illustrative_not_bookmaker"

    feed = {
        "prime_picks": [card("1", odds=1.45)],
        "top_daily_picks": [card("2")],
        "value_picks": [card("3", betting={"odds": 2.05})],
        "doubles_picks": [synthetic],
        "ace_picks": [
            card("5", odds=1.91, market="aces"),
            card("6", market="double_faults"),
        ],
        "sg_picks": [
            card("7", odds=1.88, market="games"),
            card("8", market="sets"),
        ],
    }
    health = _feed_asset_health(feed)
    required = health["market_odds"]["required"]
    assert required == {
        "total": 4,
        "priced": 2,
        "missing": 2,
        "coverage": 0.5,
        "ok": False,
        "sections": {
            "short_odds": {"total": 1, "priced": 1, "missing": 0, "coverage": 1.0},
            "top": {"total": 1, "priced": 0, "missing": 1, "coverage": 0.0},
            "value": {"total": 1, "priced": 1, "missing": 0, "coverage": 1.0},
            "doubles": {"total": 1, "priced": 0, "missing": 1, "coverage": 0.0},
        },
    }

    projections = health["market_odds"]["projections"]
    assert projections["total"] == 4
    assert projections["priced"] == 2
    assert projections["missing"] == 2
    assert projections["sections"]["aces"]["priced"] == 1
    assert projections["sections"]["double_faults"]["missing"] == 1
    assert projections["sections"]["games"]["priced"] == 1
    assert projections["sections"]["sets"]["missing"] == 1
