from datetime import datetime, timedelta, timezone

from tbt.services import admin_storage
from test_match_status_chunked_storage import ChunkTable


def test_verified_schedule_is_stored_and_read_back(monkeypatch):
    table = ChunkTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    now = datetime.now(timezone.utc)
    updated = {
        "scheduled_at": (now + timedelta(hours=4)).isoformat(),
        "checked_at": now.isoformat(),
        "source": "tennis_api_pro",
        "status": "scheduled",
    }
    saved = admin_storage.save_match_status_snapshot({
        "schedule_updates": {"17352425": updated},
    })
    assert saved["schedule_updates"]["17352425"]["scheduled_at"] == updated["scheduled_at"]
    readback = admin_storage.load_match_status_snapshot()
    assert readback["schedule_updates"] == saved["schedule_updates"]


def test_storage_rejects_unverified_or_old_schedule(monkeypatch):
    table = ChunkTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    now = datetime.now(timezone.utc)
    saved = admin_storage.save_match_status_snapshot({
        "schedule_updates": {
            "bad": {
                "scheduled_at": now.isoformat(), "checked_at": now.isoformat(),
                "source": "unknown", "status": "live",
            },
            "old": {
                "scheduled_at": now.isoformat(),
                "checked_at": (now - timedelta(hours=25)).isoformat(),
                "source": "tennis_api_pro", "status": "scheduled",
            },
        }
    })
    assert saved["schedule_updates"] == {}


def test_verified_schedule_survives_three_hours_until_betting_day_end(monkeypatch):
    table = ChunkTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    now = datetime.now(timezone.utc)
    updated = {
        "scheduled_at": (now + timedelta(hours=4)).isoformat(),
        "checked_at": (now - timedelta(hours=3)).isoformat(),
        "source": "tennis_api_pro",
        "status": "scheduled",
    }
    saved = admin_storage.save_match_status_snapshot({
        "schedule_updates": {"faria-verified": updated},
    })
    assert "faria-verified" in saved["schedule_updates"]
    assert admin_storage.load_match_status_snapshot()["schedule_updates"] == saved["schedule_updates"]
