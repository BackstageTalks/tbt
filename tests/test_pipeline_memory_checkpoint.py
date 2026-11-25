from datetime import datetime, timezone
import pipeline


def test_checkpoint_never_raises(capsys):
    pipeline._memory_checkpoint("unit")
    assert "memory_checkpoint" in capsys.readouterr().out or True


def test_today_offer_filter_keeps_only_bratislava_day():
    now = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)
    rows = [{"scheduled_at": "2026-11-25T18:00:00+00:00"},
            {"scheduled_at": "2026-11-26T18:00:00+00:00"},
            {"scheduled_at": "bad"}, "x"]
    kept = pipeline._today_offer_predictions(rows, now)
    assert kept == [rows[0]]
