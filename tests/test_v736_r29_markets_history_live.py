from datetime import datetime, timedelta, timezone
from pathlib import Path

from tbt.services.engine import PERFORMANCE_BEST_MIN_SAMPLE, performance_windows
from tbt.services.live_comeback import DEFAULT_MAX_ODDS, DEFAULT_MIN_PROBABILITY


ROOT = Path(__file__).resolve().parents[1]


def _winner_row(i: int, when: datetime, correct: bool):
    p1 = "A" if correct else "B"
    return {
        "event_id": str(i),
        "scheduled_at": when.isoformat(),
        "player1": {"id": "A", "probability": .70},
        "player2": {"id": "B", "probability": .30},
        "result": {"winner_id": p1, "correct": correct},
    }


def test_best_history_window_requires_stable_sample_before_marketing_highlight():
    now = datetime(2026, 9, 20, 8, tzinfo=timezone.utc)
    rows = []
    # 20 perfect recent rows would look spectacular but are deliberately too
    # small to win the marketing card. Add 20 older rows so 10/14/30-day windows
    # have a stable denominator and a more representative accuracy.
    for i in range(20):
        rows.append(_winner_row(i, now - timedelta(days=2, hours=i), True))
    for i in range(20, 40):
        rows.append(_winner_row(i, now - timedelta(days=8, hours=i), i % 2 == 0))

    windows, summary = performance_windows(rows, [], now=now)

    assert PERFORMANCE_BEST_MIN_SAMPLE == 30
    assert windows["3"]["model"]["n"] == 20
    assert summary["best_n"] >= 30
    assert summary["best_days"] in {10, 14, 30}
    assert summary["selection_mode"] == "best_accuracy_min_sample"
    assert summary["transparent_all_windows"] is True


def test_live_radar_defaults_match_real_prime_supply_instead_of_rejecting_it():
    assert DEFAULT_MIN_PROBABILITY == .68
    assert DEFAULT_MAX_ODDS == 1.49


def test_r29_frontend_contract_has_separate_df_tab_new_loader_and_history_windows():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    config = (ROOT / "web" / "ui-config.json").read_text(encoding="utf-8")
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    loader = ROOT / "web" / "assets" / "blinq_loading_r29.svg"

    assert "double_faults:'DVOJCHYBY'" in app
    assert "['3',lcopy('3 days'" in app
    assert "['10',lcopy('10 days'" in app
    assert "['14',lcopy('14 days'" in app
    assert "performance_window_summary" in app
    assert '"double_faults"' in config
    assert '"ui_patch": "736-r29"' in config
    assert "blinq_loading_r29.svg" in index
    assert loader.is_file()
    # The supplied loader contained a metadata-heavy embedded PNG (~1.7 MB).
    # r29 preserves the visual/animation but strips that payload down so the
    # loading screen itself does not become the slowest resource.
    assert loader.stat().st_size < 250_000
    assert "data:image/jpeg;base64," in loader.read_text(encoding="utf-8")
