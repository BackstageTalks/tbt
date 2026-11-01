from __future__ import annotations

from datetime import datetime, timedelta, timezone

import enrich_player_cards as enrichment


def test_ranking_row_parses_team_country_and_rank():
    row = {
        "team": {
            "id": 69208,
            "name": "Jasmine Paolini",
            "shortName": "J. Paolini",
            "country": {
                "alpha2": "IT",
                "alpha3": "ITA",
                "name": "Italy",
            },
        },
        "ranking": 21,
        "points": 2123,
        "previousRanking": 20,
        "bestRanking": 4,
    }
    profile = enrichment.profile_from_ranking_row(row, tour="wta")
    assert profile == {
        "id": "69208",
        "name": "Jasmine Paolini",
        "rank": 21,
        "previous_rank": 20,
        "best_rank": 4,
        "ranking_points": 2123,
        "country_code": "IT",
        "country_code3": "ITA",
        "country_name": "Italy",
        "tour": "WTA",
    }


def test_player_specific_ranking_can_use_known_id_when_history_row_omits_id():
    row = {
        "ranking": 21,
        "country": {"alpha2": "IT", "name": "Italy"},
    }
    profile = enrichment.profile_from_ranking_row(
        row, tour="wta", assumed_player_id="69208"
    )
    assert profile["id"] == "69208"
    assert profile["rank"] == 21
    assert profile["country_code"] == "IT"


def test_photo_extension_detects_provider_image_bytes():
    assert enrichment._photo_extension(b"\x89PNG\r\n\x1a\nrest", "image/png") == "png"
    assert enrichment._photo_extension(b"\xff\xd8\xffrest", "image/jpeg") == "jpg"
    assert enrichment._photo_extension(b"RIFFxxxxWEBPrest", "image/webp") == "webp"
    assert enrichment._photo_extension(b"not-an-image", "text/plain") is None


def test_current_players_are_unique_and_prioritised_by_confidence():
    feed = {
        "upcoming": [
            {
                "tour": "ATP",
                "confidence": 0.71,
                "player1": {"id": "10", "name": "Alpha"},
                "player2": {"id": "20", "name": "Beta"},
            },
            {
                "tour": "ATP",
                "confidence": 0.95,
                "player1": {"id": "10", "name": "Alpha"},
                "player2": {"id": "30", "name": "Gamma"},
            },
        ]
    }
    players = enrichment._current_players(feed)
    assert [row["id"] for row in players] == ["10", "30", "20"]
    assert players[0]["priority"] == 0.95


def test_player_details_complete_does_not_need_repeat_api_fetch():
    profile = {
        "birth_date": "1999-01-01", "height_cm": 185, "hand": "R",
        "birthplace": "City A", "residence": "City B", "country_code": "SK",
    }
    assert enrichment._player_details_complete(profile)
    assert not enrichment._player_details_complete({**profile, "hand": None})


def test_optional_player_details_cooldown_does_not_hide_future_or_stale_gaps():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    profile = {"player_detail_checked_at": (now - timedelta(days=1)).isoformat()}
    assert enrichment._recently_checked_player_details(profile, now=now)
    assert not enrichment._recently_checked_player_details(
        {"player_detail_checked_at": (now - timedelta(days=8)).isoformat()}, now=now
    )
    assert not enrichment._recently_checked_player_details(
        {"player_detail_checked_at": (now + timedelta(minutes=1)).isoformat()}, now=now
    )
    assert not enrichment._recently_checked_player_details(
        {"player_detail_checked_at": "invalid"}, now=now
    )
    assert not enrichment._recently_checked_player_details(
        {"player_detail_checked_at": "2026-11-01T10:00:00"}, now=now
    )
    assert not enrichment._recently_checked_player_details({}, now=now)


def test_missing_player_ranking_fallback_retries_after_one_day():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    stamp = {"ranking_fallback_checked_at": (now - timedelta(hours=6)).isoformat()}
    assert enrichment._recently_checked_player_rankings(stamp, now=now)
    assert not enrichment._recently_checked_player_rankings(
        {"ranking_fallback_checked_at": (now - timedelta(days=2)).isoformat()}, now=now
    )
    assert not enrichment._recently_checked_player_rankings(
        {"ranking_fallback_checked_at": (now + timedelta(minutes=1)).isoformat()}, now=now
    )
    assert not enrichment._recently_checked_player_rankings(
        {"ranking_fallback_checked_at": "bad"}, now=now
    )
    assert not enrichment._recently_checked_player_rankings({}, now=now)
