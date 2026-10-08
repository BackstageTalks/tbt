"""Cached absence of provider tournament logos must not repeatedly burn API quota."""
from datetime import datetime, timedelta, timezone

from scripts.enrich_player_cards import _recently_unavailable_tournament_logo


def test_recent_provider_missing_logo_is_skipped():
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert _recently_unavailable_tournament_logo({
        "logo_status": "unavailable", "logo_checked_at": recent,
    })


def test_old_logo_miss_is_retried():
    old = (datetime.now(timezone.utc) - timedelta(days=32)).isoformat()
    assert not _recently_unavailable_tournament_logo({
        "logo_status": "unavailable", "logo_checked_at": old,
    })


def test_uncertain_and_successful_logo_status_never_suppressed():
    assert not _recently_unavailable_tournament_logo({})
    assert not _recently_unavailable_tournament_logo({"logo_status": "unavailable"})
    assert not _recently_unavailable_tournament_logo({"logo_status": "invalid_media", "logo_checked_at": "2026-10-08T00:00:00Z"})
    assert not _recently_unavailable_tournament_logo({"logo_status": "available", "logo_checked_at": "2026-10-08T00:00:00Z"})
    assert not _recently_unavailable_tournament_logo({"logo_status": "unavailable", "logo_checked_at": "invalid"})
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert not _recently_unavailable_tournament_logo({"logo_status": "unavailable", "logo_checked_at": future})
