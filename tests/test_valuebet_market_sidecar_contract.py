from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_valuebet_sidecar_request_is_cc_by_and_non_production():
    request = json.loads(
        (ROOT / ".github/valuebet-market-sidecar-request.json").read_text(encoding="utf-8")
    )
    assert request["mode"] == "publish-sidecar"
    assert request["license"] == "CC BY 4.0"
    assert request["zero_provider_api_requests"] is True
    assert request["production_mutated"] is False
    assert request["years"] == [2021, 2022, 2023, 2024, 2025, 2026]


def test_valuebet_workflow_is_sidecar_only_and_unscheduled():
    workflow = (
        ROOT / ".github/workflows/valuebet-market-sidecar.yml"
    ).read_text(encoding="utf-8")
    assert "link_valuebetennis_market_history.py" in workflow
    assert "research/historical_market/valuebet" in workflow
    assert "valuebetennis-matchs-$year.csv" in workflow
    assert "api_requests" in workflow
    assert "production_mutated" in workflow
    assert "write_year_partition" not in workflow
    assert "import_offline_market_history.py" not in workflow
    assert "  schedule:" not in workflow
    assert "CC BY 4.0" in workflow
    assert "closing_validation_only" in workflow
