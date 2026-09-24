from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MORNING = (ROOT / ".github/workflows/morning-refresh.yml").read_text(
    encoding="utf-8"
)
DATA = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")


def test_morning_refresh_uses_local_betting_day_and_existing_pipeline():
    assert "cron: '17 6 * * *'" in MORNING
    assert "timezone: Europe/Bratislava" in MORNING
    assert "gh workflow run data.yml" in MORNING
    assert "-f mode=refresh" in MORNING
    assert "-f betting_day_start_hour=6" in MORNING
    assert "TBT_MORNING_REFRESH_ENABLED" in MORNING


def test_morning_refresh_is_request_capped_and_reuses_data_deploy_locks():
    assert "MORNING_MAX_REQUESTS" in MORNING
    assert "max_requests=\"$MORNING_MAX_REQUESTS\"" in MORNING
    assert "actions: write" in MORNING
    assert "group: tbt-history-data-writer" in DATA
    assert "group: tbt-production-deploy" in DATA
    assert "group: tbt-production-deploy" in DATA
    assert "Confirm exactly deployed prediction publication" in DATA
