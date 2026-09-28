from tbt.services.entitlements import _daily_rows


def _row(event_id: str, probability: float) -> dict:
    return {
        "event_id": event_id,
        "odds": 1.55,
        "blinq_probability": probability,
        "surface": "hard",
        "scheduled_at": "2026-09-25T16:00:00+00:00",
        "winner_id": f"p-{event_id}",
    }


def test_top_hides_fallback_rows_when_at_least_five_core_picks_exist():
    payload = {
        "top_daily_picks": [
            *[_row(f"core-{i}", probability) for i, probability in enumerate((0.824, 0.767, 0.731, 0.726, 0.698, 0.685), start=1)],
            *[_row(f"weak-{i}", probability) for i, probability in enumerate((0.670, 0.668, 0.656, 0.652), start=1)],
        ],
        "value_picks": [],
        "market_selection": {
            "top_daily_rule": {
                "core_min_probability": 0.68,
                "fallback_only_if_core_count_below": 5,
            }
        },
    }

    rows = _daily_rows(payload)

    assert len(rows) == 6
    assert all(row["blinq_probability"] >= 0.68 for row in rows)


def test_top_keeps_fallback_rows_when_core_count_is_below_five():
    payload = {
        "top_daily_picks": [
            *[_row(f"core-{i}", probability) for i, probability in enumerate((0.824, 0.767, 0.731, 0.685), start=1)],
            *[_row(f"weak-{i}", probability) for i, probability in enumerate((0.670, 0.668, 0.656, 0.652), start=1)],
        ],
        "value_picks": [],
        "market_selection": {
            "top_daily_rule": {
                "core_min_probability": 0.68,
                "fallback_only_if_core_count_below": 5,
            }
        },
    }

    rows = _daily_rows(payload)

    assert len(rows) == 8
    assert rows[-1]["blinq_probability"] == 0.652


def test_top_filters_fallback_at_exactly_five_core_picks():
    payload = {
        "top_daily_picks": [
            *[_row(f"core-{i}", probability) for i, probability in enumerate((0.824, 0.767, 0.731, 0.698, 0.685), start=1)],
            _row("weak-1", 0.670),
        ],
        "value_picks": [],
    }

    rows = _daily_rows(payload)

    assert len(rows) == 5
    assert min(row["blinq_probability"] for row in rows) >= 0.68
