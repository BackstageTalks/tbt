from datetime import date, datetime, timezone
from types import SimpleNamespace

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
    matches = pipeline._refresh_history(
        provider, [], tmp_path, _Store(),
        date(2026, 9, 21), date(2026, 9, 23),
    )

    assert matches == []
    assert provider._tbt_skipped_history_days == {"2026-09-22"}
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


def test_refresh_batches_partition_persistence_across_all_days(monkeypatch, tmp_path):
    class Provider:
        def matches_for_day(self, tour, day, historical):
            return [SimpleNamespace(
                is_completed=True,
                scheduled_at=datetime.combine(
                    day, datetime.min.time(), tzinfo=timezone.utc
                ),
            )]

    accepted = []

    def merge(matches, incoming, *, day, tour):
        row = SimpleNamespace(
            scheduled_at=datetime.combine(
                day, datetime.min.time(), tzinfo=timezone.utc
            ),
        )
        accepted.append((day, tour))
        return [*matches, row], [row]

    sync_calls = []

    def sync(matches, history_dir, year):
        sync_calls.append(year)
        path = history_dir / f"history-{year}.parquet"
        path.write_bytes(b"test")
        (history_dir / "history_manifest.json").write_text(
            "{}", encoding="utf-8"
        )
        return path, False

    class Store:
        def __init__(self):
            self.calls = []

        def upload_bundle(self, bundle, **kwargs):
            self.calls.append(([str(path) for path in bundle], kwargs))

    monkeypatch.setattr(pipeline, "_merge_refresh_batch_safely", merge)
    monkeypatch.setattr(pipeline, "_provider_event_id", lambda match: None)
    monkeypatch.setattr(pipeline, "sync_year_partition", sync)

    store = Store()
    pipeline._refresh_history(
        Provider(), [], tmp_path, store,
        date(2026, 9, 21), date(2026, 9, 23),
    )

    assert len(accepted) == 6
    assert sync_calls == [2026]
    assert len(store.calls) == 1
    assert store.calls[0][0][-1].endswith("history_manifest.json")
