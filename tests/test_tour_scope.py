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
    assert called == [3, -100, 6, -100]
    called.clear()
    client.doubles_for_day(day, historical=True)
    assert called == [3, 6, -100]


def test_native_main_category_event_below_tier_is_blocked_even_if_id_is_valid():
    assert not is_250_plus("atp", category_id=3, labels=("ATP", "ATP Challenger"))
    assert not is_250_plus("wta", category_id=6, labels=("WTA", "WTA 125"))
