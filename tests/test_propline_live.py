from datetime import datetime, timedelta, timezone

from tbt.services.propline_live import (
    PropLineClient, _match_board, _normalize_book, _price,
    discover_propline_fallback,
)
from tbt.services.market_selection import extract_match_winner_odds
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
    {"key": "h2h", "outcomes": [
        {"name": "Álex de Miñaur", "price": -125},
        {"name": "Jan-Lennard Struff", "price": 115},
    ]},
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


def test_normalized_complete_book_pairs_for_all_supported_markets():
    book = {"key": "draftkings", "markets": PRICE_MARKETS}
    result = _normalize_book(
        book, MATCH, {"match_winner", "games", "sets", "aces", "double_faults"}
    )
    assert set(result) == {"match_winner", "games", "sets", "aces", "double_faults"}
    winner = extract_match_winner_odds(
        result["match_winner"], "Álex de Miñaur", "Jan-Lennard Struff"
    )
    assert winner is not None
    assert winner["player1_odds"] == 1.8
    assert winner["player2_odds"] == 2.15
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
            assert any(key in params["markets"] for key in ("total_games", "player_double_faults"))
            return {"bookmakers": [{"key": "draftkings", "markets": PRICE_MARKETS}]}
        raise AssertionError(path)


def test_fallback_discovers_and_attaches_real_prices_with_source_provenance():
    client = FakeProp()
    payloads, report = discover_propline_fallback(client, [MATCH], {}, now=NOW, max_events=2)
    assert report["calls"] == client.calls == 3
    assert report["priced_by_market"] == {
        "match_winner": 1, "aces": 1, "double_faults": 1, "sets": 1, "games": 1
    }
    assert payloads["rapid-133"]["match_winner"]["bookmaker"] == "draftkings"
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
    assert found_ace[0]["odds_contract_version"] == "ace_df_real_api_v1"
    assert found_sg[0]["odds"] == 1.625
    assert attach["attached_by_provider"]["propline"] == 2


def test_only_fetch_missing_market_and_keep_rapidapi_primary():
    client = FakeProp()
    found, report = discover_propline_fallback(
        client, [MATCH], {"rapid-133": {"match_winner", "games", "sets", "aces"}},
        now=NOW, max_events=2,
    )
    assert set(found["rapid-133"]) == {"double_faults"}
    assert report["priced_by_market"]["match_winner"] == 0
    assert report["priced_by_market"]["games"] == 0
    assert client.calls == 3


def test_zero_budget_does_not_use_propline_event_endpoints():
    client = FakeProp()
    found, report = discover_propline_fallback(client, [MATCH], {},
                                               now=NOW, max_events=0)
    assert not found
    assert client.calls == 1


def test_wide_market_discovery_reports_advertised_versus_genuine_two_sided_quotes():
    from tbt.services.propline_live import MAX_EVENTS_PER_REFRESH, MIN_PROVIDER_REMAINING
    assert MAX_EVENTS_PER_REFRESH == -1
    assert MIN_PROVIDER_REMAINING == 150
    client = FakeProp()
    found, audit = discover_propline_fallback(client, [MATCH], {},
                                               now=NOW, max_events=75)
    assert audit["events_on_board"] == 1
    assert audit["matched_events"] == 1
    assert audit["events_limited_out"] == 0
    assert audit["events_with_any_target_market"] == 1
    assert audit["events_skipped_no_target_market"] == 0
    assert audit["odds_payload_events"] == 1
    assert audit["markets_advertised_by_type"] == {
        "match_winner": 1, "aces": 1, "double_faults": 1, "games": 1, "sets": 1
    }
    assert audit["bookmakers_priced_by_market"]["match_winner"]["draftkings"] == 1
    assert audit["bookmakers_priced_by_market"]["aces"]["draftkings"] == 1
    assert audit["sample_offers"]["games"][0]["line"] == 22.5
    assert abs(audit["sample_offers"]["games"][0]["over"] - 1.90909) < .0001
    assert audit["sample_offers"]["aces"][0]["player"] == "Álex de Miñaur"
    assert set(found["rapid-133"]) == {
        "match_winner", "aces", "double_faults", "games", "sets"
    }


def test_shared_free_tier_quota_budget_and_active_clv_defaults():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    refresh = (root / ".github/workflows/data.yml").read_text(encoding="utf-8")
    clv = (root / "scripts/propline_clv_collect.py").read_text(encoding="utf-8")
    active_workflow = (root / ".github/workflows/propline-clv-pilot.yml").read_text(encoding="utf-8")
    assert "default: -1" in refresh
    assert "DAILY_LIMIT = 250" in clv
    assert "MIN_PROVIDER_REMAINING = 150" in clv
    assert "propline_clv_collect.py" in active_workflow
    assert "workflow_dispatch:" in active_workflow
    assert "  schedule:" not in active_workflow


def test_propline_abbreviated_names_match_both_players_without_spending_api():
    from tbt.services.propline_live import _match_board_with_diagnostics
    short = {**PROP, "home_team": "J. Struff", "away_team": "A. de Minaur"}
    pairs, report = _match_board_with_diagnostics([MATCH], [short], NOW)
    assert len(pairs) == 1
    assert report["matched_exact"] == 0
    assert report["matched_abbreviated"] == 1
    assert report["ambiguous_rejected"] == 0


def test_abbreviated_names_fail_closed_on_shared_initial_surname_or_time():
    from tbt.services.propline_live import _match_board_with_diagnostics
    other = {**MATCH, "event_id": "other-9", "player1": {"name": "Anna de Minaur"}}
    short = {**PROP, "home_team": "J. Struff", "away_team": "A. de Minaur"}
    found, report = _match_board_with_diagnostics([MATCH, other], [short], NOW)
    assert not found
    assert report["ambiguous_rejected"] == 1
    later = {**short, "commence_time": (NOW + timedelta(hours=8)).isoformat()}
    assert not _match_board([MATCH], [later], NOW)
    one_player_wrong = {**short, "home_team": "J. Someone"}
    assert not _match_board([MATCH], [one_player_wrong], NOW)


def test_conflicting_prop_fixture_identity_and_identical_duplicate_handling():
    from tbt.services.propline_live import _match_board_with_diagnostics
    found, _ = _match_board_with_diagnostics([MATCH], [PROP, PROP], NOW)
    assert len(found) == 1
    conflicting = {**PROP, "id": "5678"}
    found, report = _match_board_with_diagnostics([MATCH], [PROP, conflicting], NOW)
    assert not found
    assert report["ambiguous_rejected"] == 2


def test_match_winner_h2h_is_not_returned_when_primary_already_has_price():
    client = FakeProp()
    found, report = discover_propline_fallback(
        client, [MATCH], {"rapid-133": {"match_winner"}},
        now=NOW, max_events=2,
    )
    assert "match_winner" not in found["rapid-133"]
    assert report["priced_by_market"]["match_winner"] == 0
    assert set(found["rapid-133"]) == {"aces", "double_faults", "games", "sets"}



def test_unlimited_propline_fallback_checks_all_eligible_events_not_first_75():
    """No artificial fixture cap: only provider quota may stop discovery."""
    fixtures = []
    board = []
    for i in range(82):
        fixtures.append({
            "event_id": f"rapid-{i}", "scheduled_at": START, "tour": "ATP",
            "player1": {"id": f"p{i}", "name": f"First Player{i:03d}"},
            "player2": {"id": f"q{i}", "name": f"Second Opponent{i:03d}"},
        })
        board.append({
            "id": str(1000 + i), "home_team": f"First Player{i:03d}",
            "away_team": f"Second Opponent{i:03d}", "commence_time": START,
        })

    class LargeBoard:
        max_calls = 1000
        min_remaining = 150
        remaining = 800

        def __init__(self):
            self.calls = 0

        def get(self, path, params=None):
            self.calls += 1
            if path == "/sports/tennis/events":
                return board
            if path.endswith("/markets"):
                return [{"key": "h2h"}]
            if path.endswith("/odds"):
                eid = int(path.split("/")[-2]) - 1000
                return {"bookmakers": [{
                    "key": "test-book",
                    "markets": [{"key": "h2h", "outcomes": [
                        {"name": f"First Player{eid:03d}", "price": -120},
                        {"name": f"Second Opponent{eid:03d}", "price": 110},
                    ]}],
                }]}
            raise AssertionError(path)

    client = LargeBoard()
    found, report = discover_propline_fallback(
        client, fixtures, {}, now=NOW, max_events=-1,
    )
    assert report["matched_events"] == 82
    assert report["events_limited_out"] == 0
    assert report["priced_by_market"]["match_winner"] == 82
    assert len(found) == 82
    assert client.calls == 165


def test_propline_client_does_not_spend_a_known_final_reserve_call():
    from tbt.services.propline_live import MIN_PROVIDER_REMAINING
    import pytest

    client = PropLineClient("placeholder", max_calls=1000)
    client.remaining = MIN_PROVIDER_REMAINING
    with pytest.raises(RuntimeError, match="reserve"):
        client.get("/sports/tennis/events")
    assert client.calls == 0


def test_primary_ace_df_markets_are_not_deleted_before_fallback():
    from pathlib import Path
    pipeline = (Path(__file__).resolve().parents[1] / "scripts/pipeline.py").read_text()
    assert '"rapidapi_first_propline_fallback"' in pipeline
    assert "ignored_rapid_ace_df" not in pipeline
    assert "propline_only_v1" not in pipeline



def test_doubles_fallback_requires_full_team_identity_and_complete_h2h():
    from tbt.services.market_selection import attach_match_winner_market
    from tbt.services.propline_live import _match_board_with_diagnostics

    first = "Jamie Murray / Bruno Soares"
    second = "Rajeev Ram / Joe Salisbury"
    doubles = {
        "event_id": "doubles-001", "prediction_family": "doubles",
        "scheduled_at": START, "tour": "ATP", "winner_id": "team1",
        "data_depth": 0.9,
        "player1": {"id": "team1", "name": first, "probability": 0.81},
        "player2": {"id": "team2", "name": second, "probability": 0.19},
    }
    event = {"id": "24680", "home_team": first, "away_team": second,
             "commence_time": START}
    matches, _ = _match_board_with_diagnostics([doubles], [event], NOW)
    assert len(matches) == 1
    ambiguous_short = {**event, "home_team": "J. Soares",
                       "away_team": "R. Salisbury"}
    matches, _ = _match_board_with_diagnostics([doubles], [ambiguous_short], NOW)
    assert matches == []

    class Book:
        calls = 0
        max_calls = 9
        remaining = 600
        min_remaining = 150

        def get(self, path, params=None):
            self.calls += 1
            if path.endswith("/events"):
                return [event]
            if path.endswith("/markets"):
                return [{"key": "h2h"}]
            if path.endswith("/odds"):
                assert params["markets"] == "h2h"
                return {"bookmakers": [{
                    "key": "test-book", "markets": [
                        {"key": "h2h", "outcomes": [
                            {"name": first, "price": -120},
                            {"name": second, "price": 110},
                        ]}
                    ],
                }]}
            raise AssertionError(path)

    quote, audit = discover_propline_fallback(
        Book(), [doubles],
        {"doubles-001": {"aces", "double_faults", "games", "sets"}},
        now=NOW, max_events=-1,
    )
    assert audit["priced_by_market"]["match_winner"] == 1
    market = extract_match_winner_odds(
        quote["doubles-001"]["match_winner"]["payload"], first, second)
    enriched = attach_match_winner_market(
        doubles, market, captured_at=NOW, provider_id=2)
    assert enriched["betting"]["market"] == "match_winner"
    assert enriched["betting"]["provider_id"] == 2
    assert enriched["betting"]["odds"] > 1.5
