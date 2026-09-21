from datetime import datetime, timedelta, timezone

from tbt.services.engine import performance_windows


def _row(now, days_ago, publications):
    return {
        "event_id": f"e-{days_ago}-{len(publications)}-{id(publications)}",
        "scheduled_at": (now - timedelta(days=days_ago)).isoformat(),
        "market_publications": publications,
    }


def _bet(section, correct):
    return {
        "section": section, "market": "match_winner", "selection_id": "A", "issued_at": "2026-09-01T00:00:00+00:00",
        "price_status": "priced", "odds": 1.5,
        "result": {"correct": correct, "staked_units": 1.0, "profit_units": .5 if correct else -1.0},
    }


def _projection(section, market, hit):
    return {
        "section": section, "market": market, "selection_id": f"{market}:x", "issued_at": "2026-09-01T00:00:00+00:00",
        "price_status": "projection_only", "result": {"status": "hit" if hit else "miss", "correct": hit},
    }


def test_category_best_windows_prefer_larger_sample_when_history_is_young():
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    rows = [
        _row(now, 1, [_bet("top_daily", True), _projection("ace", "aces", True)]),
        _row(now, 2, [_bet("top_daily", True), _projection("ace", "aces", True)]),
        _row(now, 5, [_bet("top_daily", False), _projection("ace", "aces", False)]),
        _row(now, 6, [_bet("top_daily", True), _projection("ace", "aces", True)]),
    ]
    windows, summary = performance_windows([], rows, now=now)
    assert windows["3"]["betting"]["sections"]["top_daily"]["n"] == 2
    assert windows["7"]["betting"]["sections"]["top_daily"]["n"] == 4
    top = summary["categories"]["top_daily"]
    ace = summary["categories"]["ace"]
    assert top["best_days"] == 7 and top["best_n"] == 4
    assert ace["best_days"] == 7 and ace["best_n"] == 4
    assert summary["categories"]["games"]["selection_mode"] == "no_settled_results"
