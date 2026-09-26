from datetime import datetime, timedelta, timezone

from tbt.services.propline_live import (
    PropLineClient, _match_board, _normalize_book, _price,
    discover_propline_fallback,
)
from tbt.services.projection_odds import (
    enrich_projection_odds, extract_match_total_odds, extract_player_total_ou,
)

NOW = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
START = (NOW + timedelta(hours=5)).isoformat()
MATCH = {
    "event_id": "rapid-133", "scheduled_at": START, "tour": "ATP",
    "player1": {"id": "1", "name": "Álex de Miñaur"},
    "player2": {"id": "2", "name": "Jan-Lennard Struff"},
}
PROP = {"id": "1234", "home_team": "Jan Lennard Struff",
        "away_team": "Alex de Minaur", "commence_time": START}
# American odds are the official default, not decimal!
PRICE_MARKETS = [
    {"key": "total_games", "outcomes": [
        {"name": "Over", "point": 22.5, "price": -110},
        {"name": "Under", "point": 22.5, "price": -105},
    ]},
    {"key": "total_sets", "outcomes": [
        {"name": "Over", "point": 2.5, "price": 140},
        {"name": "Under", "point": 2.5, "price": -160},
    ]},
    {"key": "player_aces", "outcomes": [
        {"name": "Over", "description": "Alex de Minaur", "point": 4.5, "price": 165},
        {"name": "Under", "description": "Alex de Minaur", "point": 4.5, "price": -200},
    ]},
    {"key": "player_double_faults", "outcomes": [
        {"name": "Over", "description": "Alex de Minaur", "point": 2.5, "price": 175},
        {"name": "Under", "description": "Alex de Minaur", "point": 2.5, "price": -220},
    ]},
]


def test_prop_prices_convert_from_american_without_misreading_decimals():
    assert abs(_price(-110) - 1.90909) < .0001
    assert _price(140) == 2.4
    assert _price(1.85) == 1.85
    assert _price(0) is None
    assert _price(True) is None


def test_event_match_is_exact_unaccented_both_players_and_time():
    assert len(_match_board([MATCH], [PROP], NOW)) == 1
    wrong = {**PROP, "away_team": "Somebody Else"}
    assert _match_board([MATCH], [wrong], NOW) == []
    wrong = {**PROP, "commence_time": (NOW + timedelta(hours=9)).isoformat()}
    assert _match_board([MATCH], [wrong], NOW) == []
    assert _match_board([MATCH], [PROP, PROP], NOW) == _match_board([MATCH], [PROP], NOW)


def test_normalized_complete_book_pairs_for_all_four_markets():
    book = {"key": "draftkings", "markets": PRICE_MARKETS}
    result = _normalize_book(book, MATCH, {"games", "sets", "aces", "double_faults"})
    assert set(result) == {"games", "sets", "aces", "double_faults"}
    assert abs(extract_match_total_odds(result["games"], "games")[0]["over"] - 1.90909) < .0001
    assert extract_match_total_odds(result["sets"], "sets")[0]["under"] == 1.625
    assert extract_player_total_ou(result["aces"], "aces", "Álex de Miñaur")
    assert extract_player_total_ou(result["double_faults"], "double_faults", "Álex de Miñaur")


def test_never_cross_join_two_books_to_fake_an_over_under():
    book1 = {"key": "pinnacle", "markets": [
        {"key": "total_sets", "outcomes": [{"name": "Over", "point": 2.5, "price": 130}]}]}
    book2 = {"key": "bet365", "markets": [
        {"key": "total_sets", "outcomes": [{"name": "Under", "point": 2.5, "price": -150}]}]}
    assert not _normalize_book(book1, MATCH, {"sets"})
    assert not _normalize_book(book2, MATCH, {"sets"})


class FakeProp:
    max_calls = 7
    min_remaining = 205

    def __init__(self):
        self.calls = 0
        self.remaining = 750

    def get(self, path, params=None):
        self.calls += 1
        if path.endswith("/events"):
            return [PROP]
        if path.endswith("/markets"):
            return [{"key": item["key"]} for item in PRICE_MARKETS]
        if path.endswith("/odds"):
            assert "total_games" in params["markets"]
            return {"bookmakers": [{"key": "draftkings", "markets": PRICE_MARKETS}]}
        raise AssertionError(path)


def test_fallback_discovers_and_attaches_real_prices_with_source_provenance():
    client = FakeProp()
    payloads, report = discover_propline_fallback(client, [MATCH], {}, now=NOW, max_events=2)
    assert report["calls"] == client.calls == 3
    assert report["priced_by_market"] == {"aces": 1, "double_faults": 1, "sets": 1, "games": 1}
    assert payloads["rapid-133"]["games"]["bookmaker"] == "draftkings"

    ace = [{
        **MATCH, "market": "aces", "selection_id": "1",
        "projection": 10., "projection_confidence": .8,
    }]
    sg = [{
        **MATCH, "market": "sets", "selection_id": "sets:under:2.5",
        "projection": 2.1, "reference_projection": 2.5,
        "projection_direction": "low",
    }]
    found_ace, found_sg, attach = enrich_projection_odds(
        object(), ace, sg, max_events=2, provider_id=1,
        prefetched_payloads={"rapid-133": None},
        alternate_market_payloads=payloads,
    )
    assert found_ace[0]["price_status"] == "priced_projection"
    assert found_ace[0]["provider_id"] == 2
    assert found_ace[0]["odds_source"] == "propline"
    assert found_ace[0]["odds_bookmaker"] == "draftkings"
    assert found_ace[0]["odds_provider_event_id"] == "1234"
    assert found_sg[0]["odds"] == 1.625
    assert attach["attached_by_provider"]["propline"] == 2


def test_only_fetch_missing_market_and_keep_rapidapi_primary():
    client = FakeProp()
    found, report = discover_propline_fallback(
        client, [MATCH], {"rapid-133": {"games", "sets", "aces"}},
        now=NOW, max_events=2,
    )
    assert set(found["rapid-133"]) == {"double_faults"}
    assert report["priced_by_market"]["games"] == 0
    assert client.calls == 3


def test_zero_budget_does_not_use_propline_event_endpoints():
    client = FakeProp()
    found, report = discover_propline_fallback(client, [MATCH], {},
                                               now=NOW, max_events=0)
    assert not found
    assert client.calls == 1
