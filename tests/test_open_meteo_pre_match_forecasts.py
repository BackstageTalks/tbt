from datetime import datetime, timezone
from types import SimpleNamespace

from scripts.extract_open_meteo_pre_match_forecasts import (
    _eligible,
    _nearest_index,
    _previous_name,
)


def _match(mid="m1", *, indoor=False, resolved=True):
    return SimpleNamespace(
        match_id=mid,
        scheduled_at=datetime(2026, 9, 1, 12, 20, tzinfo=timezone.utc),
        indoor=indoor,
        provider_payload={
            "_tbt_environment": {
                "venue_resolved": resolved,
                "venue": {"latitude": 48.1486, "longitude": 17.1077},
            }
        },
    )


def test_previous_run_variable_is_fixed_24h_lead():
    assert _previous_name("temperature_2m") == "temperature_2m_previous_day1"


def test_nearest_hour_is_bounded():
    times = ["2026-09-01T11:00", "2026-09-01T12:00", "2026-09-01T13:00"]
    idx = _nearest_index(times, datetime(2026, 9, 1, 12, 20, tzinfo=timezone.utc))
    assert idx == 1
    assert _nearest_index(["2026-09-01T09:00"], datetime(2026, 9, 1, 12, 20, tzinfo=timezone.utc)) is None


def test_eligible_requires_outdoor_resolved_venue():
    start = datetime(2026, 9, 1, tzinfo=timezone.utc).date()
    end = datetime(2026, 9, 2, tzinfo=timezone.utc).date()
    rows = _eligible([_match("ok"), _match("indoor", indoor=True), _match("unresolved", resolved=False)], start, end)
    assert [m.match_id for m, _ in rows] == ["ok"]
