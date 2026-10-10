from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MORNING = (ROOT / ".github/workflows/morning-refresh.yml").read_text(
    encoding="utf-8"
)
DATA = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")


def test_morning_refresh_uses_external_cron_and_existing_pipeline():
    assert "workflow_dispatch:" in MORNING
    assert "  schedule:" not in MORNING
    assert "  schedule:" not in DATA
    assert "gh workflow run data.yml" in MORNING
    assert "-f mode=refresh" in MORNING
    assert "-f morning_refresh=true" in MORNING
    assert "Prevent a second paid morning dispatch" in MORNING
    assert "steps.daily_guard.outputs.dispatch == 'true'" in MORNING
    assert "-f betting_day_start_hour=6" in MORNING
    assert "github.event_name == 'workflow_dispatch'" in MORNING


def test_morning_refresh_is_request_capped_and_reuses_data_deploy_locks():
    assert "MORNING_MAX_REQUESTS" in MORNING
    assert "max_requests=\"$MORNING_MAX_REQUESTS\"" in MORNING
    assert "actions: write" in MORNING
    assert "group: tbt-crossrepo-writer-${{ github.run_id }}" in DATA
    assert "group: tbt-production-deploy" in DATA
    assert "group: tbt-production-deploy" in DATA
    assert "Confirm exactly deployed prediction publication" in DATA


def test_pre_dawn_completion_does_not_wait_for_optional_artwork():
    pipeline = (ROOT / "scripts/pipeline.py").read_text(encoding="utf-8")
    assert "morning_selection_now(" in pipeline
    assert "morning_publication_delay(" in pipeline
    assert "time.sleep(delay)" in pipeline
    assert "morning_refresh=args.morning_refresh" in pipeline
    assert "morning_presentation:" in DATA
    assert "needs: [pipeline, deploy]" in DATA
    assert "mode=deploy-current" in DATA
    assert "MORNING_REFRESH != 'true'" in DATA
