import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def _planner():
    path = ROOT / "scripts/plan_player_enrichment_budget.py"
    spec = importlib.util.spec_from_file_location("plan_player_enrichment_budget", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_is_r40():
    release = json.loads(_text("web/release.json"))
    ui = json.loads(_text("web/ui-config.json"))
    assert release["patch"] == ui["ui_patch"] == "736-r44"
    assert 'content="736-r44"' in _text("web/index.html")


def test_b05_data_deploy_has_shared_production_critical_section():
    workflow = _text(".github/workflows/data.yml")
    assert "group: tbt-history-data-writer" in workflow  # whole data writer remains serialized
    assert "name: Deploy current prediction generation" in workflow
    assert workflow.count("group: tbt-production-deploy") >= 1
    assert "inputs.mode == 'refresh'" in workflow
    assert "format('tbt-data-pipeline-{0}', github.run_id)" in workflow
    pipeline_prefix = workflow.split("  deploy:\n", 1)[0]
    assert "Azure/static-web-apps-deploy@v1" not in pipeline_prefix
    assert "confirm_prediction_publication.py" not in pipeline_prefix


def test_b05_player_enrichment_no_longer_mutates_prediction_release():
    workflow = _text(".github/workflows/player-enrichment.yml")
    assert "scripts/pipeline.py refresh" not in workflow
    assert "group: tbt-history-data-writer" not in workflow
    assert "group: tbt-player-assets-writer" in workflow
    assert "group: tbt-production-deploy" in workflow


def test_b28_environment_inputs_are_data_not_shell_source():
    audit = _text(".github/workflows/environment-audit.yml")
    enrich = _text(".github/workflows/environment-enrichment.yml")
    assert 'ARGS+=(--start "${{ inputs.start }}")' not in audit
    assert 'ARGS+=(--end "${{ inputs.end }}")' not in audit
    assert 'END_VALUE="${{ inputs.end }}"' not in enrich
    assert '--start "${{ inputs.start }}"' not in enrich
    assert "BLINQ_INPUT_START: ${{ inputs.start }}" in audit
    assert "BLINQ_INPUT_START: ${{ inputs.start }}" in enrich


def test_b16_budget_planner_never_exceeds_total():
    m = _planner()
    result = m.plan(750, {"photo": 250, "fallback_ranking": 120, "player_detail": 250, "tournament_logo": 120}, already_used=300)
    assert result["planned_total_max"] <= 750
    assert result["ranking_snapshot_overhead"] == 2
    assert sum(result["phase_caps"].values()) <= 448


def test_b16_budget_planner_skips_when_refresh_consumed_cap():
    m = _planner()
    result = m.plan(100, {"photo": 250, "fallback_ranking": 120, "player_detail": 250, "tournament_logo": 120}, already_used=100)
    assert result["planned_enrichment_max"] == 0
    assert all(value == 0 for value in result["phase_caps"].values())


def test_b16_public_render_never_constructs_paid_asset_proxy_urls():
    app = _text("web/app.js")
    assert "`/api/v1/player-image/${" not in app
    assert "`/api/v1/tournament-logo/${" not in app
    assert "/api/v1/player-image/" not in _text("api/tbt/services/engine.py")


def test_b16_legacy_asset_endpoints_make_no_provider_calls():
    api = _text("api/function_app.py")
    player = api.split('@app.route(route="v1/player-image/{player_id}"', 1)[1].split('@app.route(route="v1/tournament-logo/{tournament_id}"', 1)[0]
    tournament = api.split('@app.route(route="v1/tournament-logo/{tournament_id}"', 1)[1].split('@app.route(route="v1/ui-config"', 1)[0]
    assert "RapidTennisClient" not in player
    assert "RapidTennisClient" not in tournament
    assert "status_code=404" in player and "status_code=404" in tournament


def test_b16_match_intelligence_is_offline_first():
    api = _text("api/function_app.py")
    assert 'BLINQ_MATCH_INTELLIGENCE_LIVE_PROVIDER' in api
    assert '"live_provider": False' in api
    assert "client.request_limit" in api
