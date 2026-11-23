from datetime import date
from types import SimpleNamespace

import pytest

from tbt.tour_scope import is_250_plus, match_is_250_plus
from tbt.providers.rapidapi import RapidTennisClient


@pytest.mark.parametrize(("tour", "category", "label", "expected"), [
    ("atp", 3, "ATP", True),
    ("wta", 6, "WTA", True),
    ("atp", -100, "Wimbledon", True),
    ("wta", -100, "Roland Garros", True),
    ("atp", 72, "ATP Challenger", False),
    ("wta", 871, "WTA 125", False),
    ("atp", 785, "ITF Men", False),
    ("wta", 213, "ITF Women", False),
    ("atp", 3, "ATP Challenger 100", False),
    ("wta", 6, "WTA 125", False),
    ("atp", 3, "ATP 125", False),
    ("wta", 6, "Wimbledon Juniors", False),
    ("atp", 6, "ATP", False),
    ("wta", 3, "WTA", False),
    ("wta", None, "WTA 250", True),
    ("atp", None, "ATP 500", True),
    ("wta", None, "WTA 1000", True),
    ("atp", None, "Grand Slam", True),
    ("wta", None, "WTA", False),
    ("atp", None, "ATP", False),
    ("atp", None, "Challenger ATP 250", False),
    ("itf", 3, "ATP 250", False),
])
def test_paid_scope(tour, category, label, expected):
    assert is_250_plus(tour, category_id=category, labels=(label,)) is expected


def test_match_scope_uses_cdb_native_source_without_mutation():
    row = SimpleNamespace(
        tour="wta", tournament="Open", tournament_level="WTA",
        provider_payload={"_tbt_source_category_id": 871, "_tbt_source_category_name": "WTA 125"},
    )
    original = dict(row.provider_payload)
    assert not match_is_250_plus(row)
    row.provider_payload = {"_tbt_source_category_id": 6, "_tbt_source_category_name": "WTA"}
    assert match_is_250_plus(row)
    row.provider_payload = original
    assert row.provider_payload == original


def test_daily_provider_does_not_pay_to_open_lower_categories():
    client = object.__new__(RapidTennisClient)
    called = []
    categories = [
        {"id": 72, "name": "ATP Challenger"},
        {"id": 213, "name": "ITF Women"},
        {"id": 785, "name": "ITF Men"},
        {"id": 871, "name": "WTA 125"},
        {"id": 3, "name": "ATP"},
        {"id": 6, "name": "WTA"},
        {"id": -100, "name": "Grand Slam"},
    ]
    client.calendar_categories = lambda day: categories
    client.category_events = lambda category, day: called.append(category) or []
    day = date(2026, 11, 21)
    client.matches_for_day("atp", day, historical=True)
    client.matches_for_day("wta", day, historical=True)
    # Native historical calendar and CDB ingest remain 250+ only.
    assert called == [3, -100, 6, -100]
    called.clear()
    client.doubles_for_day(day, historical=True)
    assert called == [3, 6, -100]


def test_native_main_category_event_below_tier_is_blocked_even_if_id_is_valid():
    assert not is_250_plus("atp", category_id=3, labels=("ATP", "ATP Challenger"))
    assert not is_250_plus("wta", category_id=6, labels=("WTA", "WTA 125"))


@pytest.mark.parametrize(("tour", "category", "label", "expected"), [
    ("atp", 3, "ATP 250", True),
    ("wta", 6, "WTA 1000", True),
    ("atp", 72, "ATP Challenger", True),
    ("atp", 72, "ATP Challenger 50", True),
    ("atp", 72, "ATP Challenger 75", True),
    ("atp", 72, "ATP Challenger 100", True),
    ("atp", 72, "ATP Challenger 125", True),
    ("atp", 72, "ATP Challenger 175", True),
    ("wta", 871, "WTA 125", True),
    ("atp", None, "Davis Cup World Group", True),
    ("wta", None, "Billie Jean King Cup World Group", True),
    ("wta", None, "Fed Cup", True),
    ("atp", None, "Billie Jean King Cup", False),
    ("wta", None, "Davis Cup", False),
    ("atp", 72, "ITF Challenger 100", False),
    ("atp", 785, "ITF Men", True),
    ("wta", 213, "ITF Women", True),
    ("atp", 72, "Challenger Juniors", False),
    ("atp", None, "UTR", False),
    ("atp", None, "Unknown tournament", False),
])
def test_match_winner_extended_scope_only(tour, category, label, expected):
    from tbt.tour_scope import is_match_winner_offer_scope
    assert is_match_winner_offer_scope(tour, category_id=category, labels=(label,)) is expected


def test_extended_discovery_visits_approved_categories_without_lower_doubles():
    client = object.__new__(RapidTennisClient)
    called = []
    categories = [
        {"id": 72, "name": "ATP Challenger"},
        {"id": 871, "name": "WTA 125"},
        {"id": 82001, "name": "Davis Cup World Group"},
        {"id": 82002, "name": "Billie Jean King Cup World Group"},
        {"id": 785, "name": "ITF Men"},
        {"id": 213, "name": "ITF Women"},
    ]
    client.calendar_categories = lambda day: categories
    client.category_events = lambda category, day: called.append(category) or []
    day = date(2026, 11, 22)
    client.matches_for_day("atp", day, historical=False)
    client.matches_for_day("wta", day, historical=False)
    assert called == [72, 82001, 785, 871, 82002, 213]
    called.clear()
    client.doubles_for_day(day, historical=False)
    assert called == []


def test_cup_event_tour_requires_explicit_competition_and_singles():
    assert RapidTennisClient._event_tour(
        {"name": "Davis Cup World Group", "homeTeam": {"id": 1}, "awayTeam": {"id": 2}},
        82001, "Davis Cup World Group") == "atp"
    assert RapidTennisClient._event_tour(
        {"name": "Billie Jean King Cup", "homeTeam": {"id": 1}, "awayTeam": {"id": 2}},
        82002, "Billie Jean King Cup") == "wta"
    assert RapidTennisClient._is_singles_event({
        "name": "Billie Jean King Cup Doubles",
        "homeTeam": {"id": 1}, "awayTeam": {"id": 2},
    }) is False


def test_historical_scope_does_not_expand_into_challenger_wta125_or_cups():
    client = object.__new__(RapidTennisClient)
    visited = []
    categories = [
        {"id": 72, "name": "ATP Challenger"},
        {"id": 871, "name": "WTA 125"},
        {"id": 82001, "name": "Davis Cup World Group"},
        {"id": 82002, "name": "Billie Jean King Cup World Group"},
        {"id": 3, "name": "ATP"},
        {"id": 6, "name": "WTA"},
    ]
    client.calendar_categories = lambda day: categories
    client.category_events = lambda category, day: visited.append(category) or []
    day = date(2026, 11, 22)
    client.matches_for_day("atp", day, historical=True)
    client.matches_for_day("wta", day, historical=True)
    assert visited == [3, 6]
    visited.clear()
    client.matches_for_day("atp", day, historical=False)
    client.matches_for_day("wta", day, historical=False)
    assert visited == [72, 82001, 3, 871, 82002, 6]


@pytest.mark.parametrize(("tour", "category", "label", "event", "ok"), [
    ("atp", 785, "ITF Men", "ITF M15 Monastir", True),
    ("atp", 785, "ITF Men", "ITF M25", True),
    ("atp", 785, "ITF Men", "ITF M50", False),
    ("atp", 785, "ITF Men", "ITF M150", False),
    ("wta", 213, "ITF Women", "ITF W15 Antalya", True),
    ("wta", 213, "ITF Women", "ITF W35", True),
    ("wta", 213, "ITF Women", "ITF W100", True),
    ("atp", 785, "ITF Men", "ITF M10", False),
    ("wta", 213, "ITF Women", "ITF W10", False),
    ("atp", 785, "ITF Men", "ITF W15", False),
    ("wta", 213, "ITF Women", "ITF M15", False),
    ("atp", 213, "ITF Women", "ITF W15", False),
    ("wta", 785, "ITF Men", "ITF M15", False),
    ("atp", 785, "ITF Men", "ITF M15 Juniors", False),
    ("wta", 213, "ITF Women", "ITF W15 Doubles", False),
    ("atp", 785, "ITF Men", "Generic ITF", False),
])
def test_itf_requires_native_category_and_explicit_eligible_event_grade(tour, category, label, event, ok):
    from tbt.tour_scope import is_match_winner_offer_scope
    assert is_match_winner_offer_scope(tour, category_id=category, labels=(label, event), event_level=True) is ok
    assert not is_250_plus(tour, category_id=category, labels=(label, event))


def test_itf_prospective_grade_survives_provider_normalization():
    client = object.__new__(RapidTennisClient)
    client.calendar_categories = lambda day: [{"id": 785, "name": "ITF Men"}]
    raw = {
        "id": 998877, "name": "M15 Monastir Singles",
        "homeTeam": {"id": 1001, "name": "Alpha"},
        "awayTeam": {"id": 1002, "name": "Beta"},
        "startTimestamp": 1795358400,
        "tournament": {"id": 11, "name": "Monastir", "rank": {"name": "M15"}},
    }
    client.category_events = lambda category, day: [raw]
    matches = client.matches_for_day("atp", date(2026, 11, 22), historical=False)
    assert len(matches) == 1
    assert matches[0].tournament_level == "ITF M15"
    assert matches[0].provider_payload["_tbt_source_category_id"] == 785
    assert client.doubles_for_day(date(2026, 11, 22), historical=False) == []
