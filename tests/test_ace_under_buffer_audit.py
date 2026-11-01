"""Read-only audit never treats invented odds as historical ROI."""
from tbt.services.ace_under_buffer import ace_under_eligible
from scripts.audit_ace_under_buffer import replay


def _row(event, mean, line, actual, *, real=True, odds=1.8):
    return {
        "event_id": event,
        "market_publications": [{
            "publication_key": f"ace:{event}:under:{line}",
            "market": "aces", "price_contract": "player_total_ou",
            "ou_side": "under", "market_line": line, "projection": mean,
            "selection_id": "A", "publication_status": "published",
            "price_status": "priced_projection" if real else "projection_only",
            "odds": odds, "odds_source": "rapidapi" if real else None,
            "provider_id": 1 if real else None,
            "captured_at": "2026-10-01T09:00:00+00:00",
            "issued_at": "2026-10-01T10:00:00+00:00",
            "result": {
                "scheduled_at": "2026-10-01T13:00:00+00:00",
                "status": "hit" if actual < line else "miss",
                "correct": actual < line,
                "actual_count": actual,
            },
        }],
    }


def test_real_historical_filter_replay_reports_true_denominator_and_units():
    payload = [
        _row("tight-loss", 2.1, 2.5, 3),
        _row("preferred-hit", 9.5, 12.5, 10),
        _row("minimum-loss", 9.5, 11.5, 13),
        _row("tight-hit", 4.1, 5.5, 2),
        _row("synthetic-not-roi", 2.1, 4.5, 0, real=False),
    ]
    result = replay(payload)
    assert result["before_filter"]["bets"] == 4
    assert result["before_filter"]["hits"] == 2
    assert result["after_minimum_buffer"]["bets"] == 2
    assert result["after_minimum_buffer"]["hits"] == 1
    assert result["removed_by_buffer"] == 2
    assert result["preferred_buffer_existing_offers"]["bets"] == 1
    assert result["before_filter"]["profit_units"] == -0.4
    assert result["after_minimum_buffer"]["profit_units"] == -0.2
    assert result["alternatives_replayed"] is False


def test_duplicate_rows_and_post_match_quotes_are_excluded():
    row = _row("x", 9.5, 12.5, 10)
    too_late = _row("y", 9.5, 12.5, 10)
    too_late["market_publications"][0]["captured_at"] = "2026-10-01T15:00:00+00:00"
    report = replay({"ledger": [row, row, too_late]})
    assert report["real_quote_settled_count"] == 1
    assert report["before_filter"]["bets"] == 1
    assert ace_under_eligible(9.5, 12.5)
