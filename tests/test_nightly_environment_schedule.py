from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/environment-enrichment.yml").read_text(encoding="utf-8")


def test_nightly_environment_schedule_is_dst_safe_and_bounded():
    assert "cron: '0 18 * * *'" in WORKFLOW
    assert "cron: '0 19 * * *'" in WORKFLOW
    assert 'ZoneInfo("Europe/Bratislava")' in WORKFLOW
    assert "local_now.hour == 20" in WORKFLOW
    assert "replace(hour=5, minute=0, second=0, microsecond=0)" in WORKFLOW
    assert "should_run" in WORKFLOW


def test_scheduled_environment_run_writes_without_tennisapi():
    assert "github.event_name == 'schedule' && 'write'" in WORKFLOW
    assert "github.event_name == 'schedule' && '4000'" in WORKFLOW
    assert "github.event_name == 'schedule' && 'true' || inputs.static_only" in WORKFLOW
    assert "enrich-weather-nightly:" in WORKFLOW
    assert '--max-requests "2000"' in WORKFLOW
    assert "nightly-data-audit:" in WORKFLOW
    assert "RAPIDAPI_KEY" not in WORKFLOW
