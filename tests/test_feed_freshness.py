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


def test_all_public_tabs_enforce_actual_0600_to_0600_schedule_not_label():
    # At 18 Oct 10:00 CEST, the current public offer is 18 Oct 06:00
    # through 19 Oct 05:59:59.999999 (exclusive next-day 06:00).
    now = datetime.fromisoformat("2026-10-18T08:00:00+00:00")
    rows = [
        {"event_id": "today-start", "scheduled_at": "2026-10-18T04:00:00Z"},
        {"event_id": "today-afternoon", "scheduled_at": "2026-10-18T12:00:00Z"},
        {"event_id": "tomorrow-early", "scheduled_at": "2026-10-19T03:59:59Z"},
        {"event_id": "tomorrow-boundary", "scheduled_at": "2026-10-19T04:00:00Z",
         "betting_day": "2026-10-18"},
        {"event_id": "tomorrow-day", "scheduled_at": "2026-10-19T09:00:00Z",
         "betting_day": "2026-10-18"},
        {"event_id": "yesterday-late", "scheduled_at": "2026-10-18T03:59:59Z",
         "betting_day": "2026-10-18"},
        {"event_id": "bad-schedule", "scheduled_at": "unknown", "betting_day": "2026-10-18"},
        {"event_id": "missing-schedule", "betting_day": "2026-10-18"},
    ]
    payload = {"generated_at": "2026-10-18T04:10:00Z", "upcoming": [], "results": []}
    payload.update({tab: list(rows) for tab in PUBLIC_TABS})

    visible = visible_feed(payload, now=now)
    for tab in PUBLIC_TABS:
        assert [row["event_id"] for row in visible[tab]] == [
            "today-start", "today-afternoon", "tomorrow-early"
        ], tab
        assert len(payload[tab]) == len(rows), "The archived feed cannot be mutated."
    assert visible["daily_offer_day"] == "2026-10-18"
    assert visible["stale"] is False


def test_public_offer_rolls_at_exact_0600_local_boundary():
    # 2026-10-19 05:59:59 CEST is 03:59:59 UTC.
    rows = [
        {"event_id": "old-final-second", "scheduled_at": "2026-10-19T03:59:59Z"},
        {"event_id": "new-exact-six", "scheduled_at": "2026-10-19T04:00:00Z"},
    ]
    payload = {"generated_at": "2026-10-18T04:10:00Z",
               "upcoming": [], "results": [], "top_daily_picks": rows}
    just_before = visible_feed(payload, now=datetime.fromisoformat("2026-10-19T03:59:59+00:00"))
    at_six = visible_feed(payload, now=datetime.fromisoformat("2026-10-19T04:00:00+00:00"))
    assert [row["event_id"] for row in just_before["top_daily_picks"]] == ["old-final-second"]
    assert [row["event_id"] for row in at_six["top_daily_picks"]] == ["new-exact-six"]
    assert just_before["daily_offer_day"] == "2026-10-18"
    assert at_six["daily_offer_day"] == "2026-10-19"


def test_public_offer_winter_cet_boundary_has_exact_start():
    rows = [
        {"event_id": "old", "scheduled_at": "2026-12-02T04:59:59Z"},
        {"event_id": "new", "scheduled_at": "2026-12-02T05:00:00Z"},
    ]
    payload = {"upcoming": [], "results": [], "top_daily_picks": rows}
    visible = visible_feed(payload, now=datetime.fromisoformat("2026-12-02T05:00:00+00:00"))
    assert [row["event_id"] for row in visible["top_daily_picks"]] == ["new"]
