from datetime import date, timedelta


def _resume_window(existing, start, end, *, explicit_start, explicit_end, lookback_days):
    # Mirror the pure window contract from scripts/enrich_doubles_history.py.
    if not existing or explicit_start or explicit_end:
        return start, end

    from datetime import datetime

    existing_days = []
    for row in existing:
        try:
            existing_days.append(
                datetime.fromisoformat(
                    str(row.get("scheduled_at") or "").replace("Z", "+00:00")
                ).date()
            )
        except (ValueError, TypeError, AttributeError):
            pass
    if not existing_days:
        return start, end

    oldest = min(existing_days)
    if oldest > start:
        return start, min(end, oldest - timedelta(days=1))

    next_end = oldest - timedelta(days=1)
    next_start = next_end - timedelta(days=max(1, lookback_days) - 1)
    return next_start, next_end


def test_completed_default_window_steps_one_full_block_back():
    start = date(2023, 9, 23)
    end = date(2026, 9, 21)
    existing = [{"scheduled_at": "2023-09-23T10:00:00+00:00"}]

    next_start, next_end = _resume_window(
        existing,
        start,
        end,
        explicit_start=False,
        explicit_end=False,
        lookback_days=1095,
    )

    assert next_end == date(2023, 9, 22)
    assert next_start == next_end - timedelta(days=1094)
    assert next_start <= next_end


def test_partial_default_window_finishes_gap_before_oldest():
    start = date(2023, 9, 23)
    end = date(2026, 9, 21)
    existing = [{"scheduled_at": "2023-12-19T10:00:00+00:00"}]

    next_start, next_end = _resume_window(
        existing,
        start,
        end,
        explicit_start=False,
        explicit_end=False,
        lookback_days=1095,
    )

    assert next_start == start
    assert next_end == date(2023, 12, 18)


def test_explicit_dates_are_never_rewritten():
    start = date(2021, 1, 1)
    end = date(2023, 9, 22)
    existing = [{"scheduled_at": "2023-09-23T10:00:00+00:00"}]

    assert _resume_window(
        existing,
        start,
        end,
        explicit_start=True,
        explicit_end=True,
        lookback_days=1095,
    ) == (start, end)
