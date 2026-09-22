from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from tbt.services.feed import visible_feed
from tbt.services.publication import build_daily_offer_snapshot, carry_forward_betting_day_market_rows

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def winner_row(event: str, when: str, *, selection: str, odds: float, day: str = "2026-09-21") -> dict:
    return {
        "event_id": event,
        "scheduled_at": when,
        "market": "match_winner",
        "selection": selection,
        "odds": odds,
        "betting_day": day,
        "player1": {"id": f"{event}-p1", "name": "Alpha", "probability": 0.70},
        "player2": {"id": f"{event}-p2", "name": "Beta", "probability": 0.30},
        "betting": {
            "market": "match_winner",
            "selection_id": f"{event}-sel",
            "selection": selection,
            "odds": odds,
            "model_probability": 0.70,
            "edge": 0.08,
            "expected_value": 0.10,
            "betting_day": day,
        },
    }


def publication_for(row: dict, section: str, *, issued: bool = True) -> dict:
    betting = row["betting"]
    return {
        "section": section,
        "market": betting["market"],
        "selection_id": betting["selection_id"],
        "selection": betting["selection"],
        "odds": betting["odds"],
        "model_probability": betting["model_probability"],
        "edge": betting["edge"],
        "expected_value": betting["expected_value"],
        "betting_day": betting["betting_day"],
        "projection": None,
        "opponent_projection": None,
        "projection_scope": None,
        "projection_metric": None,
        "projection_confidence": None,
        "projection_label": None,
        "issued_at": "2026-09-21T06:30:00+00:00" if issued else None,
        "publication_status": "published" if issued else "pending",
    }


def test_r55_release_identity_and_no_bookmaker_experiment():
    release = (WEB / "release.json").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert '"patch": "736-r55"' in release
    assert 'content="736-r55"' in index
    assert '/app.js?v=7360&p=55' in index
    assert "hub-row-started" in app
    assert "hub-offer-status" in app
    assert "bookmaker_availability" not in app


def test_r55_carries_only_issued_rows_and_preserves_morning_order():
    now = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    morning_a = winner_row("a", "2026-09-21T08:00:00+00:00", selection="Alpha", odds=1.70)
    morning_b = winner_row("b", "2026-09-21T09:00:00+00:00", selection="Alpha", odds=1.80)
    pending = winner_row("p", "2026-09-21T10:00:00+00:00", selection="Alpha", odds=1.90)
    current_b_changed = winner_row("b", "2026-09-21T09:00:00+00:00", selection="Beta", odds=2.40)
    current_c = winner_row("c", "2026-09-21T21:00:00+00:00", selection="Alpha", odds=1.65)

    prior = {"top_daily_picks": [morning_a, morning_b, pending]}
    current = {"top_daily_picks": [current_c, current_b_changed], "market_selection": {}}
    ledger = [
        {"event_id": "a", "market_publications": [publication_for(morning_a, "top_daily", issued=True)]},
        {"event_id": "b", "market_publications": [publication_for(morning_b, "top_daily", issued=True)]},
        {"event_id": "p", "market_publications": [publication_for(pending, "top_daily", issued=False)]},
        {"event_id": "c", "market_publications": [publication_for(current_c, "top_daily", issued=False)]},
    ]

    merged, report = carry_forward_betting_day_market_rows(current, prior, ledger, now=now)
    rows = merged["top_daily_picks"]
    assert [row["event_id"] for row in rows] == ["a", "b", "c"]
    # The already-issued morning choice must win over a later model/provider flip.
    assert rows[1]["selection"] == "Alpha"
    assert rows[1]["odds"] == 1.80
    assert report["carried"]["top_daily_picks"] == 2
    assert report["new"]["top_daily_picks"] == 1


def test_r55_does_not_carry_yesterday_after_six_am_boundary():
    now = datetime(2026, 9, 22, 5, 0, tzinfo=timezone.utc)  # 07:00 Bratislava
    old = winner_row("old", "2026-09-21T08:00:00+00:00", selection="Alpha", odds=1.70, day="2026-09-21")
    fresh = winner_row("fresh", "2026-09-22T09:00:00+00:00", selection="Alpha", odds=1.75, day="2026-09-22")
    prior = {"top_daily_picks": [old]}
    current = {"top_daily_picks": [fresh], "market_selection": {}}
    ledger = [
        {"event_id": "old", "market_publications": [publication_for(old, "top_daily", issued=True)]},
        {"event_id": "fresh", "market_publications": [publication_for(fresh, "top_daily", issued=False)]},
    ]
    merged, report = carry_forward_betting_day_market_rows(current, prior, ledger, now=now)
    assert [row["event_id"] for row in merged["top_daily_picks"]] == ["fresh"]
    assert report["betting_day"] == "2026-09-22"


def test_r55_visible_feed_keeps_started_offer_until_day_rollover():
    raw = {
        "generated_at": "2026-09-21T08:00:00+00:00",
        "upcoming": [winner_row("x", "2026-09-21T09:00:00+00:00", selection="Alpha", odds=1.70)],
        "top_daily_picks": [winner_row("x", "2026-09-21T09:00:00+00:00", selection="Alpha", odds=1.70)],
        "prime_picks": [], "value_picks": [], "doubles_picks": [], "ace_picks": [], "sg_picks": [],
        "results": [],
    }
    late = visible_feed(deepcopy(raw), now=datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc))
    assert late["upcoming"] == []
    assert [r["event_id"] for r in late["top_daily_picks"]] == ["x"]

    next_day = visible_feed(deepcopy(raw), now=datetime(2026, 9, 22, 5, 0, tzinfo=timezone.utc))
    assert next_day["top_daily_picks"] == []


def test_r55_persistent_snapshot_keeps_current_day_offer_independent_of_future_discovery():
    now = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    morning = winner_row("morning", "2026-09-21T08:00:00+00:00", selection="Alpha", odds=1.70)
    later = winner_row("later", "2026-09-21T21:00:00+00:00", selection="Alpha", odds=1.80)
    feed = {
        "top_daily_picks": [morning, later],
        "prime_picks": [],
        "value_picks": [],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
    }
    snapshot = build_daily_offer_snapshot(feed, now=now)
    assert snapshot["betting_day"] == "2026-09-21"
    assert [row["event_id"] for row in snapshot["top_daily_picks"]] == ["morning", "later"]
    assert snapshot["totals"]["top_daily_picks"] == 2


def test_r55_pipeline_persists_and_reloads_daily_offer_snapshot_asset():
    pipeline = (ROOT / "scripts" / "pipeline.py").read_text(encoding="utf-8")
    assert '"daily_offer_snapshot.json" if "daily_offer_snapshot.json" in assets else None' in pipeline
    assert 'prior_snapshot = read_json(prediction_dir / "daily_offer_snapshot.json", {})' in pipeline
    assert 'snapshot_source = prior_snapshot if isinstance(prior_snapshot, dict) and prior_snapshot else prior_feed' in pipeline
    assert 'write_json(store.directory / "daily_offer_snapshot.json", snapshot)' in pipeline
    assert 'store.directory / "daily_offer_snapshot.json",' in pipeline
