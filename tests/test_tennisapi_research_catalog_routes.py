"""Fail-closed, offline contracts for four optional TennisApi research routes.

All tests stub provider traffic: no paid API requests and no canonical CDB writes.
"""
from datetime import date, datetime, timezone

import pytest

from tbt.providers.rapidapi import RapidTennisClient


def research_client():
    client = object.__new__(RapidTennisClient)
    calls = []

    def fake_get(path, *, enrichment=False):
        assert enrichment is True
        calls.append(path)
        return {"witness": path}

    client._get = fake_get
    return client, calls


def test_all_four_research_routes_use_exact_guarded_provider_paths():
    client, calls = research_client()
    assert client.tournament_venue_events(2473, 67391, 29580, 0)["witness"].endswith(
        "/venue/29580/events/all/0")
    assert client.tournament_events_on_date(2473, date(2025, 7, 21))[
        "witness"].endswith("/scheduled-events/2025-07-21")
    assert client.tournaments_by_category(3)["witness"].endswith(
        "/tournament/all/category/3")
    assert client.tournaments_by_category(-100)["witness"].endswith(
        "/tournament/all/category/-100")
    assert client.player_recent_tournaments(14486)["witness"].endswith(
        "/player/14486/tournaments/last")
    assert calls == [
        "/api/tennis/tournament/2473/season/67391/venue/29580/events/all/0",
        "/api/tennis/tournament/2473/scheduled-events/2025-07-21",
        "/api/tennis/tournament/all/category/3",
        "/api/tennis/tournament/all/category/-100",
        "/api/tennis/player/14486/tournaments/last",
    ]


@pytest.mark.parametrize("invalid", [
    None, 0, -1, True, False, 0.5, " ", "01/next", "../etc",
    "3?mode=bad", "-101", "-0100", "1.0",
])
def test_invalid_ids_cannot_reach_provider(invalid):
    client, calls = research_client()
    for op in (
        lambda: client.tournament_venue_events(invalid, 67391, 29580),
        lambda: client.tournament_venue_events(2473, invalid, 29580),
        lambda: client.tournament_venue_events(2473, 67391, invalid),
        lambda: client.tournament_events_on_date(invalid, date(2025, 7, 21)),
        lambda: client.tournaments_by_category(invalid),
        lambda: client.player_recent_tournaments(invalid),
    ):
        with pytest.raises(ValueError):
            op()
    assert calls == []


@pytest.mark.parametrize("page", [
    -1, True, False, None, "1/../../", " 1 ", 1.7,
])
def test_invalid_venue_pages_fail_before_any_request(page):
    client, calls = research_client()
    with pytest.raises(ValueError):
        client.tournament_venue_events(2473, 67391, 29580, page)
    assert calls == []


def test_venue_page_is_explicit_and_zero_based():
    client, calls = research_client()
    client.tournament_venue_events("2473", "67391", "29580", page="2")
    assert calls == [
        "/api/tennis/tournament/2473/season/67391/venue/29580/events/all/2"]


@pytest.mark.parametrize("wrong_day", [
    "2025-07-21", "21/7/2025", None, 20250721,
    datetime(2025, 7, 21, tzinfo=timezone.utc),
])
def test_research_tournament_date_is_explicit_iso_date_only(wrong_day):
    client, calls = research_client()
    with pytest.raises(ValueError, match="scheduled_date"):
        client.tournament_events_on_date(2473, wrong_day)
    assert calls == []


def test_grand_slam_category_exception_is_exact_not_freeform():
    client, calls = research_client()
    client.tournaments_by_category("-100")
    assert calls == ["/api/tennis/tournament/all/category/-100"]
    for invalid in ("-0100", "-200", "--100", "-100/other"):
        with pytest.raises(ValueError):
            client.tournaments_by_category(invalid)
    assert len(calls) == 1
