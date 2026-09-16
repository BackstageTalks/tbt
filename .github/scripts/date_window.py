from datetime import date, datetime, timedelta, timezone


def history_window(start=None, end=None, lookback_days=1095, today=None):
    today = today or datetime.now(timezone.utc).date()
    if not 1 <= int(lookback_days) <= 36500:
        raise ValueError('lookback_days must be 1..36500')
    last = date.fromisoformat(end) if end else today - timedelta(days=1)
    first = date.fromisoformat(start) if start else last - timedelta(days=int(lookback_days) - 1)
    if first > last or last >= today:
        raise ValueError('Use start <= end < today UTC')
    return first, last
