"""Regression guards for the daily serving snapshot's 06:00 Bratislava boundary."""
from datetime import datetime

from tbt.services.feed import visible_feed


def _stale(generated_at, now):
    stamp = datetime.fromisoformat(now.replace("Z", "+00:00"))
    return visible_feed({"generated_at": generated_at, "upcoming": [], "results": []}, now=stamp)["stale"]


def test_morning_feed_remains_fresh_during_evening():
    # 04:10Z = 06:10 Europe/Bratislava in October.
    assert _stale("2026-10-08T04:10:47Z", "2026-10-08T17:52:00Z") is False


def test_morning_feed_goes_stale_at_next_betting_day():
    assert _stale("2026-10-08T04:10:47Z", "2026-10-09T03:59:00Z") is False
    assert _stale("2026-10-08T04:10:47Z", "2026-10-09T04:01:00Z") is True


def test_just_before_morning_boundary_is_previous_day():
    assert _stale("2026-10-08T03:59:00Z", "2026-10-08T04:01:00Z") is True


def test_winter_betting_day_uses_cet_offset():
    assert _stale("2026-12-01T05:05:00Z", "2026-12-01T22:59:00Z") is False
    assert _stale("2026-12-01T05:05:00Z", "2026-12-02T05:01:00Z") is True


def test_missing_or_implausibly_future_dated_feed_is_stale():
    assert _stale(None, "2026-10-08T12:00:00Z") is True
    assert _stale("2026-10-08T14:00:00Z", "2026-10-08T12:00:00Z") is True


def test_retired_top200_is_never_served_even_from_legacy_snapshot():
    now = datetime.fromisoformat("2026-10-09T09:00:00+00:00")
    historical = {"event_id": "old-legacy", "market_publications": [{"section": "top200"}]}
    payload = {
        "generated_at": "2026-10-09T04:10:00Z",
        "upcoming": [],
        "results": [historical],
        "top200_picks": [{"event_id": "obsolete", "betting_day": "2026-10-09"}],
        "top_daily_picks": [{"event_id": "current", "betting_day": "2026-10-09", "scheduled_at": "2026-10-09T12:00:00Z"}],
    }
    visible = visible_feed(payload, now=now)
    assert visible["top200_picks"] == []
    assert [row["event_id"] for row in visible["top_daily_picks"]] == ["current"]
    assert visible["results"] == [historical]
    assert payload["top200_picks"][0]["event_id"] == "obsolete"  # Input not mutated.


PUBLIC_TABS = ("top_daily_picks", "prime_picks", "value_picks",
               "doubles_picks", "ace_picks", "sg_picks")


def test_public_tabs_exclude_tomorrows_0430_and_0500_matches():
    # Screenshot reproduction: 18 Oct 10:00 CEST. Internal day ends at
    # 19 Oct 06:00, but the public board shows 18 Oct fixtures only.
    now = datetime.fromisoformat("2026-10-18T08:00:00+00:00")
    rows = [
        {"event_id": "today-start-0600", "scheduled_at": "2026-10-18T04:00:00Z"},
        {"event_id": "today-afternoon", "scheduled_at": "2026-10-18T12:00:00Z"},
        {"event_id": "today-last-second", "scheduled_at": "2026-10-18T21:59:59Z"},
        {"event_id": "tomorrow-midnight", "scheduled_at": "2026-10-18T22:00:00Z"},
        {"event_id": "tomorrow-osaka-0430", "scheduled_at": "2026-10-19T02:30:00Z"},
        {"event_id": "tomorrow-guangzhou-0500", "scheduled_at": "2026-10-19T03:00:00Z"},
        {"event_id": "tomorrow-0559", "scheduled_at": "2026-10-19T03:59:59Z"},
        {"event_id": "tomorrow-exact-0600", "scheduled_at": "2026-10-19T04:00:00Z",
         "betting_day": "2026-10-18"},
        {"event_id": "tomorrow-1100", "scheduled_at": "2026-10-19T09:00:00Z",
         "betting_day": "2026-10-18"},
        {"event_id": "today-before-0600", "scheduled_at": "2026-10-18T03:59:59Z",
         "betting_day": "2026-10-18"},
        {"event_id": "bad-schedule", "scheduled_at": "unknown", "betting_day": "2026-10-18"},
        {"event_id": "missing-schedule", "betting_day": "2026-10-18"},
    ]
    payload = {"generated_at": "2026-10-18T04:10:00Z", "upcoming": [], "results": []}
    payload.update({tab: list(rows) for tab in PUBLIC_TABS})

    visible = visible_feed(payload, now=now)
    for tab in PUBLIC_TABS:
        assert [row["event_id"] for row in visible[tab]] == [
            "today-start-0600", "today-afternoon", "today-last-second"
        ], tab
        assert len(payload[tab]) == len(rows), "Raw published offer must not be mutated."
    assert visible["daily_offer_day"] == "2026-10-18"
    assert visible["stale"] is False


def test_public_day_rolls_at_exact_0600_local_not_midnight():
    # Internal day 18 Oct continues until 19 Oct 05:59:59, but tomorrow's
    # 05:59 fixture is not rendered on today's public board.
    rows = [
        {"event_id": "old-day-evening", "scheduled_at": "2026-10-18T21:59:59Z"},
        {"event_id": "next-date-before-six", "scheduled_at": "2026-10-19T03:59:59Z"},
        {"event_id": "new-day-exact-six", "scheduled_at": "2026-10-19T04:00:00Z"},
    ]
    payload = {"generated_at": "2026-10-18T04:10:00Z",
               "upcoming": [], "results": [], "top_daily_picks": rows}
    before_midnight = visible_feed(payload, now=datetime.fromisoformat("2026-10-18T21:59:59+00:00"))
    before_six = visible_feed(payload, now=datetime.fromisoformat("2026-10-19T03:59:59+00:00"))
    at_six = visible_feed(payload, now=datetime.fromisoformat("2026-10-19T04:00:00+00:00"))
    assert [row["event_id"] for row in before_midnight["top_daily_picks"]] == ["old-day-evening"]
    assert [row["event_id"] for row in before_six["top_daily_picks"]] == ["old-day-evening"]
    assert [row["event_id"] for row in at_six["top_daily_picks"]] == ["new-day-exact-six"]
    assert before_six["daily_offer_day"] == "2026-10-18"
    assert at_six["daily_offer_day"] == "2026-10-19"


def test_discovery_and_results_are_not_purged_by_public_board_filter():
    tomorrow = {"event_id": "discovery", "scheduled_at": "2026-10-19T03:00:00Z"}
    result = {"event_id": "historical", "result": {"winner_id": "p1"}}
    payload = {
        "upcoming": [tomorrow], "results": [result],
        "top_daily_picks": [tomorrow],
    }
    viewed = visible_feed(payload, now=datetime.fromisoformat("2026-10-18T08:00:00+00:00"))
    assert viewed["top_daily_picks"] == []
    assert viewed["upcoming"] == [tomorrow]  # Internal discovery preserved.
    assert viewed["results"] == [result]  # Results not affected.
    assert payload["top_daily_picks"] == [tomorrow]  # Published raw data kept.


def test_public_offer_winter_cet_boundary_has_exact_start():
    rows = [
        {"event_id": "old", "scheduled_at": "2026-12-02T04:59:59Z"},
        {"event_id": "new", "scheduled_at": "2026-12-02T05:00:00Z"},
    ]
    payload = {"upcoming": [], "results": [], "top_daily_picks": rows}
    visible = visible_feed(payload, now=datetime.fromisoformat("2026-12-02T05:00:00+00:00"))
    assert [row["event_id"] for row in visible["top_daily_picks"]] == ["new"]
