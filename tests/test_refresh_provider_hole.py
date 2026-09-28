from datetime import date

import pytest

import pipeline
from tbt.errors import ProviderError


class _Provider:
    def __init__(self, fail_day):
        self.fail_day = fail_day
        self.calls = []

    def matches_for_day(self, tour, day, historical):
        self.calls.append((tour, day, historical))
        if day == self.fail_day:
            raise ProviderError(f"RapidAPI HTTP 403 for {day.isoformat()}")
        return []


class _Store:
    def upload_bundle(self, *args, **kwargs):
        raise AssertionError("empty refresh must not upload history")


def test_refresh_skips_one_broken_past_provider_day(tmp_path):
    provider = _Provider(date(2026, 9, 22))
    matches, skipped = pipeline._refresh_history(
        provider, [], tmp_path, _Store(),
        date(2026, 9, 21), date(2026, 9, 23),
    )

    assert matches == []
    assert skipped == {"2026-09-22"}
    # Once the shared calendar discovery for a day fails, do not waste another
    # request trying the WTA path for the same broken historical date.
    assert ("wta", date(2026, 9, 22), True) not in provider.calls
    # Adjacent days still continue, so a one-day provider hole cannot kill refresh.
    assert ("atp", date(2026, 9, 23), True) in provider.calls
    assert ("wta", date(2026, 9, 23), True) in provider.calls


def test_refresh_keeps_current_day_fail_closed(tmp_path):
    provider = _Provider(date(2026, 9, 23))
    with pytest.raises(ProviderError, match="403"):
        pipeline._refresh_history(
            provider, [], tmp_path, _Store(),
            date(2026, 9, 21), date(2026, 9, 23),
        )
