from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tbt.services.bookmaker_availability import (
    SK_BOOKMAKERS,
    attach_bookmaker_availability,
    canonical_bookmaker,
    load_bookmaker_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)


def _winner_row() -> dict:
    return {
        "event_id": "evt-1",
        "scheduled_at": "2026-09-22T12:00:00+00:00",
        "player1": {"name": "Alpha One"},
        "player2": {"name": "Beta Two"},
        "betting": {"market": "match_winner", "selection": "Alpha One", "odds": 1.62},
        "probability": 0.71,
        "edge": 0.092,
    }


def _df_row() -> dict:
    return {
        "event_id": "evt-df",
        "scheduled_at": "2026-09-22T13:00:00+00:00",
        "player1": {"name": "Gamma Three"},
        "player2": {"name": "Delta Four"},
        "projection_metric": "double_faults",
        "projection_subject": "Gamma Three",
        "selection": "Gamma Three · Over 3.5 Double Faults",
        "line": 3.5,
        "betting": {"market": "double_faults", "selection": "Gamma Three · Over 3.5 Double Faults", "odds": 1.81},
    }


def _offer(bookmaker: str = "Tipsport", **overrides) -> dict:
    data = {
        "bookmaker": bookmaker,
        "event_id": "evt-1",
        "scheduled_at": "2026-09-22T12:00:00+00:00",
        "player1": "Alpha One",
        "player2": "Beta Two",
        "market": "match_winner",
        "selection": "Alpha One",
        "odds": 1.88,
        "captured_at": NOW.isoformat(),
    }
    data.update(overrides)
    return data


def test_all_target_sk_bookies_and_aliases_are_supported():
    assert list(SK_BOOKMAKERS) == ["tipsport", "nike", "fortuna", "doxxbet", "synottip", "tipos", "chance"]
    aliases = {
        "Tipsport.sk": "tipsport",
        "Niké.sk": "nike",
        "iFortuna.sk": "fortuna",
        "DOXXbet.sk": "doxxbet",
        "SYNOT TIP": "synottip",
        "eTipos.sk": "tipos",
        "Chance.sk": "chance",
    }
    for raw, expected in aliases.items():
        assert canonical_bookmaker(raw) == expected


def test_exact_match_winner_offer_adds_badge_without_changing_blinq_odds_or_edge():
    source = {"top_daily_picks": [_winner_row()]}
    original = json.loads(json.dumps(source))
    updated, report = attach_bookmaker_availability(source, [_offer()], snapshot_generated_at=NOW, now=NOW)
    row = updated["top_daily_picks"][0]

    assert row["bookmaker_availability"] == [{
        "bookmaker": "tipsport",
        "label": "Tipsport",
        "short": "T",
        "odds": 1.88,
        "line": None,
        "verified_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(minutes=45)).isoformat(),
        "url": "",
    }]
    assert row["betting"]["odds"] == original["top_daily_picks"][0]["betting"]["odds"] == 1.62
    assert row["edge"] == original["top_daily_picks"][0]["edge"]
    assert source == original  # service returns a deep-copied feed
    assert report["matched_rows"] == 1


def test_multiple_sk_bookies_are_deduplicated_and_ordered_by_registry():
    offers = [_offer("Chance"), _offer("Niké"), _offer("Tipsport"), _offer("Tipsport", odds=1.91)]
    updated, _ = attach_bookmaker_availability({"top_daily_picks": [_winner_row()]}, offers, now=NOW)
    books = [item["bookmaker"] for item in updated["top_daily_picks"][0]["bookmaker_availability"]]
    assert books == ["tipsport", "nike", "chance"]


def test_total_line_mismatch_is_fail_closed():
    row = _winner_row()
    row["projection_metric"] = "games"
    row["selection"] = "Over 20.5 Games"
    row["line"] = 20.5
    row["betting"] = {"market": "games", "selection": "Over 20.5 Games", "odds": 1.77}
    wrong = _offer(market="games", selection="Over 21.5 Games", line=21.5)
    exact = _offer("Fortuna", market="games", selection="Over 20.5 Games", line=20.5)

    updated, report = attach_bookmaker_availability({"value_picks": [row]}, [wrong, exact], now=NOW)
    badges = updated["value_picks"][0]["bookmaker_availability"]
    assert [item["bookmaker"] for item in badges] == ["fortuna"]
    assert badges[0]["line"] == 20.5
    assert report["matched_offers"] == 1


def test_player_prop_requires_same_player_side_and_line():
    wrong_player = _offer(
        event_id="evt-df",
        scheduled_at="2026-09-22T13:00:00+00:00",
        player1="Gamma Three",
        player2="Delta Four",
        market="double faults",
        player="Delta Four",
        selection="Over 3.5",
        line=3.5,
    )
    exact = _offer(
        "DOXXbet",
        event_id="evt-df",
        scheduled_at="2026-09-22T13:00:00+00:00",
        player1="Gamma Three",
        player2="Delta Four",
        market="double faults",
        player="Gamma Three",
        selection="Over 3.5",
        line=3.5,
    )
    updated, _ = attach_bookmaker_availability({"sg_picks": [_df_row()]}, [wrong_player, exact], now=NOW)
    badges = updated["sg_picks"][0]["bookmaker_availability"]
    assert [item["bookmaker"] for item in badges] == ["doxxbet"]


def test_stale_suspended_unknown_and_wrong_event_never_create_badges():
    offers = [
        _offer(captured_at=(NOW - timedelta(hours=2)).isoformat()),
        _offer("Niké", suspended=True),
        _offer("MadeUpBet"),
        _offer("Fortuna", event_id="other-event", player1="Else One", player2="Else Two"),
    ]
    updated, report = attach_bookmaker_availability({"top_daily_picks": [_winner_row()]}, offers, now=NOW, max_age_minutes=45)
    assert "bookmaker_availability" not in updated["top_daily_picks"][0]
    assert report["rejected"]["unknown_bookmaker"] == 1
    assert report["rejected"]["stale_or_inactive"] == 2


def test_optional_snapshot_file_loads_and_missing_source_fails_closed(tmp_path, monkeypatch):
    example = {
        "generated_at": NOW.isoformat(),
        "offers": [_offer("TIPOS")],
    }
    path = tmp_path / "books.json"
    path.write_text(json.dumps(example), encoding="utf-8")
    monkeypatch.setenv("BLINQ_BOOKMAKER_OFFERS_FILE", str(path))
    monkeypatch.delenv("BLINQ_BOOKMAKER_FEED_URL", raising=False)
    offers, generated, report = load_bookmaker_snapshot(ROOT)
    assert len(offers) == 1 and generated == NOW
    assert report == {"enabled": True, "source": "file", "offers": 1, "error": None}

    monkeypatch.setenv("BLINQ_BOOKMAKER_OFFERS_FILE", str(tmp_path / "missing.json"))
    offers, generated, report = load_bookmaker_snapshot(ROOT)
    assert offers == [] and generated is None
    assert report["enabled"] is True and report["error"] == "FileNotFoundError"


def test_frontend_has_all_seven_badges_and_uses_only_verified_annotation():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
    for book in SK_BOOKMAKERS:
        assert f"{book}:" in app
    assert "row.bookmaker_availability" in app
    assert "hub-bookmaker-badge" in app
    assert "hub-bookmaker-badge" in css
    assert "expires_at" in app[app.index("const bookmakerBadgeMeta"):app.index("function hubOddsHtml")]
    assert "provider_id" not in app[app.index("const bookmakerBadgeMeta"):app.index("function hubOddsHtml")]
