from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/environment-enrichment.yml").read_text(encoding="utf-8")
REQUEST = (ROOT / ".github/nightly-environment-request.json").read_text(encoding="utf-8")


def test_nightly_environment_is_externally_triggered_and_bounded():
    assert "paths:" in WORKFLOW
    assert ".github/nightly-environment-request.json" in WORKFLOW
    assert "cron:" not in WORKFLOW
    assert 'ZoneInfo("Europe/Bratislava")' in WORKFLOW
    assert "local_now.hour >= 20 or local_now.hour < 5" in WORKFLOW
    assert "replace(hour=5, minute=0, second=0, microsecond=0)" in WORKFLOW
    assert "should_run" in WORKFLOW


def test_nightly_environment_writes_without_tennisapi():
    assert 'mode = "write"' in WORKFLOW
    assert 'static_max_requests' in WORKFLOW
    assert 'weather_max_requests' in WORKFLOW
    assert "enrich-weather-nightly:" in WORKFLOW
    assert "nightly-data-audit:" in WORKFLOW
    assert "RAPIDAPI_KEY" not in WORKFLOW
    assert '"static_max_requests": 4000' in REQUEST
    assert '"weather_max_requests": 2000' in REQUEST
