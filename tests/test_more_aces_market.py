"""Regression coverage for the independent VIAC ES market."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from tbt.schemas import MatchRecord
from tbt.services.ace_selection import select_ace_winner_picks
from tbt.services.match_status import _grade_runtime_projection
from tbt.services.admin_storage import resolve_ui_access_config, validate_ui_config


def _historical(mid, when, p1, p2, a1, a2):
    return MatchRecord(
        match_id=mid, tour="atp", scheduled_at=when,
        player1_id=p1, player1_name=p1, player2_id=p2,
        player2_name=p2, winner_id=p1, status="finished",
        surface="hard", tournament="History",
        stats={"p1_aces": a1, "p2_aces": a2,
               "p1_double_faults": 1, "p2_double_faults": 2},
    )


def test_independent_most_aces_is_not_bookmaker_player_total():
    now = datetime(2026, 11, 8, 10, tzinfo=timezone.utc)
    history = []
    for i in range(12):
        when = now - timedelta(days=20 + i * 7)
        history.append(_historical(f"a{i}", when, "A", f"X{i}", 11, 2))
        history.append(_historical(f"b{i}", when, "B", f"Y{i}", 2, 11))
    fixture = {
        "id": "future", "event_id": "999",
        "scheduled_at": (now + timedelta(hours=4)).isoformat(),
        "tour": "ATP", "surface": "hard",
        "player1": {"id": "A", "name": "Alpha"},
        "player2": {"id": "B", "name": "Beta"},
    }
    picks, report = select_ace_winner_picks(history, [fixture], now=now)
    assert report["most_aces_selected"] == 1
    assert len(picks) == 1
    pick = picks[0]
    assert pick["market"] == "most_aces"
    assert pick["price_contract"] == "player_superiority"
    assert pick["selection_id"] == "A"
    assert pick["projection"] > pick["opponent_projection"]
    assert pick["odds"] is None and pick["probability"] is None


def _grade(first, second, *, include_opponent=True):
    row = {
        "scheduled_at": "2026-11-08T16:00:00+00:00",
        "event_id": "event1",
        "player1": {"id": "A", "name": "Alpha"},
        "player2": {"id": "B", "name": "Beta"},
    }
    publication = {
        "section": "ace_winner", "market": "most_aces",
        "issued_at": "2026-11-08T10:00:00+00:00",
        "selection_id": "A", "selection": "Alpha",
        "price_contract": "player_superiority",
        "price_status": "projection_only", "odds": None,
        "projection": 8, "opponent_projection": 5,
    }
    stats = {"p1_aces": first}
    if include_opponent:
        stats["p2_aces"] = second
    status = {
        "status": "win", "provider_home_id": "A", "provider_away_id": "B",
        "projection_stats_p1_id": "A", "projection_stats_p2_id": "B",
        "projection_stats": stats,
    }
    return _grade_runtime_projection(row, publication, status)


def test_most_aces_success_loss_tie_and_missing_opponent():
    hit, miss, draw = _grade(8, 5), _grade(4, 9), _grade(6, 6)
    assert hit["result"]["status"] == "hit"
    assert miss["result"]["status"] == "miss"
    assert draw["result"]["status"] == "void"
    assert draw["result"]["correct"] is None
    assert draw["result"]["reason"] == "aces_equal"
    assert hit["result"]["opponent_actual_count"] == 5
    assert "profit_units" not in hit["result"]
    assert _grade(8, 5, include_opponent=False) is None


def test_ui_config_includes_regular_most_aces_tab_and_stats_control():
    config = resolve_ui_access_config(None)
    tabs = config["dashboard"]["daily_hub"]["tabs"]
    assert "ace_winner" in tabs
    assert tabs["ace_winner"]["enabled"] is True
    assert tabs["ace_winner"]["plans"]["elite"]["visible_rows"] == "ALL"
    assert tabs["ace_winner"]["plans"]["rookie"]["visible_rows"] == 0
    complete = json.loads((Path(__file__).resolve().parents[1] / 'web' / 'ui-config.json').read_text(encoding='utf-8'))
    assert validate_ui_config(complete)['dashboard']['daily_hub']['tabs']['ace_winner']['enabled'] is True


def test_most_aces_rejects_missing_contract_and_a_player_total_line():
    from tbt.services.match_status import _grade_runtime_projection
    row = {
        "scheduled_at": "2026-11-08T16:00:00+00:00",
        "event_id": "event1",
        "player1": {"id": "A", "name": "Alpha"},
        "player2": {"id": "B", "name": "Beta"},
    }
    status = {
        "status": "win",
        "provider_home_id": "A", "provider_away_id": "B",
        "projection_stats_p1_id": "A", "projection_stats_p2_id": "B",
        "projection_stats": {"p1_aces": 9, "p2_aces": 4},
    }
    valid = {
        "market": "most_aces",
        "section": "ace_winner",
        "price_contract": "player_superiority",
        "issued_at": "2026-11-08T10:00:00+00:00",
        "selection_id": "A",
    }
    assert _grade_runtime_projection(row, valid, status)["result"]["correct"] is True
    assert _grade_runtime_projection(row, {**valid, "price_contract": ""}, status) is None
    assert _grade_runtime_projection(row, {**valid, "market_line": 4.5}, status) is None
    assert _grade_runtime_projection(row, {**valid, "ou_side": "over"}, status) is None


def test_new_tab_has_results_kpis_admin_export_and_responsive_placement():
    root = Path(__file__).resolve().parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    css = (root / "web" / "blinq-daily-hub-mobile.css").read_text(encoding="utf-8")
    assert "const DAILY_HUB_TABS=['daily','prime','value','ace','ace_winner'" in app
    assert "value:'value',ace:'ace',ace_winner:'ace_winner'" in app
    assert "if(category==='ace_winner')return String(publication?.market||'')==='most_aces'" in app
    assert "const STATS_MARKET_TABS={daily:" in app and "ace_winner:'ace_winner'" in app
    assert "['doubles','Štvorhra'],['ace','Esá'],['ace_winner','Viac es']" in app
    assert "['daily','prime','value','ace','ace_winner','double_faults'" in app
    assert '[data-tab="ace_winner"]' in css
    assert 'grid-area:projection!important' in css
    assert 'if(value===\'aces_equal\')return lcopy(\'TIE\',\'REMÍZA\',\'REMÍZA\')' in app
    assert "const sample=graded.length" in app
    assert "roi:stake?profit/stake:null" in app
