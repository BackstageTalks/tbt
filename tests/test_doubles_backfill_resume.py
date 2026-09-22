from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = spec_from_file_location("enrich_doubles_history_test_module", SCRIPTS / "enrich_doubles_history.py")
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
_resume_window = module._resume_window


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
