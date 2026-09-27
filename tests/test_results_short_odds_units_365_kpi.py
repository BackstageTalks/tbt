"""Results: VOID/SKREČ coloring, Short Odds W/L-only and a 365-day KPI."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tbt.services.engine import betting_performance, performance_windows

ROOT = Path(__file__).resolve().parents[1]


def _settled(now, *, event, section, odds, correct, profit, days=1, void=False):
    result = {"status": "void" if void else ("hit" if correct else "miss"),
              "correct": None if void else correct,
              "staked_units": 0.0 if void else 1.0,
              "profit_units": 0.0 if void else profit,
              "reason": "retired" if void else None}
    return {"event_id": event,
            "scheduled_at": (now - timedelta(days=days)).isoformat(),
            "market_publications": [{
                "market": "match_winner", "section": section,
                "selection_id": event, "issued_at": (now - timedelta(days=days+1)).isoformat(),
                "odds": odds, "price_status": "priced", "result": result,
            }]}


def test_short_odds_is_in_win_loss_and_average_odds_but_not_units_or_roi():
    now = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    rows = [
        _settled(now, event="prime", section="prime", odds=1.06, correct=True, profit=.06),
        _settled(now, event="top", section="top_daily", odds=1.86, correct=False, profit=-1.0),
        _settled(now, event="value", section="value", odds=2.10, correct=True, profit=1.10),
        _settled(now, event="void", section="top_daily", odds=1.65, correct=None, profit=0, void=True),
    ]
    summary = betting_performance(rows)
    overall = summary["overall"]
    assert (overall["n"], overall["wins"], overall["losses"], overall["voids"]) == (3, 2, 1, 1)
    assert abs(overall["hit_rate"] - 2 / 3) < 1e-12
    assert abs(overall["avg_odds"] - (1.06 + 1.86 + 2.10) / 3) < 1e-12
    assert overall["staked_units"] == 2.0
    assert abs(overall["profit_units"] - .10) < 1e-12
    assert abs(overall["roi"] - .05) < 1e-12
    assert summary["sections"]["prime"]["wins"] == 1
    assert summary["sections"]["prime"]["staked_units"] == 0
    assert summary["sections"]["prime"]["profit_units"] == 0
    assert summary["sections"]["prime"]["roi"] is None
    assert summary["markets"]["match_winner"]["staked_units"] == 2.0
    # The historical ledger is immutable; only reporting excludes Short Odds.
    assert rows[0]["market_publications"][0]["result"]["profit_units"] == .06


def test_365_day_kpi_window_preserves_30_day_and_uses_issued_records():
    now = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    old = _settled(now, event="200days", section="top_daily", odds=1.75,
                   correct=True, profit=.75, days=200)
    windows, meta = performance_windows([], [old], now=now)
    assert windows["30"]["betting"]["overall"]["n"] == 0
    assert windows["365"]["betting"]["overall"]["n"] == 1
    assert windows["365"]["betting"]["overall"]["profit_units"] == .75
    assert 30 in meta["windows_days"] and 365 in meta["windows_days"]


def test_results_ui_purple_void_units_and_longer_filter_are_explicit():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
    assert "['365',lcopy('365 days','365 dní','365 dní')]" in app
    assert "shortOddsUnitsExcluded" not in app
    assert "const units=outcome.kind==='void'?0:rawUnits;" in app
    assert "averageOddsHelp" not in app
    assert "if(String(publication?.section||'').toLowerCase()==='prime')continue;" in app
    assert "unitSample" in app
    assert ".results-table b.retired" in css
    assert ".results-table b.void" in css
    assert ".results-table td.void" in css
    assert ".results-units-depth b.void" in css
    assert "color:#c99aff!important" in css


def test_no_tennis_api_results_rebuild_updates_public_dashboard_accuracy():
    rebuild = (ROOT / "scripts" / "rebuild_results_history.py").read_text(encoding="utf-8")
    assert '"dashboard_model_success", "results_meta"' in rebuild
    assert 'for key in (' in rebuild
    assert 'feed[key] = derived[key]' in rebuild
    assert '"immutable_issued_evidence_only"' in rebuild
