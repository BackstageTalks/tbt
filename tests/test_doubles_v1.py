from datetime import datetime, timedelta, timezone
from pathlib import Path

from tbt.schemas import MatchRecord
from tbt.services.doubles_selection import build_predictions, select_picks, MODEL_VERSION
from tbt.services.market_selection import select_market_sections

ROOT = Path(__file__).resolve().parents[1]


def _members(prefix):
    return [{"id": f"{prefix}1", "name": f"{prefix} One"}, {"id": f"{prefix}2", "name": f"{prefix} Two"}]


def _history_row(i, winner="A"):
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    return {
        "event_id": f"h{i}",
        "scheduled_at": (now - timedelta(days=260-i)).isoformat(),
        "tour": "atp",
        "tournament": "Test Doubles",
        "tournament_id": "99",
        "surface": "hard",
        "round_name": "R16",
        "player1_id": "PAIR-A",
        "player1_name": "Alpha / Beta",
        "player1_members": _members("A"),
        "player2_id": "PAIR-B",
        "player2_name": "Gamma / Delta",
        "player2_members": _members("B"),
        "winner_id": "PAIR-A" if winner == "A" else "PAIR-B",
        "status": "finished",
    }


def _upcoming():
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    return MatchRecord(
        match_id="u1", tour="atp", scheduled_at=now + timedelta(hours=6),
        player1_id="PAIR-A", player1_name="Alpha / Beta",
        player2_id="PAIR-B", player2_name="Gamma / Delta",
        surface="hard", tournament="Test Doubles", tournament_id="99",
        round_name="SF", status="upcoming",
        provider_payload={
            "_tbt_provider_event_id": "u1",
            "homeTeam": {"id": "PAIR-A", "name": "Alpha / Beta", "players": _members("A")},
            "awayTeam": {"id": "PAIR-B", "name": "Gamma / Delta", "players": _members("B")},
            "tournament": {"uniqueTournament": {"id": 99}},
        },
    )


def test_doubles_model_is_separate_and_fail_closed_on_its_own_history():
    history = [_history_row(i, "A" if i % 4 else "B") for i in range(260)]
    rows, report = build_predictions(history, [_upcoming()], now=datetime(2026, 9, 19, tzinfo=timezone.utc))
    assert report["ready"] is True
    assert rows
    row = rows[0]
    assert row["prediction_family"] == "doubles"
    assert row["model_version"] == MODEL_VERSION
    assert row["doubles"]["separate_from_singles"] is True
    assert row["winner_id"] in {"PAIR-A", "PAIR-B"}
    assert row["data_depth"] >= 0.35


def test_doubles_selection_requires_real_price_and_does_not_leak_into_singles_sections():
    history = [_history_row(i, "A" if i % 5 else "B") for i in range(260)]
    rows, _ = build_predictions(history, [_upcoming()], now=datetime(2026, 9, 19, tzinfo=timezone.utc))
    row = rows[0]
    winner = row["winner_id"]
    name = row["player1"]["name"] if winner == row["player1"]["id"] else row["player2"]["name"]
    raw_prob = row["player1"]["probability"] if winner == row["player1"]["id"] else row["player2"]["probability"]
    # Use a valid odds-backed publication shape; the selector still applies its
    # own public probability/EV guardrails.
    row["betting"] = {
        "market": "match_winner", "selection": name, "selection_id": winner,
        "odds": 1.70, "model_probability": raw_prob,
        "blinq_probability": max(0.60, 0.5 + (raw_prob - 0.5) * row["data_depth"]),
        "fair_implied_probability": 0.56, "edge": 0.05,
        "expected_value": 0.08, "betting_day": "2026-09-19",
    }
    picks, report = select_picks([row])
    assert report["odds_backed"] is True
    assert len(picks) == 1
    sections = select_market_sections([row], doubles_picks=picks)
    assert sections["doubles_picks"] == picks
    assert sections["top_daily_picks"] == []
    assert sections["value_picks"] == []
    assert sections["prime_picks"] == []
    assert "doubles_match_winner" in sections["market_selection"]["odds_backed_outputs"]


def test_data_workflow_exposes_doubles_backfill_and_refresh_budget():
    workflow = (ROOT / ".github" / "workflows" / "data.yml").read_text(encoding="utf-8")
    assert "doubles-data" in workflow
    assert "enrich_doubles_history.py" in workflow
    assert "--doubles-odds-max-events" in workflow
